"""Typed HTTP contracts for report-first creator onboarding and snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bipme.intelligence.creator_goals import CREATOR_GOALS_VERSION, ContentStyle, CreatorOutcome
from bipme.intelligence.creator_report import REPORT_ALGORITHM_VERSION
from bipme.intelligence.report_evidence import REPORT_EVIDENCE_VERSION

MAX_NICHE_LENGTH = 255
MAX_AUDIENCE_LENGTH = 512
GOALS_SCHEMA_VERSION = CREATOR_GOALS_VERSION
REPORT_SCHEMA_VERSION = REPORT_ALGORITHM_VERSION
EVIDENCE_SCHEMA_VERSION = REPORT_EVIDENCE_VERSION


class CreatorProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    niche: str = Field(min_length=2, max_length=MAX_NICHE_LENGTH)
    intended_audience: str = Field(min_length=2, max_length=MAX_AUDIENCE_LENGTH)
    priority_outcomes: list[CreatorOutcome] = Field(min_length=1, max_length=4)
    preferred_styles: list[ContentStyle] = Field(default_factory=list, max_length=6)
    language: str | None = Field(default=None, min_length=2, max_length=64)

    @field_validator("niche", "intended_audience", "language")
    @classmethod
    def trim_declarations(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("declaration cannot be blank")
        return trimmed

    @field_validator("priority_outcomes", "preferred_styles")
    @classmethod
    def require_unique_items(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("declarations must not contain duplicates")
        return value


class CreatorProfileResponse(BaseModel):
    creator_key: UUID
    revision: int
    version: str
    recorded_at: datetime
    niche: str
    intended_audience: str
    priority_outcomes: tuple[CreatorOutcome, ...]
    preferred_styles: tuple[ContentStyle, ...]
    language: str | None


class CreatorProfileStateResponse(BaseModel):
    status: Literal["configured", "not_configured"]
    profile: CreatorProfileResponse | None


class DataPermissionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_personal_history: bool


class DataPermissionResponse(BaseModel):
    personal_history: Literal["granted", "revoked", "not_granted"]
    personal_history_revision: int | None
    recorded_at: datetime | None
    x_history_processing: Literal["blocked", "enabled"]
    niche_discovery: Literal["unavailable"] = "unavailable"
    external_synthesis: Literal["disabled"] = "disabled"


class CreatorReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_sources: list[Literal["personal_history"]] = Field(default_factory=list, max_length=1)

    @field_validator("data_sources")
    @classmethod
    def require_unique_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("data sources must not contain duplicates")
        return value


class CreatorReportResponse(BaseModel):
    id: UUID
    creator_key: UUID
    generated_at: datetime
    as_of: datetime
    goals_revision: int
    goals_version: str
    evidence_version: str
    report_version: str
    baseline_version: str
    processing_status: Literal["completed"] = "completed"
    coverage: Literal["personal_and_niche", "personal_only_partial", "insufficient_evidence"]
    freshness: dict[str, str | None]
    processing_permissions: dict[str, Any]
    limitations: tuple[str, ...]
    evidence: dict[str, Any]
    report: dict[str, Any]


class CreatorReportStateResponse(BaseModel):
    status: Literal["available", "awaiting_profile", "awaiting_import"]
    latest_report: CreatorReportResponse | None
