"""Synthetic-only archive mapping; not a production ingestion or authorization API.

No HTTP route, network client, inference, database writes or extraction lives here.
Calling code must never treat a synthetic marker as proof of real processing rights.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import UUID

from bipme.integrations import x_archive_inspection as inspection
from bipme.persistence.models import CanonicalPost

SOURCE = "x_archive_synthetic_v1"
MAPPING_VERSION = "x-archive-candidate-fields-v1"
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 10_000
MAX_SECONDS = 5.0
_ID = re.compile(r"[0-9]{1,30}\Z", re.ASCII)
METRICS = {
    "favorite_count": "like_count",
    "retweet_count": "repost_count",
    "reply_count": "reply_count",
    "quote_count": "quote_count",
    "bookmark_count": "bookmark_count",
}
_FIELDS = frozenset(
    {
        "id_str",
        "created_at",
        "full_text",
        "in_reply_to_status_id_str",
        "quoted_status_id_str",
        "is_quote_status",
        "retweeted_status",
        *METRICS,
    }
)


class SyntheticArchiveError(ValueError):
    """Content-free validation failure suitable for display without its cause."""


@dataclass(frozen=True)
class ArchiveCounter:
    name: str
    value: int | None
    missing_reason: str | None
    # Candidate field semantics are not verified X metric definitions.
    definition: str = "unverified_archive_counter"
    unit: str = "count"
    observed_at: None = None


@dataclass(frozen=True)
class ArchivePost:
    external_post_id: str
    published_at: datetime
    topology: Literal["original", "reply", "quote"]
    reply_to_external_post_id: str | None
    quoted_external_post_id: str | None
    text: str | None = field(repr=False)
    counters: tuple[ArchiveCounter, ...]


@dataclass(frozen=True)
class SyntheticArchiveBatch:
    creator_id: UUID
    import_identity: str
    entry_name: str
    wrapper: str
    record_count: int
    posts: tuple[ArchivePost, ...] = field(repr=False)
    excluded_reposts: int
    unsupported_field_records: int
    parsed_at: datetime
    mapping_version: str = MAPPING_VERSION
    source: str = SOURCE
    limitations: tuple[str, ...] = (
        "Synthetic candidate schema only; real archive format and source rights are unverified.",
        "Counter measurement time is unknown; no outcome observations or windows are created.",
        "Reposts are excluded because canonical topology has no repost value.",
        "Unsupported fields are counted but neither retained nor interpreted.",
        "No media, impressions, profiles, embeddings or inference are produced.",
    )


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise SyntheticArchiveError("record has an invalid identifier")
    return value


def _reference(record: dict[str, object], name: str) -> str | None:
    value = record.get(name)
    return None if value is None else _identifier(value)


def _normalize(record: dict[str, object], include_text: bool) -> ArchivePost | None:
    if any(
        key in record
        for key in (
            "in_reply_to_status_id",
            "quoted_status_id",
            "quoted_status",
            "referenced_tweets",
        )
    ):
        raise SyntheticArchiveError("record uses unsupported topology fields")
    post_id = _identifier(record.get("id_str"))
    raw_time = record.get("created_at")
    if not isinstance(raw_time, str) or len(raw_time) > 40:
        raise SyntheticArchiveError("record has an invalid publication timestamp")
    try:
        published_at = datetime.strptime(raw_time, "%a %b %d %H:%M:%S %z %Y").astimezone(UTC)
    except ValueError:
        raise SyntheticArchiveError("record has an invalid publication timestamp") from None
    text = record.get("full_text")
    if text is not None and (not isinstance(text, str) or len(text) > 10_000):
        raise SyntheticArchiveError("record has invalid post text")
    quote_signal = record.get("is_quote_status")
    if quote_signal is not None and not isinstance(quote_signal, bool):
        raise SyntheticArchiveError("record has an invalid quote flag")
    reply = _reference(record, "in_reply_to_status_id_str")
    quote = _reference(record, "quoted_status_id_str")
    if quote_signal is True and quote is None or quote_signal is False and quote is not None:
        raise SyntheticArchiveError("record has inconsistent quote topology")
    if reply is not None and quote is not None:
        raise SyntheticArchiveError("record topology is ambiguous")
    counters: list[ArchiveCounter] = []
    for source_field, name in METRICS.items():
        value = record.get(source_field)
        if value is not None:
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value, re.ASCII):
                value = int(value)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 10**18:
                raise SyntheticArchiveError("record has an invalid counter")
        counters.append(ArchiveCounter(name, value, "not_present" if value is None else None))
    if "retweeted_status" in record:
        nested = record["retweeted_status"]
        if not isinstance(nested, dict) or reply is not None or quote is not None:
            raise SyntheticArchiveError("record has invalid repost topology")
        _identifier(nested.get("id_str"))
        return None
    return ArchivePost(
        post_id,
        published_at,
        "reply" if reply else "quote" if quote else "original",
        reply,
        quote,
        text if include_text and isinstance(text, str) else None,
        tuple(counters),
    )


def parse_synthetic_archive(
    path: Path,
    *,
    creator_id: UUID,
    synthetic_fixture: Literal[True],
    include_text: bool = False,
    now: datetime | None = None,
) -> SyntheticArchiveBatch:
    """Parse an explicitly designated synthetic fixture, atomically in memory.

    creator_id is test context, not an ownership claim extracted from an archive.
    The marker is an intentional-use guard, not authentication or a rights gate.
    Work is byte/record bounded with a cooperative deadline, not an OS time limit.
    The caller owns the input file; no archive is extracted, copied or deleted.
    """
    if synthetic_fixture is not True or not isinstance(creator_id, UUID):
        raise SyntheticArchiveError("synthetic fixture context is required")
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise SyntheticArchiveError("parse timestamp must be timezone-aware")
    started = monotonic()
    archive = inspection._validate_archive(path)
    try:
        selected = [
            info for info in archive.infolist() if info.filename in inspection.POST_HISTORY_PATHS
        ]
        if len(selected) != 1:
            raise SyntheticArchiveError("exactly one allowlisted post-history entry is required")
        info = selected[0]
        if info.file_size > MAX_PAYLOAD_BYTES:
            raise SyntheticArchiveError("synthetic payload exceeds its byte limit")
        payload = inspection._read_selected_entry(archive, info)
        value, wrapper = inspection._unwrap_json(payload)
        records = inspection._records(value)
    finally:
        archive.close()
    if len(records) > MAX_RECORDS:
        raise SyntheticArchiveError("synthetic payload exceeds its record limit")
    posts: list[ArchivePost] = []
    seen: set[str] = set()
    excluded = unsupported = 0
    for record in records:
        if monotonic() - started > MAX_SECONDS:
            raise SyntheticArchiveError("synthetic parsing deadline exceeded")
        post_id = _identifier(record.get("id_str"))
        if post_id in seen:
            raise SyntheticArchiveError("duplicate post identity in archive")
        seen.add(post_id)
        unsupported += bool(record.keys() - _FIELDS)
        post = _normalize(record, include_text)
        if post is None:
            excluded += 1
        else:
            posts.append(post)
    digest = hashlib.sha256()
    for component in (
        MAPPING_VERSION.encode(),
        creator_id.bytes,
        info.filename.encode(),
        b"text" if include_text else b"metadata",
        payload,
    ):
        digest.update(len(component).to_bytes(8, "big"))
        digest.update(component)
    return SyntheticArchiveBatch(
        creator_id,
        digest.hexdigest(),
        info.filename,
        wrapper,
        len(records),
        tuple(posts),
        excluded,
        unsupported,
        instant.astimezone(UTC),
    )


def synthetic_canonical_posts(batch: SyntheticArchiveBatch) -> tuple[CanonicalPost, ...]:
    """Construct transient test rows only; caller owns transaction and authorization.

    No counter is mapped to OutcomeObservationRecord. parsed_at is import provenance,
    not source_observed_at. Reuse COD-345's canonical identity and topology contract.
    """
    return tuple(
        CanonicalPost(
            creator_id=batch.creator_id,
            platform="x",
            external_post_id=post.external_post_id,
            published_at=post.published_at,
            topology=post.topology,
            availability="available",
            reply_to_external_post_id=post.reply_to_external_post_id,
            quoted_external_post_id=post.quoted_external_post_id,
            ingestion_key=f"x:{post.external_post_id}",
            text=post.text,
            source=batch.source,
            source_endpoint=None,
            source_observed_at=None,
            provenance={
                "source": batch.source,
                "mapping_version": batch.mapping_version,
                "import_id": batch.import_identity,
                "selected_entry": batch.entry_name,
                "content_format": batch.wrapper,
                "imported_at": batch.parsed_at.isoformat(),
                "metric_observation_time": "unknown",
            },
        )
        for post in batch.posts
    )
