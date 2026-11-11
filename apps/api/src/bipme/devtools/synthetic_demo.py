"""Explicitly gated synthetic demo seeder. This module has no X client."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import zipfile
import zlib
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bipme.api.source_policy import SYNTHETIC_DEMO_SOURCE, synthetic_demo_enabled_for
from bipme.intelligence.creator_goals import CREATOR_GOALS_VERSION
from bipme.intelligence.embeddings import EmbeddingIdentity, EmbeddingRole, TextEmbedder
from bipme.intelligence.post_profiles import (
    MediaKind,
    PostProfileInput,
    Topology,
    extract_post_profile,
)
from bipme.persistence.contracts import post_profile_payload
from bipme.persistence.models import (
    APIUsageLedger,
    CanonicalPost,
    Creator,
    CreatorGoalRevision,
    CreatorHistoryImport,
    CreatorPlatformIdentity,
    CreatorProcessingPermission,
    CreatorReportSnapshot,
    CreatorSession,
    DraftAssessment,
    OutcomeObservationRecord,
    PostEmbedding,
    PostProfileRecord,
    ScheduledJob,
    XAccountConnection,
)

LABEL = "Synthetic demonstration data — not live X evidence"
SOURCE = SYNTHETIC_DEMO_SOURCE
VERSION = "bipme-synthetic-demo-v1"
ENTRY = "data/tweets.js"
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_ENTRY = 64 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_RATIO = 200
MAX_ENTRIES = 2000
MAX_SCENARIOS_BYTES = 16 * 1024 * 1024
MAX_SCENARIOS = 20_000
EMBEDDING_REVISION = hashlib.sha1(b"bipme-synthetic-demo-hash-embedding-v1").hexdigest()
EMBEDDING_IDENTITY = EmbeddingIdentity(
    "bipme/synthetic-demo-hash-embedding",
    EMBEDDING_REVISION,
    384,
    "synthetic-demo-token-hash-v1",
)
JS_PREFIX = re.compile(r"window\.YTD\.tweets(?:\.part\d+)?\s*=\s*", re.ASCII)


class SyntheticDemoError(ValueError):
    """A safe seeder refusal; messages never include fixture content."""


class SyntheticDemoEmbedder:
    """Deterministic normalized token-hash vectors, isolated from the live E5 identity."""

    @property
    def identity(self) -> EmbeddingIdentity:
        return EMBEDDING_IDENTITY

    def encode(self, texts: Sequence[str], *, role: EmbeddingRole) -> list[list[float]]:
        if role not in {"query", "passage"}:
            raise ValueError("unsupported embedding role")
        result = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("embedding text must be non-empty")
            vector = [0.0] * self.identity.dimensions
            for token in re.findall(r"[\w#@]+", text.casefold(), flags=re.UNICODE):
                digest = hashlib.sha256(token.encode()).digest()
                slot = int.from_bytes(digest[:4], "big") % len(vector)
                vector[slot] += 1.0 if digest[4] & 1 else -1.0
            norm = math.sqrt(math.fsum(value * value for value in vector)) or 1.0
            if not any(vector):
                vector[0] = 1.0
            result.append([value / norm for value in vector])
        return result


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_environment(creator_id: UUID, confirmed: bool) -> None:
    environment = os.getenv("BIPME_ENVIRONMENT", "").strip().lower()
    if not confirmed:
        raise SyntheticDemoError("pass --synthetic-demo to confirm synthetic-only seeding")
    if environment not in {"development", "demo"}:
        raise SyntheticDemoError("BIPME_ENVIRONMENT must be explicitly development or demo")
    if not _enabled("BIPME_SYNTHETIC_DEMO_ENABLED"):
        raise SyntheticDemoError("BIPME_SYNTHETIC_DEMO_ENABLED=true is required")
    try:
        demo_creator = UUID(os.getenv("BIPME_SYNTHETIC_DEMO_CREATOR_ID", ""))
        app_creator = UUID(os.getenv("BIPME_CREATOR_ID", ""))
    except ValueError:
        raise SyntheticDemoError(
            "configure BIPME_SYNTHETIC_DEMO_CREATOR_ID and BIPME_CREATOR_ID"
        ) from None
    if creator_id != demo_creator or creator_id != app_creator:
        raise SyntheticDemoError(
            "demo target must match the dedicated and authenticated creator IDs"
        )
    database_url = os.getenv("BIPME_DATABASE_URL", "")
    expected_database = os.getenv("BIPME_SYNTHETIC_DEMO_DATABASE_NAME", "")
    if not database_url or not expected_database:
        raise SyntheticDemoError(
            "configure BIPME_DATABASE_URL and BIPME_SYNTHETIC_DEMO_DATABASE_NAME"
        )
    try:
        parsed_url = make_url(database_url)
    except (ValueError, TypeError):
        parsed_url = None
    if parsed_url is None or parsed_url.database != expected_database:
        raise SyntheticDemoError("database URL must target the configured isolated demo database")
    if parsed_url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise SyntheticDemoError("synthetic demo database must be hosted on this machine")


def _read_archive(path: Path) -> tuple[list[dict[str, Any]], str]:
    if path.is_symlink() or not path.is_file():
        raise SyntheticDemoError(
            f"required synthetic archive is missing or not a regular file: {path}"
        )
    if path.stat().st_size > MAX_ARCHIVE:
        raise SyntheticDemoError("archive exceeds compressed-size limit")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise SyntheticDemoError("archive is not a readable ZIP file") from None
    try:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise SyntheticDemoError("archive has too many entries")
        seen: set[str] = set()
        total = 0
        for info in infos:
            name = info.filename
            if (
                not name
                or "\x00" in name
                or "\\" in name
                or name.startswith("/")
                or re.match(r"^[A-Za-z]:", name)
                or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
            ):
                raise SyntheticDemoError("archive contains an unsafe entry path")
            if name in seen:
                raise SyntheticDemoError("archive contains duplicate entry names")
            seen.add(name)
            if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                raise SyntheticDemoError("archive contains a link or encrypted entry")
            total += info.file_size
            if info.file_size < 0 or info.compress_size < 0 or total > MAX_TOTAL:
                raise SyntheticDemoError("archive exceeds expanded-size limits")
            if info.file_size and (
                info.compress_size == 0 or info.file_size > info.compress_size * MAX_RATIO
            ):
                raise SyntheticDemoError("archive exceeds compression-ratio limit")
        selected = [info for info in infos if info.filename == ENTRY]
        if len(selected) != 1:
            raise SyntheticDemoError(f"archive must contain exactly one allowlisted {ENTRY} entry")
        info = selected[0]
        if info.file_size > MAX_ENTRY:
            raise SyntheticDemoError("selected post-history entry exceeds size limit")
        try:
            with archive.open(info) as source:
                data = source.read(MAX_ENTRY + 1)
        except (OSError, RuntimeError, EOFError, zlib.error, zipfile.BadZipFile):
            raise SyntheticDemoError("selected post-history entry could not be read") from None
        if len(data) > MAX_ENTRY or len(data) != info.file_size:
            raise SyntheticDemoError("selected post-history entry exceeded declared size")
        try:
            text = data.decode("utf-8-sig", errors="strict").strip()
            match = JS_PREFIX.match(text)
            if match:
                text = text[match.end() :].strip().removesuffix(";").rstrip()
            value = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise SyntheticDemoError(
                "data/tweets.js must contain inert JSON, not executable JavaScript"
            ) from None
        if isinstance(value, dict):
            value = value.get("tweets")
        if not isinstance(value, list) or not value:
            raise SyntheticDemoError("post-history entry must contain a non-empty array")
        posts = []
        for item in value:
            candidate = item.get("tweet", item) if isinstance(item, dict) else None
            if not isinstance(candidate, dict):
                raise SyntheticDemoError("post-history array contains a non-object")
            posts.append(candidate)
        return posts, hashlib.sha256(data).hexdigest()
    finally:
        archive.close()


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SyntheticDemoError("synthetic post has no publication timestamp")
    try:
        if value.isdigit():
            result = datetime.fromtimestamp(int(value) / 1000, UTC)
        else:
            try:
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                result = parsedate_to_datetime(value)
    except (ValueError, OverflowError, OSError):
        raise SyntheticDemoError("synthetic post has an invalid publication timestamp") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise SyntheticDemoError("publication timestamps must include a timezone")
    return result.astimezone(UTC)


def _post_parts(
    raw: dict[str, Any],
) -> tuple[str, datetime, str, Topology, str | None, str | None, tuple[MediaKind, ...]]:
    raw_id = next(
        (raw.get(key) for key in ("id_str", "id", "tweet_id") if raw.get(key) is not None), None
    )
    if not isinstance(raw_id, (str, int)) or isinstance(raw_id, bool) or not str(raw_id).strip():
        raise SyntheticDemoError("synthetic post has an invalid ID")
    external_id = f"synthetic-demo:{raw_id}"
    time_value = next(
        (
            raw.get(key)
            for key in ("created_at", "created_at_utc", "timestamp_ms")
            if raw.get(key) is not None
        ),
        None,
    )
    published_at = _timestamp(time_value)
    text = raw.get("full_text", raw.get("text"))
    if not isinstance(text, str) or not text.strip() or len(text) > 10_000:
        raise SyntheticDemoError("synthetic post has missing or oversized text")
    if raw.get("retweeted_status") is not None:
        raise SyntheticDemoError("retweet wrapper records are unsupported")
    reply = raw.get("in_reply_to_status_id_str", raw.get("in_reply_to_status_id"))
    quote = raw.get("quoted_status_id_str", raw.get("quoted_status_id"))
    if quote is None and isinstance(raw.get("quoted_status"), dict):
        quote = raw["quoted_status"].get("id_str", raw["quoted_status"].get("id"))
    is_quote = raw.get("is_quote_status") is True or quote is not None
    if reply is not None:
        topology, reply_to, quoted = "reply", f"synthetic-demo:{reply}", None
    elif is_quote:
        if quote is None:
            raise SyntheticDemoError("quote post has no quoted post ID")
        topology, reply_to, quoted = "quote", None, f"synthetic-demo:{quote}"
    else:
        topology, reply_to, quoted = "original", None, None
    entities = raw.get("extended_entities") or raw.get("entities")
    kinds = {"photo": "image", "video": "video", "animated_gif": "gif"}
    media: tuple[MediaKind, ...] = ()
    if isinstance(entities, dict) and isinstance(entities.get("media"), list):
        media = tuple(
            cast(MediaKind, kinds[item["type"]])
            for item in entities["media"]
            if isinstance(item, dict) and item.get("type") in kinds
        )
    return external_id, published_at, text, cast(Topology, topology), reply_to, quoted, media


def _read_scenarios(path: Path) -> tuple[list[dict[str, Any]], str]:
    if path.is_symlink() or not path.is_file():
        raise SyntheticDemoError(f"required monitoring scenarios are missing: {path}")
    if path.stat().st_size > MAX_SCENARIOS_BYTES:
        raise SyntheticDemoError("monitoring scenario file exceeds size limit")
    try:
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise SyntheticDemoError("monitoring scenarios must be valid UTF-8 JSON") from None
    scenarios = value.get("scenarios") if isinstance(value, dict) else value
    if not isinstance(scenarios, list) or len(scenarios) > MAX_SCENARIOS:
        raise SyntheticDemoError("monitoring JSON must contain a bounded scenarios array")
    if any(not isinstance(item, dict) for item in scenarios):
        raise SyntheticDemoError("monitoring scenarios must be objects")
    return scenarios, hashlib.sha256(data).hexdigest()


def _scenario_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise SyntheticDemoError("recorded scenario is missing explicit observed_at")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SyntheticDemoError("scenario observed_at is invalid") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise SyntheticDemoError("scenario observed_at must include a timezone")
    return result.astimezone(UTC)


def _isolation_check(db: Session, creator_id: UUID) -> None:
    creator_ids = set(db.scalars(select(Creator.id)).all())
    if creator_ids - {creator_id}:
        raise SyntheticDemoError("refused: database contains other creator records")
    for model in (
        CreatorPlatformIdentity,
        XAccountConnection,
        CreatorHistoryImport,
        ScheduledJob,
        APIUsageLedger,
    ):
        if db.scalar(select(func.count()).select_from(model)):
            raise SyntheticDemoError(
                "refused: database contains platform, import, job, or provider activity"
            )
    if db.scalar(
        select(func.count())
        .select_from(CanonicalPost)
        .where(
            (CanonicalPost.creator_id != creator_id)
            | (CanonicalPost.source != SOURCE)
            | (CanonicalPost.provenance["synthetic_demo"].as_boolean().is_not(True))
        )
    ):
        raise SyntheticDemoError("refused: database contains non-demo or non-synthetic posts")
    if db.scalar(
        select(func.count())
        .select_from(OutcomeObservationRecord)
        .where(
            (OutcomeObservationRecord.creator_id != creator_id)
            | (OutcomeObservationRecord.provenance["synthetic_demo"].as_boolean().is_not(True))
        )
    ):
        raise SyntheticDemoError("refused: database contains non-demo observations")
    if db.scalar(
        select(func.count())
        .select_from(PostEmbedding)
        .where(
            (PostEmbedding.creator_id != creator_id)
            | (PostEmbedding.model_id != EMBEDDING_IDENTITY.model_id)
            | (PostEmbedding.model_revision != EMBEDDING_IDENTITY.revision)
            | (PostEmbedding.preprocessing_version != EMBEDDING_IDENTITY.preprocessing_version)
        )
    ):
        raise SyntheticDemoError("refused: database contains non-demo embeddings")


def _ensure_goal(db: Session, creator_id: UUID, now: datetime) -> None:
    goal = db.scalar(
        select(CreatorGoalRevision).where(
            CreatorGoalRevision.creator_id == creator_id, CreatorGoalRevision.revision == 1
        )
    )
    if goal is None:
        db.add(
            CreatorGoalRevision(
                creator_id=creator_id,
                revision=1,
                goals_version=CREATOR_GOALS_VERSION,
                recorded_at=now,
                niche="synthetic software development",
                intended_audience="synthetic independent developers",
                priority_outcomes=["conversation", "reach"],
                preferred_styles=["technical_explainer", "tutorial"],
                language="en",
            )
        )
    elif goal.goals_version != CREATOR_GOALS_VERSION:
        raise SyntheticDemoError("refused: demo creator has a conflicting goal revision")


def _seed_posts(
    db: Session,
    creator_id: UUID,
    raws: list[dict[str, Any]],
    archive_hash: str,
    now: datetime,
    embedder: TextEmbedder,
) -> dict[str, CanonicalPost]:
    prepared = [_post_parts(raw) for raw in raws]
    ids = [item[0] for item in prepared]
    if len(ids) != len(set(ids)):
        raise SyntheticDemoError("archive contains duplicate post IDs")
    vectors = embedder.encode([item[2] for item in prepared], role="passage")
    if len(vectors) != len(prepared):
        raise SyntheticDemoError("demo embedder returned an invalid vector count")
    result: dict[str, CanonicalPost] = {}
    for (external_id, published, text, topology, reply_to, quoted, media), vector in zip(
        prepared, vectors, strict=True
    ):
        provenance = {
            "source": SOURCE,
            "synthetic_demo": True,
            "dataset_version": VERSION,
            "archive_sha256": archive_hash,
            "selected_entry": ENTRY,
            "seeded_at": now.isoformat(),
            "label": LABEL,
            "archive_counters": "excluded_without_observation_timestamps",
        }
        post = db.scalar(
            select(CanonicalPost).where(
                CanonicalPost.creator_id == creator_id,
                CanonicalPost.platform == "x",
                CanonicalPost.external_post_id == external_id,
            )
        )
        if post is None:
            post = CanonicalPost(
                creator_id=creator_id,
                platform="x",
                external_post_id=external_id,
                published_at=published,
                availability="available",
                topology=topology,
                reply_to_external_post_id=reply_to,
                quoted_external_post_id=quoted,
                ingestion_key=f"{VERSION}:{external_id}",
                text=text,
                media_present=bool(media),
                source=SOURCE,
                source_endpoint=ENTRY,
                source_observed_at=now,
                provenance=provenance,
            )
            db.add(post)
            db.flush()
        elif (
            post.source != SOURCE
            or post.published_at != published
            or post.text != text
            or post.topology != topology
            or post.reply_to_external_post_id != reply_to
            or post.quoted_external_post_id != quoted
            or post.media_present != bool(media)
            or post.provenance.get("synthetic_demo") is not True
            or post.provenance.get("archive_sha256") != archive_hash
        ):
            raise SyntheticDemoError("existing synthetic post conflicts with supplied archive")
        if reply_to:
            parent = db.scalar(
                select(CanonicalPost).where(
                    CanonicalPost.creator_id == creator_id,
                    CanonicalPost.external_post_id == reply_to,
                )
            )
            if parent:
                post.reply_to_post_id = parent.id
        profile = extract_post_profile(
            PostProfileInput(
                text=text,
                observed_at=published,
                features_as_of=published,
                creator_key=str(creator_id),
                topology=topology,
                thread_role="single",
                media_types=media,
            )
        )
        features = post_profile_payload(profile)
        existing_profile = db.scalar(
            select(PostProfileRecord).where(
                PostProfileRecord.post_id == post.id,
                PostProfileRecord.profile_version == profile.version,
                PostProfileRecord.features_as_of == profile.features_as_of,
            )
        )
        if existing_profile is None:
            db.add(
                PostProfileRecord(
                    post_id=post.id,
                    creator_id=creator_id,
                    profile_version=profile.version,
                    features_as_of=profile.features_as_of,
                    input_observed_at=profile.input_observed_at,
                    features=features,
                )
            )
        elif json.dumps(existing_profile.features, sort_keys=True) != json.dumps(
            features, sort_keys=True
        ):
            raise SyntheticDemoError("existing synthetic post profile conflicts with archive")
        identity = embedder.identity
        existing_embedding = db.scalar(
            select(PostEmbedding).where(
                PostEmbedding.post_id == post.id,
                PostEmbedding.model_id == identity.model_id,
                PostEmbedding.model_revision == identity.revision,
                PostEmbedding.dimensions == identity.dimensions,
                PostEmbedding.preprocessing_version == identity.preprocessing_version,
                PostEmbedding.normalized == identity.normalized,
                PostEmbedding.embedding_version == identity.embedding_version,
            )
        )
        if existing_embedding is None:
            db.add(
                PostEmbedding(
                    post_id=post.id,
                    creator_id=creator_id,
                    model_id=identity.model_id,
                    model_revision=identity.revision,
                    dimensions=identity.dimensions,
                    preprocessing_version=identity.preprocessing_version,
                    normalized=identity.normalized,
                    embedding_version=identity.embedding_version,
                    embedding=vector,
                    generated_at=now,
                )
            )
        elif any(
            not math.isclose(a, b, abs_tol=1e-7)
            for a, b in zip(existing_embedding.embedding, vector, strict=True)
        ):
            raise SyntheticDemoError("existing synthetic embedding conflicts with archive")
        result[external_id.removeprefix("synthetic-demo:")] = post
    db.flush()
    return result


def _seed_scenarios(
    db: Session,
    creator_id: UUID,
    scenarios: list[dict[str, Any]],
    posts: dict[str, CanonicalPost],
    scenario_hash: str,
) -> int:
    recorded = 0
    seen: set[str] = set()
    for index, row in enumerate(scenarios):
        state = row.get("state", row.get("status"))
        if state in {"pending", "skipped"}:
            continue
        if state not in {"observed", "missing", "invalid"}:
            raise SyntheticDemoError(
                "scenario state must be observed, missing, invalid, pending, or skipped"
            )
        raw_id = row.get("post_id", row.get("tweet_id"))
        post = posts.get(str(raw_id).removeprefix("synthetic-demo:"))
        if post is None:
            raise SyntheticDemoError("monitoring scenario refers to a post absent from the archive")
        metric = row.get("metric", row.get("metric_name"))
        definition = row.get("metric_definition", row.get("definition"))
        unit = row.get("metric_unit", row.get("unit", "count"))
        window = row.get("window_key", row.get("window"))
        window_kind = row.get("window_kind", "age_aligned")
        if not all(
            isinstance(item, str) and item.strip() for item in (metric, definition, unit, window)
        ):
            raise SyntheticDemoError(
                "recorded scenario requires metric, definition, unit, and window"
            )
        if window_kind not in {"mature_cumulative", "age_aligned"}:
            raise SyntheticDemoError("scenario uses unsupported window_kind")
        observed_at = _scenario_time(row.get("observed_at"))
        if observed_at < post.published_at:
            raise SyntheticDemoError("scenario observed_at precedes publication")
        raw_value = row.get("value", row.get("metric_value"))
        if state == "observed":
            try:
                value = Decimal(str(raw_value))
            except (InvalidOperation, ValueError):
                raise SyntheticDemoError(
                    "observed scenario requires a numeric metric value"
                ) from None
            if not value.is_finite() or value < 0:
                raise SyntheticDemoError("scenario metric value must be finite and non-negative")
        else:
            if raw_value is not None:
                raise SyntheticDemoError("missing/invalid scenario cannot carry a metric value")
            value = None
        scenario_id = str(row.get("scenario_id", row.get("id", index)))
        key = f"{VERSION}:observation:{scenario_id}"
        if key in seen:
            raise SyntheticDemoError("monitoring scenarios contain duplicate scenario IDs")
        seen.add(key)
        existing = db.scalar(
            select(OutcomeObservationRecord).where(
                OutcomeObservationRecord.creator_id == creator_id,
                OutcomeObservationRecord.idempotency_key == key,
            )
        )
        expected = (
            post.id,
            str(metric),
            str(definition),
            str(unit),
            value,
            state,
            window_kind,
            str(window),
            observed_at,
        )
        if existing is not None:
            actual = (
                existing.post_id,
                existing.metric_name,
                existing.metric_definition,
                existing.metric_unit,
                existing.metric_value,
                existing.state,
                existing.window_kind,
                existing.window_key,
                existing.observed_at,
            )
            if actual != expected or existing.provenance.get("scenario_sha256") != scenario_hash:
                raise SyntheticDemoError(
                    "existing synthetic observation conflicts with scenario fixture"
                )
            recorded += 1
            continue
        db.add(
            OutcomeObservationRecord(
                post_id=post.id,
                creator_id=creator_id,
                published_at=post.published_at,
                metric_name=str(metric),
                metric_definition=str(definition),
                metric_unit=str(unit),
                metric_value=value,
                state=state,
                window_kind=window_kind,
                window_key=str(window),
                observed_at=observed_at,
                idempotency_key=key,
                provenance={
                    "source": SOURCE,
                    "synthetic_demo": True,
                    "dataset_version": VERSION,
                    "scenario_sha256": scenario_hash,
                    "scenario_id": scenario_id,
                    "simulated_observation": True,
                    "label": LABEL,
                },
            )
        )
        recorded += 1
    db.flush()
    return recorded


def seed_synthetic_demo(
    db: Session,
    *,
    archive_path: Path,
    scenarios_path: Path,
    creator_id: UUID,
    confirmed: bool,
    now: datetime | None = None,
    embedder: TextEmbedder | None = None,
) -> dict[str, int | str]:
    _require_environment(creator_id, confirmed)
    if not synthetic_demo_enabled_for(creator_id):
        raise SyntheticDemoError("API synthetic-demo gate is not enabled for this creator")
    raws, archive_hash = _read_archive(archive_path)
    scenarios, scenario_hash = _read_scenarios(scenarios_path)
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise SyntheticDemoError("seed time must be timezone-aware")
    timestamp = timestamp.astimezone(UTC)
    model = embedder or SyntheticDemoEmbedder()
    if model.identity.model_id.startswith("intfloat/"):
        raise SyntheticDemoError("synthetic embedder cannot use the production E5 identity")
    try:
        _isolation_check(db, creator_id)
        if db.get(Creator, creator_id) is None:
            db.add(Creator(id=creator_id))
            db.flush()
        _ensure_goal(db, creator_id, timestamp)
        post_map = _seed_posts(db, creator_id, raws, archive_hash, timestamp, model)
        observation_count = _seed_scenarios(db, creator_id, scenarios, post_map, scenario_hash)
        db.flush()
        return {
            "creator_id": str(creator_id),
            "posts": len(post_map),
            "scenarios": len(scenarios),
            "recorded_observations": observation_count,
            "label": LABEL,
            "embedding_identity": model.identity.index_key,
        }
    except Exception:
        db.rollback()
        raise


def reset_synthetic_demo(db: Session, *, creator_id: UUID, confirmed: bool) -> None:
    _require_environment(creator_id, confirmed)
    _isolation_check(db, creator_id)
    try:
        for model in (
            CreatorReportSnapshot,
            OutcomeObservationRecord,
            PostProfileRecord,
            PostEmbedding,
            CanonicalPost,
            DraftAssessment,
            CreatorSession,
            CreatorGoalRevision,
            CreatorProcessingPermission,
        ):
            db.execute(delete(model).where(model.creator_id == creator_id))
        db.execute(delete(Creator).where(Creator.id == creator_id))
        db.commit()
    except Exception:
        db.rollback()
        raise


def link_synthetic_publication(
    db: Session,
    *,
    creator_id: UUID,
    assessment_id: UUID,
    published_at: datetime,
    confirmed: bool,
    now: datetime | None = None,
) -> UUID:
    """Attach a simulated post through existing persistence, never through the X verifier."""
    _require_environment(creator_id, confirmed)
    if not synthetic_demo_enabled_for(creator_id):
        raise SyntheticDemoError("API synthetic-demo gate is not enabled for this creator")
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise SyntheticDemoError("simulated publication time must include a timezone")
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    published_at = published_at.astimezone(UTC)
    if published_at > timestamp:
        raise SyntheticDemoError("simulated publication time cannot be in the future")
    _isolation_check(db, creator_id)
    assessment = db.scalar(
        select(DraftAssessment).where(
            DraftAssessment.id == assessment_id,
            DraftAssessment.creator_id == creator_id,
        )
    )
    if assessment is None:
        raise SyntheticDemoError("assessment does not belong to the dedicated demo creator")
    if published_at <= assessment.assessed_at:
        raise SyntheticDemoError("simulated publication must occur after the draft assessment")
    if db.scalar(
        select(func.count())
        .select_from(CanonicalPost)
        .where(CanonicalPost.source_assessment_id == assessment_id)
    ):
        raise SyntheticDemoError("assessment already has a linked publication")
    post_id = uuid5(NAMESPACE_URL, f"{VERSION}:publication:{assessment_id}")
    db.add(
        CanonicalPost(
            id=post_id,
            creator_id=creator_id,
            platform="x",
            external_post_id=f"synthetic-demo-publication:{assessment_id}",
            published_at=published_at,
            availability="available",
            topology="original",
            source_assessment_id=assessment_id,
            version_match_state="unknown",
            text=None,
            media_present=None,
            source=SOURCE,
            source_endpoint="synthetic-demo:simulated-publication",
            source_observed_at=timestamp,
            ingestion_key=f"{VERSION}:publication:{assessment_id}",
            provenance={
                "source": SOURCE,
                "synthetic_demo": True,
                "dataset_version": VERSION,
                "simulated_publication": True,
                "label": LABEL,
                "version_match_state": "unknown",
                "observation_state": "pending_until_explicit_scenario",
            },
        )
    )
    db.flush()
    return post_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed isolated BipMe synthetic creator evidence")
    parser.add_argument(
        "--synthetic-demo", action="store_true", help="confirm synthetic-only operation"
    )
    parser.add_argument("--archive", type=Path, default=Path("bipme_synthetic_x_archive.zip"))
    parser.add_argument(
        "--scenarios", type=Path, default=Path("bipme_synthetic_monitoring_scenarios.json")
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--reset", action="store_true", help="remove only dedicated demo creator data"
    )
    operation.add_argument(
        "--link-assessment",
        type=UUID,
        help="create an unverified synthetic publication for a saved draft",
    )
    parser.add_argument("--published-at", help="explicit timezone-aware simulated publication time")
    args = parser.parse_args(argv)
    if not args.reset and args.link_assessment is None:
        missing = [
            str(path)
            for path in (args.archive, args.scenarios)
            if path.is_symlink() or not path.is_file()
        ]
        if missing:
            print(
                "missing required synthetic demo input(s): " + ", ".join(missing), file=sys.stderr
            )
            return 2
    try:
        creator_id = UUID(os.getenv("BIPME_SYNTHETIC_DEMO_CREATOR_ID", ""))
        _require_environment(creator_id, args.synthetic_demo)
        database_url = os.environ["BIPME_DATABASE_URL"]
    except (ValueError, KeyError, SyntheticDemoError) as exc:
        print(f"synthetic demo refused: {exc}", file=sys.stderr)
        return 2
    from sqlalchemy import create_engine

    engine = create_engine(database_url)
    try:
        with Session(engine) as db:
            if args.reset:
                reset_synthetic_demo(db, creator_id=creator_id, confirmed=True)
                print("Synthetic demo creator data removed.")
            elif args.link_assessment is not None:
                if not args.published_at:
                    raise SyntheticDemoError("--published-at is required with --link-assessment")
                try:
                    published_at = datetime.fromisoformat(args.published_at.replace("Z", "+00:00"))
                except ValueError:
                    raise SyntheticDemoError(
                        "--published-at must be an ISO timestamp with timezone"
                    ) from None
                post_id = link_synthetic_publication(
                    db,
                    creator_id=creator_id,
                    assessment_id=args.link_assessment,
                    published_at=published_at,
                    confirmed=True,
                )
                db.commit()
                print(
                    json.dumps(
                        {
                            "synthetic_publication_id": str(post_id),
                            "assessment_id": str(args.link_assessment),
                            "version_match_state": "unknown",
                            "label": LABEL,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                result = seed_synthetic_demo(
                    db,
                    archive_path=args.archive,
                    scenarios_path=args.scenarios,
                    creator_id=creator_id,
                    confirmed=True,
                )
                db.commit()
                print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (SyntheticDemoError, IntegrityError) as exc:
        print(f"synthetic demo refused: {exc}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
