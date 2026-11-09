"""Creator profile, processing-permission and deterministic report API.

This router only assembles from creator-scoped canonical records already in the
database. It never imports X content, calls a search provider or invokes synthesis.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.api.analysis import _latest_observation_records
from bipme.api.creator_report_schemas import (
    CreatorProfileResponse,
    CreatorProfileStateResponse,
    CreatorProfileUpdate,
    CreatorReportRequest,
    CreatorReportResponse,
    CreatorReportStateResponse,
    DataPermissionResponse,
    DataPermissionUpdate,
)
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.api.schemas import ErrorResponse
from bipme.intelligence.baselines import BaselineRequest, OutcomeObservation, build_creator_baseline
from bipme.intelligence.content_patterns import PersonalPostProfile
from bipme.intelligence.creator_goals import CREATOR_GOALS_VERSION, CreatorGoalsSnapshot
from bipme.intelligence.creator_report import (
    REPORT_ALGORITHM_VERSION,
    CreatorIntelligenceReport,
    assemble_creator_report,
)
from bipme.intelligence.post_profiles import PROFILE_VERSION, PostProfile
from bipme.intelligence.report_evidence import (
    REPORT_EVIDENCE_VERSION,
    CreatorReportEvidenceBundle,
    ReportEvidence,
    ReportSource,
)
from bipme.persistence.contracts import outcome_observations_from_records
from bipme.persistence.models import (
    CanonicalPost,
    Creator,
    CreatorGoalRevision,
    CreatorProcessingPermission,
    CreatorReportSnapshot,
    OutcomeObservationRecord,
    PostProfileRecord,
)

router = APIRouter(prefix="/api/v1/creators/me", tags=["creator report"])
PERMISSION_POLICY_VERSION = "creator-history-processing-v1"
PERSONAL_HISTORY_SOURCE = "personal_history"
MAX_REPORT_POSTS = 5_000
MAX_REPORT_OBSERVATIONS = 20_000
MAX_REPORT_PROFILE_REVISIONS = 10_000


def _profile_response(record: CreatorGoalRevision) -> CreatorProfileResponse:
    return CreatorProfileResponse(
        creator_key=record.creator_id,
        revision=record.revision,
        version=record.goals_version,
        recorded_at=record.recorded_at,
        niche=record.niche,
        intended_audience=record.intended_audience,
        priority_outcomes=tuple(record.priority_outcomes),  # type: ignore[arg-type]
        preferred_styles=tuple(record.preferred_styles),  # type: ignore[arg-type]
        language=record.language,
    )


def _latest_profile(db: Session, creator_id: UUID) -> CreatorGoalRevision | None:
    return db.scalar(
        select(CreatorGoalRevision)
        .where(CreatorGoalRevision.creator_id == creator_id)
        .order_by(CreatorGoalRevision.revision.desc())
        .limit(1)
    )


def _latest_permission(db: Session, creator_id: UUID) -> CreatorProcessingPermission | None:
    return db.scalar(
        select(CreatorProcessingPermission)
        .where(
            CreatorProcessingPermission.creator_id == creator_id,
            CreatorProcessingPermission.source_kind == PERSONAL_HISTORY_SOURCE,
        )
        .order_by(CreatorProcessingPermission.revision.desc())
        .limit(1)
    )


def _permission_response(
    record: CreatorProcessingPermission | None,
) -> DataPermissionResponse:
    status: Literal["granted", "revoked", "not_granted"] = (
        "not_granted" if record is None else ("granted" if record.allowed else "revoked")
    )
    return DataPermissionResponse(
        personal_history=status,
        personal_history_revision=record.revision if record else None,
        recorded_at=record.recorded_at if record else None,
        x_history_processing="enabled"
        if _x_history_policy_verified_at(datetime.now(UTC)) is not None
        else "blocked",
    )


def _x_history_policy_verified_at(as_of: datetime) -> datetime | None:
    """Require an enabled operator gate with an explicit, cutoff-safe review timestamp."""
    value = os.getenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "false").strip().lower()
    if value not in {"1", "true", "yes", "on"}:
        return None
    raw_time = os.getenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT")
    if not raw_time:
        return None
    try:
        verified_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if verified_at.tzinfo is None or verified_at.utcoffset() is None or verified_at > as_of:
        return None
    return verified_at.astimezone(UTC)


def _require_creator(db: Session, creator_id: UUID, *, lock: bool = False) -> Creator:
    query = select(Creator).where(Creator.id == creator_id)
    if lock:
        query = query.with_for_update()
    creator = db.scalar(query)
    if creator is None:
        raise ApiError(404, "creator_not_found", "The authenticated creator profile was not found.")
    return creator


def _safe_commit(db: Session, code: str, message: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(
            409, "creator_state_conflict", "The creator state changed; retry the request."
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(503, code, message) from None


@router.get(
    "/profile",
    response_model=CreatorProfileStateResponse,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Read the authenticated creator's declared profile",
)
def get_creator_profile(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CreatorProfileStateResponse:
    """Return the latest self-declared goals without inferring audience attributes."""
    try:
        record = _latest_profile(db, creator.creator_id)
    except SQLAlchemyError:
        raise ApiError(
            503, "profile_unavailable", "Creator profile is temporarily unavailable."
        ) from None
    return CreatorProfileStateResponse(
        status="configured" if record else "not_configured",
        profile=_profile_response(record) if record else None,
    )


@router.put(
    "/profile",
    response_model=CreatorProfileResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Create a new immutable revision of the creator's declared profile",
)
def put_creator_profile(
    payload: CreatorProfileUpdate,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    now: Annotated[datetime, Depends(get_current_time)],
) -> CreatorProfileResponse:
    """Persist creator-declared niche, audience, goals and style as a revision."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ApiError(503, "clock_unavailable", "Creator profile is temporarily unavailable.")
    try:
        _require_creator(db, creator.creator_id, lock=True)
        previous = _latest_profile(db, creator.creator_id)
        same_values = previous is not None and (
            previous.niche == payload.niche
            and previous.intended_audience == payload.intended_audience
            and previous.priority_outcomes == payload.priority_outcomes
            and previous.preferred_styles == payload.preferred_styles
            and previous.language == payload.language
        )
        if same_values:
            return _profile_response(cast(CreatorGoalRevision, previous))
        revision = (previous.revision if previous else 0) + 1
        record = CreatorGoalRevision(
            id=uuid4(),
            creator_id=creator.creator_id,
            revision=revision,
            goals_version=CREATOR_GOALS_VERSION,
            recorded_at=now,
            niche=payload.niche,
            intended_audience=payload.intended_audience,
            priority_outcomes=list(payload.priority_outcomes),
            preferred_styles=list(payload.preferred_styles),
            language=payload.language,
        )
        db.add(record)
        _safe_commit(db, "profile_unavailable", "Creator profile is temporarily unavailable.")
        return _profile_response(record)
    except ApiError:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "profile_unavailable", "Creator profile is temporarily unavailable."
        ) from None


@router.get(
    "/data-permissions",
    response_model=DataPermissionResponse,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Read source-specific deterministic-report processing permissions",
)
def get_data_permissions(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> DataPermissionResponse:
    """Report the local history opt-in and fixed unavailable external sources."""
    try:
        record = _latest_permission(db, creator.creator_id)
    except SQLAlchemyError:
        raise ApiError(
            503, "permission_state_unavailable", "Data permissions are temporarily unavailable."
        ) from None
    return _permission_response(record)


@router.put(
    "/data-permissions",
    response_model=DataPermissionResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Grant or revoke local deterministic processing of personal history",
)
def put_data_permissions(
    payload: DataPermissionUpdate,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    now: Annotated[datetime, Depends(get_current_time)],
) -> DataPermissionResponse:
    """Record consent or revocation; revocation erases derived report snapshots."""
    try:
        _require_creator(db, creator.creator_id, lock=True)
        previous = _latest_permission(db, creator.creator_id)
        if previous is not None and previous.allowed == payload.allow_personal_history:
            return _permission_response(previous)
        if previous is None and not payload.allow_personal_history:
            return _permission_response(None)
        revision = (previous.revision if previous else 0) + 1
        permission = CreatorProcessingPermission(
            id=uuid4(),
            creator_id=creator.creator_id,
            revision=revision,
            source_kind=PERSONAL_HISTORY_SOURCE,
            allowed=payload.allow_personal_history,
            policy_version=PERMISSION_POLICY_VERSION,
            recorded_at=now,
        )
        db.add(permission)
        if not payload.allow_personal_history:
            db.execute(
                delete(CreatorReportSnapshot).where(
                    CreatorReportSnapshot.creator_id == creator.creator_id
                )
            )
        _safe_commit(
            db,
            "permission_state_unavailable",
            "Data permissions are temporarily unavailable.",
        )
        return _permission_response(permission)
    except ApiError:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "permission_state_unavailable", "Data permissions are temporarily unavailable."
        ) from None


def _profile_snapshot(record: CreatorGoalRevision) -> CreatorGoalsSnapshot:
    return CreatorGoalsSnapshot(
        creator_key=str(record.creator_id),
        recorded_at=record.recorded_at,
        niche=record.niche,
        intended_audience=record.intended_audience,
        priority_outcomes=tuple(record.priority_outcomes),  # type: ignore[arg-type]
        preferred_styles=tuple(record.preferred_styles),  # type: ignore[arg-type]
        language=record.language,
        version=record.goals_version,
    )


def _latest_post_profiles(
    db: Session, creator_id: UUID, post_ids: set[UUID], as_of: datetime
) -> tuple[PersonalPostProfile, ...]:
    if not post_ids:
        return ()
    rows = list(
        db.scalars(
            select(PostProfileRecord).where(
                PostProfileRecord.creator_id == creator_id,
                PostProfileRecord.post_id.in_(post_ids),
                PostProfileRecord.profile_version == PROFILE_VERSION,
                PostProfileRecord.features_as_of <= as_of,
                PostProfileRecord.input_observed_at <= as_of,
            )
        ).all()
    )
    latest: dict[UUID, PostProfileRecord] = {}
    for row in sorted(
        rows, key=lambda item: (item.features_as_of, item.input_observed_at, str(item.id))
    ):
        latest[row.post_id] = row
    profiles: list[PersonalPostProfile] = []
    for post_id, row in sorted(latest.items(), key=lambda item: str(item[0])):
        raw = row.features
        if not isinstance(raw, dict):
            continue
        embedded_owner = raw.get("creator_key")
        if embedded_owner not in (None, str(creator_id)):
            continue
        features: dict[str, Any] = dict(raw)
        features["version"] = row.profile_version
        features["features_as_of"] = row.features_as_of
        features["input_observed_at"] = row.input_observed_at
        features["creator_key"] = str(creator_id)
        features["creator_context_observed_at"] = row.creator_context_observed_at
        for field in (
            "hashtags",
            "mentions",
            "format_tags",
            "media_types",
            "topic_signals",
            "intent_signals",
        ):
            if isinstance(features.get(field), list):
                features[field] = tuple(features[field])
        try:
            profile = PostProfile(**features)
        except (TypeError, ValueError):
            continue
        profiles.append(PersonalPostProfile(post_id=str(post_id), profile=profile))
    return tuple(profiles)


def _json_snapshot(value: object) -> Any:
    return json.loads(
        json.dumps(
            value,
            default=lambda item: (
                item.isoformat() if isinstance(item, datetime) else _json_unsupported(item)
            ),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _json_unsupported(value: object) -> object:
    raise TypeError(f"unsupported snapshot value: {type(value).__name__}")


def _make_evidence_bundle(
    db: Session,
    *,
    creator_id: UUID,
    goals_record: CreatorGoalRevision,
    permission: CreatorProcessingPermission | None,
    selected_sources: tuple[str, ...],
    as_of: datetime,
) -> tuple[
    CreatorReportEvidenceBundle,
    tuple[OutcomeObservation, ...],
    tuple[PersonalPostProfile, ...],
    dict[str, Any],
]:
    goals = _profile_snapshot(goals_record)
    personal_sources: tuple[ReportSource, ...] = ()
    evidence_records: list[ReportEvidence] = []
    observations: tuple[OutcomeObservation, ...] = ()
    excluded_observations: tuple[OutcomeObservation, ...] = ()
    profiles: tuple[PersonalPostProfile, ...] = ()
    evidence_snapshot: dict[str, Any] = {"sources": [], "observations": [], "profiles": []}
    limitations: list[str] = []
    include_personal = PERSONAL_HISTORY_SOURCE in selected_sources

    if not include_personal:
        limitations.append("Personal history was not selected for this report generation.")
    elif permission is None or not permission.allowed:
        raise ApiError(
            403,
            "source_permission_required",
            "Personal-history processing has not been authorized.",
        )
    elif _x_history_policy_verified_at(as_of) is None:
        limitations.append(
            "X-history processing remains blocked until COD-344 confirms data-use rights and an operator enables the source policy gate."
        )
    else:
        post_filter = (
            CanonicalPost.creator_id == creator_id,
            CanonicalPost.platform == "x",
            CanonicalPost.availability == "available",
            CanonicalPost.published_at <= as_of,
        )
        post_count = (
            db.scalar(select(func.count()).select_from(CanonicalPost).where(*post_filter)) or 0
        )
        if post_count > MAX_REPORT_POSTS:
            limitations.append(
                f"Personal history exceeds the {MAX_REPORT_POSTS}-post deterministic report limit; no sample was selected."
            )
        elif post_count == 0:
            limitations.append("No available creator-owned canonical history is available yet.")
        else:
            posts = list(
                db.scalars(
                    select(CanonicalPost)
                    .where(*post_filter)
                    .order_by(CanonicalPost.published_at, CanonicalPost.id)
                ).all()
            )
            post_ids = {post.id for post in posts}
            outcome_filter = (
                OutcomeObservationRecord.creator_id == creator_id,
                OutcomeObservationRecord.post_id.in_(post_ids),
                OutcomeObservationRecord.observed_at <= as_of,
            )
            observation_count = (
                db.scalar(
                    select(func.count())
                    .select_from(OutcomeObservationRecord)
                    .where(*outcome_filter)
                )
                or 0
            )
            profile_filter = (
                PostProfileRecord.creator_id == creator_id,
                PostProfileRecord.post_id.in_(post_ids),
                PostProfileRecord.profile_version == PROFILE_VERSION,
                PostProfileRecord.features_as_of <= as_of,
                PostProfileRecord.input_observed_at <= as_of,
            )
            profile_count = (
                db.scalar(
                    select(func.count()).select_from(PostProfileRecord).where(*profile_filter)
                )
                or 0
            )
            if observation_count > MAX_REPORT_OBSERVATIONS:
                limitations.append(
                    f"Personal history exceeds the {MAX_REPORT_OBSERVATIONS}-observation report limit; no sample was selected."
                )
            elif profile_count > MAX_REPORT_PROFILE_REVISIONS:
                limitations.append(
                    f"Personal history exceeds the {MAX_REPORT_PROFILE_REVISIONS}-profile report limit; no sample was selected."
                )
            else:
                profiles = _latest_post_profiles(db, creator_id, post_ids, as_of)
                if post_ids:
                    rows = list(
                        db.scalars(select(OutcomeObservationRecord).where(*outcome_filter)).all()
                    )
                    # Select the latest row before converting states. A newer invalid row
                    # is an explicit gap and must not resurrect an older observed value.
                    rows = _latest_observation_records(rows, as_of)
                    weights = {str(post_id): 1.0 for post_id in post_ids}
                    all_observations = outcome_observations_from_records(
                        rows, weights_by_post_id=weights
                    )
                    definitions_by_dimension: dict[tuple[str, str], set[str]] = {}
                    for item in all_observations:
                        definitions_by_dimension.setdefault((item.metric, item.window), set()).add(
                            item.metric_definition
                        )
                    ambiguous_dimensions = {
                        dimension
                        for dimension, definitions in definitions_by_dimension.items()
                        if len(definitions) > 1
                    }
                    for metric, window in sorted(ambiguous_dimensions):
                        limitations.append(
                            f"{metric} ({window}) has multiple metric definitions and was excluded rather than mixed."
                        )
                    observations = tuple(
                        item
                        for item in all_observations
                        if (item.metric, item.window) not in ambiguous_dimensions
                    )
                    excluded_observations = tuple(
                        item
                        for item in all_observations
                        if (item.metric, item.window) in ambiguous_dimensions
                    )

            if (
                observation_count <= MAX_REPORT_OBSERVATIONS
                and profile_count <= MAX_REPORT_PROFILE_REVISIONS
            ):
                source_id = f"canonical-personal-history:{permission.id}"
                personal_sources = (
                    ReportSource(
                        source_id=source_id,
                        pool="personal",
                        observed_at=as_of,
                        source_version="canonical-post-v1:post-profile-v1:outcome-v1",
                        authorization_basis="creator-opt-in+verified-operator-x-history-policy",
                        coverage_note="Creator-owned canonical posts and stored observations only.",
                        authorization_verified=True,
                        authorization_verified_at=max(
                            permission.recorded_at,
                            _x_history_policy_verified_at(as_of) or permission.recorded_at,
                        ),
                    ),
                )
                grouped: dict[tuple[str, str, str], list[OutcomeObservation]] = {}
                for item in observations:
                    if item.value is None:
                        continue
                    grouped.setdefault(
                        (item.metric, item.metric_definition, item.window), []
                    ).append(item)
                for (metric, definition, window), records in sorted(grouped.items()):
                    post_ids_for_metric = tuple(sorted({item.post_id for item in records}))
                    observed_at = max(item.observed_at for item in records)
                    evidence_key = json.dumps(
                        [metric, definition, window, post_ids_for_metric],
                        separators=(",", ":"),
                    )
                    evidence_id = (
                        "personal-metric:" + hashlib.sha256(evidence_key.encode()).hexdigest()[:24]
                    )
                    evidence_records.append(
                        ReportEvidence(
                            evidence_id=evidence_id,
                            pool="personal",
                            kind="observation",
                            statement=(
                                f"Stored {len(records)} exact-definition outcome observations for "
                                f"{metric} ({definition}; {window}) in creator-owned history."
                            ),
                            source_ids=(source_id,),
                            post_ids=post_ids_for_metric,
                            metric=metric,
                            metric_definition=definition,
                            metric_window=window,
                            observed_at=observed_at,
                        )
                    )
                if not observations:
                    limitations.append(
                        "Creator-owned posts exist, but no usable outcome observations are available."
                    )
                evidence_snapshot = {
                    "sources": [asdict(item) for item in personal_sources],
                    "observations": [asdict(item) for item in observations],
                    "missing_observations": [
                        asdict(item) for item in observations if item.value is None
                    ],
                    "excluded_ambiguous_observations": [
                        asdict(item) for item in excluded_observations
                    ],
                    "profiles": [
                        {
                            "post_id": item.post_id,
                            "profile_version": item.profile.version,
                            "features_as_of": item.profile.features_as_of,
                            "input_observed_at": item.profile.input_observed_at,
                        }
                        for item in profiles
                    ],
                }

    bundle = CreatorReportEvidenceBundle(
        creator_key=str(creator_id),
        as_of=as_of,
        goals=goals,
        personal_sources=personal_sources,
        niche_sources=(),
        personal_evidence=tuple(evidence_records),
        niche_evidence=(),
        limitations=tuple(
            [
                "Niche discovery is unavailable and was not requested; this endpoint makes no external request.",
                "Generative synthesis is disabled for deterministic report generation.",
            ]
            + limitations
        ),
    )
    evidence_snapshot["bundle"] = asdict(bundle)
    return bundle, observations, profiles, _json_snapshot(evidence_snapshot)


def _personal_baselines(
    creator_id: UUID,
    as_of: datetime,
    observations: tuple[OutcomeObservation, ...],
) -> tuple[Any, ...]:
    grouped: dict[tuple[str, str, str], list[OutcomeObservation]] = {}
    for item in observations:
        grouped.setdefault((item.metric, item.metric_definition, item.window), []).append(item)
    return tuple(
        build_creator_baseline(
            tuple(items),
            BaselineRequest(
                creator_key=str(creator_id),
                metric=metric,
                metric_definition=definition,
                window=window,
                as_of=as_of,
            ),
        )
        for (metric, definition, window), items in sorted(grouped.items())
    )


def _permission_snapshot(
    permission: CreatorProcessingPermission | None,
    selected_sources: tuple[str, ...],
    as_of: datetime,
    *,
    personal_source_included: bool,
    input_limit_reached: bool,
) -> dict[str, Any]:
    selected = PERSONAL_HISTORY_SOURCE in selected_sources
    included = bool(selected and permission and permission.allowed)
    policy_verified_at = _x_history_policy_verified_at(as_of)
    policy_enabled = policy_verified_at is not None
    return {
        "personal_history": {
            "status": "not_selected"
            if not selected
            else "not_authorized"
            if not included
            else "blocked_by_source_policy"
            if not policy_enabled
            else "bounded_input_limit"
            if input_limit_reached
            else "included"
            if personal_source_included
            else "no_authorized_records",
            "permission_id": str(permission.id) if permission else None,
            "permission_revision": permission.revision if permission else None,
            "creator_consent_status": (
                "not_granted"
                if permission is None
                else "granted"
                if permission.allowed
                else "revoked"
            ),
            "policy_version": permission.policy_version if permission else None,
            "source_policy_enabled": policy_enabled,
            "source_policy_verified_at": policy_verified_at.isoformat()
            if policy_verified_at
            else None,
        },
        "niche_discovery": {"status": "unavailable", "external_requests": 0},
        "external_synthesis": {"status": "disabled", "provider_calls": 0},
    }


def _request_fingerprint(
    goals: CreatorGoalRevision,
    selected_sources: tuple[str, ...],
    permission: CreatorProcessingPermission | None,
) -> str:
    body = {
        "goals_revision_id": str(goals.id),
        "selected_sources": selected_sources,
        "permission_id": str(permission.id) if permission else None,
        "report_version": REPORT_ALGORITHM_VERSION,
        "evidence_version": REPORT_EVIDENCE_VERSION,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _report_response(record: CreatorReportSnapshot) -> CreatorReportResponse:
    report = record.report_snapshot
    return CreatorReportResponse(
        id=record.id,
        creator_key=record.creator_id,
        generated_at=record.generated_at,
        as_of=record.as_of,
        goals_revision=record.goals_revision,
        goals_version=record.goals_version,
        evidence_version=record.evidence_version,
        report_version=record.report_version,
        baseline_version=record.baseline_version,
        coverage=record.report_state,  # type: ignore[arg-type]
        freshness=cast(dict[str, str | None], record.freshness_snapshot),
        processing_permissions=record.permission_snapshot,
        limitations=tuple(report.get("limitations", [])),
        evidence=record.evidence_snapshot,
        report=report,
    )


@router.post(
    "/report",
    response_model=CreatorReportResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Generate or refresh the authenticated creator's deterministic initial report",
    description=(
        "Uses only selected, creator-authorized canonical history already stored by BipMe. "
        "Does not require a draft, call X, spend credits or call a synthesis provider. "
        "A new Idempotency-Key creates a new immutable snapshot; retry with the same key "
        "to retrieve the original result."
    ),
)
def generate_creator_report(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    now: Annotated[datetime, Depends(get_current_time)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    payload: CreatorReportRequest | None = None,
) -> CreatorReportResponse:
    """Persist a deterministic report over a frozen, authorized input snapshot."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ApiError(
            503, "report_generation_unavailable", "Report generation is temporarily unavailable."
        )
    selected_sources = tuple(payload.data_sources) if payload else ()
    try:
        _require_creator(db, creator.creator_id, lock=True)
        goals = _latest_profile(db, creator.creator_id)
        if goals is None:
            raise ApiError(
                409,
                "creator_profile_required",
                "Complete the creator profile before generating a report.",
            )
        permission = _latest_permission(db, creator.creator_id)
        if PERSONAL_HISTORY_SOURCE in selected_sources and (
            permission is None or not permission.allowed
        ):
            raise ApiError(
                403,
                "source_permission_required",
                "Personal-history processing has not been authorized.",
            )
        bundle, outcomes, profiles, evidence_snapshot = _make_evidence_bundle(
            db,
            creator_id=creator.creator_id,
            goals_record=goals,
            permission=permission,
            selected_sources=selected_sources,
            as_of=now,
        )
        fingerprint = _request_fingerprint(goals, selected_sources, permission)
        previous = db.scalar(
            select(CreatorReportSnapshot).where(
                CreatorReportSnapshot.creator_id == creator.creator_id,
                CreatorReportSnapshot.idempotency_key == idempotency_key,
            )
        )
        if previous is not None:
            if previous.request_fingerprint != fingerprint:
                raise ApiError(
                    409,
                    "idempotency_key_reused",
                    "Use a new idempotency key to generate a different report.",
                )
            return _report_response(previous)

        report: CreatorIntelligenceReport = assemble_creator_report(
            bundle,
            personal_baselines=_personal_baselines(creator.creator_id, now, outcomes),
            personal_outcomes=outcomes,
            personal_profiles=profiles,
        )
        source_state = _permission_snapshot(
            permission,
            selected_sources,
            now,
            personal_source_included=bool(bundle.personal_sources),
            input_limit_reached=any(
                "report limit; no sample was selected" in item for item in bundle.limitations
            ),
        )
        record = CreatorReportSnapshot(
            id=uuid4(),
            creator_id=creator.creator_id,
            goals_revision_id=goals.id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            generated_at=now,
            as_of=now,
            goals_revision=goals.revision,
            goals_version=goals.goals_version,
            evidence_version=report.evidence_version,
            report_version=report.version,
            baseline_version=report.baseline_version,
            report_state=report.state,
            report_snapshot=cast(dict[str, Any], json.loads(report.to_json())),
            evidence_snapshot=evidence_snapshot,
            permission_snapshot=source_state,
            freshness_snapshot={
                "personal_history": "historical" if bundle.personal_sources else "unknown",
                "niche_discovery": "unavailable",
            },
        )
        db.add(record)
        _safe_commit(db, "report_persistence_unavailable", "The report could not be saved.")
        return _report_response(record)
    except ApiError:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "report_generation_unavailable", "Report generation is temporarily unavailable."
        ) from None
    except (TypeError, ValueError, OverflowError):
        db.rollback()
        raise ApiError(
            503, "report_generation_unavailable", "Report generation is temporarily unavailable."
        ) from None


def _latest_report(db: Session, creator_id: UUID) -> CreatorReportSnapshot | None:
    return db.scalar(
        select(CreatorReportSnapshot)
        .where(CreatorReportSnapshot.creator_id == creator_id)
        .order_by(CreatorReportSnapshot.generated_at.desc(), CreatorReportSnapshot.id.desc())
        .limit(1)
    )


@router.get(
    "/report/latest",
    response_model=CreatorReportStateResponse,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Read the latest report and its coverage state",
)
def get_latest_creator_report(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CreatorReportStateResponse:
    """Return the latest immutable report, or an explicit onboarding state."""
    try:
        profile = _latest_profile(db, creator.creator_id)
        report = _latest_report(db, creator.creator_id)
    except SQLAlchemyError:
        raise ApiError(
            503, "report_unavailable", "The latest report is temporarily unavailable."
        ) from None
    if report is not None:
        return CreatorReportStateResponse(
            status="available", latest_report=_report_response(report)
        )
    return CreatorReportStateResponse(
        status="awaiting_import" if profile is not None else "awaiting_profile",
        latest_report=None,
    )


@router.get(
    "/reports/{report_id}",
    response_model=CreatorReportResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Read an immutable creator-owned report snapshot",
)
def get_creator_report(
    report_id: UUID,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CreatorReportResponse:
    """Retrieve a report only when it belongs to the authenticated creator."""
    try:
        record = db.scalar(
            select(CreatorReportSnapshot).where(
                CreatorReportSnapshot.id == report_id,
                CreatorReportSnapshot.creator_id == creator.creator_id,
            )
        )
    except SQLAlchemyError:
        raise ApiError(
            503, "report_unavailable", "The report is temporarily unavailable."
        ) from None
    if record is None:
        raise ApiError(404, "report_not_found", "The report was not found.")
    return _report_response(record)


@router.delete(
    "/reports",
    status_code=204,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Delete all report snapshots for the authenticated creator",
)
def delete_creator_reports(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    """Erase report/evidence snapshots without deleting imported source records."""
    try:
        _require_creator(db, creator.creator_id, lock=True)
        db.execute(
            delete(CreatorReportSnapshot).where(
                CreatorReportSnapshot.creator_id == creator.creator_id
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "report_deletion_unavailable", "Report deletion is temporarily unavailable."
        ) from None
    return Response(status_code=204)


@router.delete(
    "/profile",
    status_code=204,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Delete creator profile, processing-permission history and derived reports",
)
def delete_creator_profile(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    """Erase API-owned profile, consent and report snapshots; import data stays importer-owned."""
    try:
        _require_creator(db, creator.creator_id, lock=True)
        db.execute(
            delete(CreatorReportSnapshot).where(
                CreatorReportSnapshot.creator_id == creator.creator_id
            )
        )
        db.execute(
            delete(CreatorGoalRevision).where(CreatorGoalRevision.creator_id == creator.creator_id)
        )
        db.execute(
            delete(CreatorProcessingPermission).where(
                CreatorProcessingPermission.creator_id == creator.creator_id
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503,
            "profile_deletion_unavailable",
            "Creator profile deletion is temporarily unavailable.",
        ) from None
    return Response(status_code=204)
