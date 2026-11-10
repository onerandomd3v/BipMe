"""Creator-owned manual publication attachment for immutable Outlooks."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.api.auth import get_token_cipher
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.api.schemas import AcceptedHypothesis, ErrorResponse, StrictModel
from bipme.auth.crypto import TokenCipher
from bipme.integrations.x_publication import (
    PublishedPostEvidence,
    XPublicationUnavailable,
    XPublishedPostVerifier,
    build_x_publication_verifier,
)
from bipme.persistence.models import (
    CanonicalPost,
    CreatorPlatformIdentity,
    DraftAssessment,
    XAccountConnection,
)

router = APIRouter(prefix="/api/v1/creators/me", tags=["publications"])
_POST_ID = re.compile(r"^[0-9]{1,32}$")
_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_PUBLICATION_SOURCE = "x_creator_authorized_publication"
_PUBLICATION_ENDPOINT = "/2/tweets/{id}"
VersionMatchState = Literal["match", "mismatch", "unknown"]


class PublicationLinkRequest(StrictModel):
    """A canonical X URL or numeric post ID; provider timestamps are authoritative."""

    post_url_or_id: str = Field(min_length=1, max_length=2048)

    @field_validator("post_url_or_id")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("post_url_or_id must be trimmed and non-blank")
        return value


class PublicationLinkResponse(StrictModel):
    assessment_id: UUID
    assessed_at: datetime
    assessed_fingerprint: str
    accepted_hypothesis: AcceptedHypothesis | None
    canonical_post_id: UUID
    external_post_id: str
    published_at: datetime
    version_match_state: VersionMatchState


def get_x_publication_verifier(
    cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
) -> Iterator[XPublishedPostVerifier]:
    """Build the gated provider verifier; tests replace this dependency with a fake."""
    verifier = build_x_publication_verifier(cipher)
    try:
        yield verifier
    finally:
        verifier.close()


def parse_x_post_id(value: str) -> str:
    """Accept a numeric ID or a strict HTTPS x.com/twitter.com status URL."""
    if _POST_ID.fullmatch(value):
        return value
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ApiError(422, "invalid_post_reference", "The X post URL or ID is invalid.") from None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or hostname not in {"x.com", "twitter.com"}
    ):
        raise ApiError(422, "invalid_post_reference", "The X post URL or ID is invalid.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 3 or parts[1].lower() != "status" or not _HANDLE.fullmatch(parts[0]):
        if len(parts) != 3 or parts[0].lower() != "i" or parts[1].lower() != "status":
            raise ApiError(422, "invalid_post_reference", "The X post URL or ID is invalid.")
    post_id = parts[2]
    if not _POST_ID.fullmatch(post_id):
        raise ApiError(422, "invalid_post_reference", "The X post URL or ID is invalid.")
    return post_id


def _text_fingerprint(text: str) -> str:
    digest = hashlib.sha256(
        b"bipme-published-text-v1\0"
        + unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"sha256:{digest}"


def _version_match_state(
    assessment: DraftAssessment, evidence: PublishedPostEvidence
) -> VersionMatchState:
    metadata = assessment.decision_snapshot.get("_cod361_linking")
    if not isinstance(metadata, dict) or not isinstance(evidence.text, str):
        return "unknown"
    expected_text = metadata.get("assessed_text_fingerprint")
    expected_topology = metadata.get("topology")
    expected_media = metadata.get("media_present")
    if not isinstance(expected_text, str) or not isinstance(expected_topology, str):
        return "unknown"
    if _text_fingerprint(evidence.text) != expected_text:
        return "mismatch"
    if evidence.topology != expected_topology:
        return "mismatch"
    if not isinstance(expected_media, bool) or evidence.media_present is None:
        return "unknown"
    return "match" if evidence.media_present == expected_media else "mismatch"


def _response(assessment: DraftAssessment, post: CanonicalPost) -> PublicationLinkResponse:
    try:
        hypothesis = (
            AcceptedHypothesis.model_validate(assessment.accepted_hypothesis)
            if assessment.accepted_hypothesis is not None
            else None
        )
    except ValidationError as exc:
        raise ApiError(
            503, "assessment_snapshot_invalid", "The saved assessment is unavailable."
        ) from exc
    assert post.source_assessment_id == assessment.id
    assert post.version_match_state in {"match", "mismatch", "unknown"}
    return PublicationLinkResponse(
        assessment_id=assessment.id,
        assessed_at=assessment.assessed_at,
        assessed_fingerprint=assessment.content_fingerprint,
        accepted_hypothesis=hypothesis,
        canonical_post_id=post.id,
        external_post_id=post.external_post_id,
        published_at=post.published_at,
        version_match_state=cast(VersionMatchState, post.version_match_state),
    )


def _verification_error(error: XPublicationUnavailable) -> ApiError:
    if error.code == "post_not_found":
        return ApiError(404, "published_post_not_found", "The published X post was not found.")
    if error.code in {"permission_denied", "connection_unavailable", "reauthorization_required"}:
        return ApiError(403, "x_account_unavailable", "The authorized X account is unavailable.")
    if error.code == "duplicate_request":
        return ApiError(
            409,
            "publication_verification_in_progress",
            "The publication is already being verified.",
        )
    return ApiError(
        503, "publication_verification_unavailable", "Published post verification is unavailable."
    )


@router.post(
    "/draft-assessments/{assessment_id}/publication",
    response_model=PublicationLinkResponse,
    status_code=201,
    responses={
        200: {"model": PublicationLinkResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Attach a manually published X post to an immutable Outlook",
)
def link_publication(
    assessment_id: UUID,
    payload: PublicationLinkRequest,
    response: Response,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    verifier: Annotated[XPublishedPostVerifier, Depends(get_x_publication_verifier)],
    now: Annotated[datetime, Depends(get_current_time)],
) -> PublicationLinkResponse:
    """Verify and attach one creator-owned publication without changing the Outlook."""
    post_id = parse_x_post_id(payload.post_url_or_id)
    try:
        assessment = db.scalar(
            select(DraftAssessment).where(
                DraftAssessment.id == assessment_id,
                DraftAssessment.creator_id == creator.creator_id,
            )
        )
        if assessment is None:
            raise ApiError(404, "assessment_not_found", "The requested assessment was not found.")

        existing = db.scalar(
            select(CanonicalPost)
            .where(
                CanonicalPost.platform == "x",
                CanonicalPost.external_post_id == post_id,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.creator_id != creator.creator_id:
                raise ApiError(
                    404, "published_post_not_found", "The published X post was not found."
                )
            if existing.source_assessment_id == assessment.id:
                response.status_code = 200
                return _response(assessment, existing)
            if existing.source_assessment_id is not None:
                raise ApiError(
                    409, "published_post_already_linked", "The published X post is already linked."
                )

        try:
            evidence = verifier.verify(
                db, creator_id=creator.creator_id, post_id=post_id, now=now.astimezone(UTC)
            )
        except XPublicationUnavailable as exc:
            raise _verification_error(exc) from None
        if evidence.external_post_id != post_id:
            raise ApiError(
                503,
                "publication_verification_unavailable",
                "Published post verification is unavailable.",
            )
        if evidence.published_at < assessment.assessed_at:
            raise ApiError(
                422,
                "publication_before_assessment",
                "The published post predates the original assessment.",
            )

        locked_assessment = db.scalar(
            select(DraftAssessment)
            .where(
                DraftAssessment.id == assessment_id,
                DraftAssessment.creator_id == creator.creator_id,
            )
            .with_for_update()
        )
        if locked_assessment is None:
            raise ApiError(404, "assessment_not_found", "The requested assessment was not found.")
        locked_connection = db.scalar(
            select(XAccountConnection)
            .join(
                CreatorPlatformIdentity,
                (CreatorPlatformIdentity.id == XAccountConnection.creator_identity_id)
                & (CreatorPlatformIdentity.creator_id == XAccountConnection.creator_id),
            )
            .where(
                XAccountConnection.creator_id == creator.creator_id,
                XAccountConnection.platform == "x",
                XAccountConnection.state == "connected",
                CreatorPlatformIdentity.platform == "x",
            )
            .with_for_update()
        )
        if locked_connection is None:
            raise ApiError(403, "x_account_unavailable", "The authorized X account is unavailable.")
        identity = db.get(CreatorPlatformIdentity, locked_connection.creator_identity_id)
        authorized_user_id = getattr(verifier, "authorized_user_id", None)
        if (
            identity is None
            or identity.external_creator_id != evidence.author_id
            or (
                authorized_user_id is not None
                and identity.external_creator_id != authorized_user_id
            )
        ):
            raise ApiError(
                403,
                "published_post_owner_mismatch",
                "The published X post is not owned by the authorized account.",
            )

        state = _version_match_state(locked_assessment, evidence)
        if existing is None:
            existing = CanonicalPost(
                id=uuid4(),
                creator_id=creator.creator_id,
                platform="x",
                external_post_id=post_id,
                published_at=evidence.published_at,
                availability="available",
                topology=evidence.topology,
                reply_to_external_post_id=evidence.reply_to_external_post_id,
                quoted_external_post_id=evidence.quoted_external_post_id,
                text=evidence.text,
                media_present=evidence.media_present,
                source=_PUBLICATION_SOURCE,
                source_endpoint=_PUBLICATION_ENDPOINT,
                source_observed_at=now.astimezone(UTC),
                provenance={
                    "source": _PUBLICATION_SOURCE,
                    "endpoint": _PUBLICATION_ENDPOINT,
                    "observed_at": now.astimezone(UTC).isoformat(),
                },
                source_assessment_id=locked_assessment.id,
                version_match_state=state,
            )
            db.add(existing)
        else:
            if existing.published_at != evidence.published_at:
                raise ApiError(
                    409,
                    "published_post_changed",
                    "Published post evidence changed; retry verification.",
                )
            existing.source_assessment_id = locked_assessment.id
            existing.version_match_state = state
            existing.topology = evidence.topology
            existing.reply_to_external_post_id = evidence.reply_to_external_post_id
            existing.quoted_external_post_id = evidence.quoted_external_post_id
            if evidence.text is not None:
                existing.text = evidence.text
            if evidence.media_present is not None:
                existing.media_present = evidence.media_present
            existing.source = _PUBLICATION_SOURCE
            existing.source_endpoint = _PUBLICATION_ENDPOINT
            existing.source_observed_at = now.astimezone(UTC)
            existing.provenance = {
                "source": _PUBLICATION_SOURCE,
                "endpoint": _PUBLICATION_ENDPOINT,
                "observed_at": now.astimezone(UTC).isoformat(),
            }
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raced = db.scalar(
                select(CanonicalPost).where(
                    CanonicalPost.platform == "x",
                    CanonicalPost.external_post_id == post_id,
                    CanonicalPost.creator_id == creator.creator_id,
                )
            )
            if raced is not None and raced.source_assessment_id == assessment_id:
                response.status_code = 200
                return _response(locked_assessment, raced)
            raise ApiError(
                409, "publication_link_conflict", "The publication could not be linked."
            ) from None
        except SQLAlchemyError:
            db.rollback()
            raise ApiError(
                503, "publication_store_unavailable", "The publication link could not be saved."
            ) from None
        return _response(locked_assessment, existing)
    except ApiError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "publication_store_unavailable", "The publication link could not be saved."
        ) from None
