"""Authenticated creator-history import and status endpoints."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bipme.api.dependencies import AuthenticatedCreator, get_authenticated_creator, get_db_session
from bipme.api.errors import ApiError
from bipme.auth.config import AuthSettings
from bipme.auth.crypto import TokenCipher
from bipme.integrations.x_read import (
    HttpXReadProvider,
    XCreatorHistoryReader,
    XReadPricing,
    XReadSettings,
)
from bipme.persistence.models import CreatorHistoryImport
from bipme.persistence.usage import XUsageLimits
from bipme.posts.history import CreatorHistoryImporter, import_summary

router = APIRouter(prefix="/api/v1/creators/me/history", tags=["creator-history"])


class HistoryImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    import_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    max_posts: int = Field(default=20, ge=1, le=400)


class HistoryImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    import_id: str
    status: str
    requested_posts: int
    pages_read: int
    imported_posts: int
    next_page_available: bool
    error_code: str | None
    source: str
    started_at: datetime
    completed_at: datetime | None
    provenance: dict[str, object]


def get_history_importer() -> Iterator[CreatorHistoryImporter]:
    """Build the importer only when every external-use and spend gate is explicit."""
    auth = AuthSettings.from_environment()
    enabled = os.getenv("BIPME_X_HISTORY_IMPORT_ENABLED", "false").lower() in {"1", "true", "yes"}
    entitlement = os.getenv("BIPME_X_ACCOUNT_ENTITLEMENT_VERIFIED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    rights = os.getenv("BIPME_X_HISTORY_DATA_RIGHTS_VERIFIED", "false").lower() in {
        "1",
        "true",
        "yes",
    }

    def money(name: str) -> Decimal | None:
        try:
            value = Decimal(os.environ[name])
        except (KeyError, InvalidOperation):
            return None
        return value if value.is_finite() and value > 0 else None

    def instant(name: str) -> datetime | None:
        try:
            value = datetime.fromisoformat(os.environ[name].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            return None
        return value if value.tzinfo is not None else None

    request_cost = money("BIPME_X_HISTORY_REQUEST_COST_USD")
    result_cost = money("BIPME_X_HISTORY_RESULT_COST_USD")
    observed_at = instant("BIPME_X_HISTORY_PRICING_OBSERVED_AT")
    expires_at = instant("BIPME_X_HISTORY_PRICING_EXPIRES_AT")
    source = os.getenv("BIPME_X_HISTORY_PRICING_SOURCE")
    operation_limit = money("BIPME_X_HISTORY_OPERATION_LIMIT_USD")
    import_limit = money("BIPME_X_HISTORY_IMPORT_LIMIT_USD")
    if not (
        enabled
        and entitlement
        and rights
        and auth.x_allowed_user_id
        and auth.token_encryption_ready
        and auth.x_daily_cost_limit
        and request_cost
        and result_cost
        and observed_at
        and expires_at
        and source
        and operation_limit
        and import_limit
    ):
        raise ApiError(
            503, "history_import_unavailable", "Creator history import is not configured."
        )
    settings = XReadSettings(
        enabled=True,
        allowed_user_id=auth.x_allowed_user_id,
        account_entitlement_verified=True,
        data_rights_verified=True,
    )
    cipher = TokenCipher(auth.token_encryption_keys, auth.active_token_key_version or "")
    provider = HttpXReadProvider(settings=settings)
    reader = XCreatorHistoryReader(
        provider=provider,
        cipher=cipher,
        settings=settings,
        pricing=XReadPricing(request_cost, result_cost, observed_at, expires_at, source),
        limits=XUsageLimits(
            money("BIPME_X_HISTORY_TOTAL_LIMIT_USD"),
            auth.x_daily_cost_limit,
            operation_limit,
            import_limit,
        ),
    )
    try:
        yield CreatorHistoryImporter(reader)
    finally:
        provider.close()


@router.post("/imports", response_model=HistoryImportResponse, status_code=200)
def start_history_import(
    request: HistoryImportRequest,
    creator: AuthenticatedCreator = Depends(get_authenticated_creator),  # noqa: B008
    db: Session = Depends(get_db_session),  # noqa: B008
    importer: CreatorHistoryImporter = Depends(get_history_importer),  # noqa: B008
) -> dict[str, object]:
    try:
        return importer.import_history(
            db,
            creator_id=creator.creator_id,
            import_id=request.import_id,
            max_posts=request.max_posts,
        )
    except ValueError as exc:
        raise ApiError(422, "invalid_import_request", "The import request is invalid.") from exc


@router.get("/imports/{import_id}", response_model=HistoryImportResponse)
def get_history_import(
    import_id: str,
    creator: AuthenticatedCreator = Depends(get_authenticated_creator),  # noqa: B008
    db: Session = Depends(get_db_session),  # noqa: B008
) -> dict[str, object]:
    row = db.scalar(
        select(CreatorHistoryImport).where(
            CreatorHistoryImport.creator_id == creator.creator_id,
            CreatorHistoryImport.import_id == import_id,
        )
    )
    if row is None:
        raise ApiError(404, "history_import_not_found", "The creator history import was not found.")
    return {**import_summary(row), "provenance": {}}
