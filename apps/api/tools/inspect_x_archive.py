"""Local-only, metadata-only inspection of selected X post-history ZIP entries.

This is a research aid, not an importer or validator of any production export schema.
It never executes JavaScript and never emits IDs, timestamps, post text, URLs or values.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
import zipfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Any

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 2_000
MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_SELECTED_ENTRY_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
POST_HISTORY_PATHS = frozenset({"data/tweets.js", "data/tweets.json"})
JS_ASSIGNMENT = re.compile(r"window\.YTD\.tweets(?:\.part\d+)?\s*=\s*", re.ASCII)

ID_FIELDS = ("id", "id_str", "tweet_id")
TIME_FIELDS = ("created_at", "timestamp_ms", "created_at_utc")
METRIC_FIELDS = {
    "replies": ("reply_count",),
    "reposts": ("retweet_count", "repost_count"),
    "quotes": ("quote_count",),
    "likes": ("favorite_count", "like_count"),
    "bookmarks": ("bookmark_count",),
    "impressions": ("impression_count",),
}


class ArchiveInspectionError(ValueError):
    """A safe-to-display archive inspection failure without archive content."""


def _safe_member_name(name: str) -> None:
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
        or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
    ):
        raise ArchiveInspectionError("archive contains an unsafe entry path")


def _validate_archive(path: Path) -> zipfile.ZipFile:
    if path.is_symlink() or not path.is_file():
        raise ArchiveInspectionError("input must be an explicitly supplied regular file")
    try:
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ArchiveInspectionError("archive exceeds the compressed-size limit")
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise ArchiveInspectionError("input is not a readable ZIP archive") from None

    try:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ArchiveInspectionError("archive exceeds the entry-count limit")
        total_uncompressed = 0
        seen_names: set[str] = set()
        for info in infos:
            _safe_member_name(info.filename)
            if info.filename in seen_names:
                raise ArchiveInspectionError("archive contains duplicate entry names")
            seen_names.add(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ArchiveInspectionError("archive contains a symbolic link")
            if info.flag_bits & 0x1:
                raise ArchiveInspectionError("encrypted archive entries are not supported")
            if info.file_size < 0 or info.compress_size < 0:
                raise ArchiveInspectionError("archive contains invalid entry sizes")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise ArchiveInspectionError("archive exceeds the total expanded-size limit")
            if info.file_size > 0 and (
                info.compress_size == 0
                or info.file_size > info.compress_size * MAX_COMPRESSION_RATIO
            ):
                raise ArchiveInspectionError("archive exceeds the compression-ratio limit")
    except BaseException:
        archive.close()
        raise
    return archive


def _read_selected_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > MAX_SELECTED_ENTRY_BYTES:
        raise ArchiveInspectionError("post-history entry exceeds the selected-entry limit")
    try:
        with archive.open(info, "r") as source:
            data = source.read(MAX_SELECTED_ENTRY_BYTES + 1)
    except (OSError, RuntimeError, EOFError, zlib.error, zipfile.BadZipFile, NotImplementedError):
        raise ArchiveInspectionError("post-history entry could not be read safely") from None
    if len(data) > MAX_SELECTED_ENTRY_BYTES or len(data) != info.file_size:
        raise ArchiveInspectionError("post-history entry exceeded its declared size")
    return data


def _unwrap_json(data: bytes) -> tuple[Any, str]:
    try:
        text = data.decode("utf-8-sig", errors="strict").strip()
    except UnicodeDecodeError:
        raise ArchiveInspectionError("post-history entry is not UTF-8 JSON data") from None
    match = JS_ASSIGNMENT.match(text)
    wrapper = "javascript_assignment_json" if match else "json"
    if match:
        text = text[match.end() :].strip()
        if text.endswith(";"):
            text = text[:-1].rstrip()
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        raise ArchiveInspectionError(
            "post-history entry is not a recognized inert JSON structure"
        ) from None
    return value, wrapper


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("tweets")
    if not isinstance(value, list):
        raise ArchiveInspectionError("post-history JSON must contain an array of post records")
    posts: list[dict[str, Any]] = []
    for item in value:
        candidate = item.get("tweet") if isinstance(item, dict) and "tweet" in item else item
        if not isinstance(candidate, dict):
            raise ArchiveInspectionError("post-history array contains a non-object record")
        posts.append(candidate)
    return posts


def _present(record: dict[str, Any], names: tuple[str, ...]) -> bool:
    return any(name in record and record[name] is not None for name in names)


def _topology(record: dict[str, Any]) -> str | None:
    if _present(record, ("in_reply_to_status_id", "in_reply_to_status_id_str")):
        return "reply"
    if _present(record, ("retweeted_status",)):
        return "repost"
    if record.get("is_quote_status") is True or _present(
        record, ("quoted_status_id", "quoted_status_id_str", "quoted_status")
    ):
        return "quote"
    return None


def _media_types(record: dict[str, Any]) -> list[str]:
    entities = record.get("extended_entities") or record.get("entities")
    if not isinstance(entities, dict) or not isinstance(entities.get("media"), list):
        return []
    types: list[str] = []
    for item in entities["media"]:
        if isinstance(item, dict):
            media_type = item.get("type")
            if isinstance(media_type, str) and media_type in {"photo", "video", "animated_gif"}:
                types.append(media_type)
    return types


def summarize_posts(
    posts: list[dict[str, Any]], *, entry_name: str, wrapper: str, byte_count: int, crc: int
) -> dict[str, Any]:
    field_counts: Counter[str] = Counter()
    topology_counts: Counter[str] = Counter()
    media_counts: Counter[str] = Counter()
    total = len(posts)
    for record in posts:
        if _present(record, ID_FIELDS):
            field_counts["post_id"] += 1
        if _present(record, TIME_FIELDS):
            field_counts["publication_timestamp"] += 1
        if _present(record, ("full_text", "text")):
            field_counts["post_text"] += 1
        topology = _topology(record)
        if topology:
            topology_counts[topology] += 1
        metrics = record.get("public_metrics")
        metric_source = metrics if isinstance(metrics, dict) else record
        for label, candidates in METRIC_FIELDS.items():
            if _present(metric_source, candidates):
                field_counts[f"metric:{label}"] += 1
        types = _media_types(record)
        if types:
            field_counts["media_metadata"] += 1
            media_counts.update(types)
        elif _present(record, ("media", "extended_entities", "attachments")):
            field_counts["media_metadata"] += 1

    tracked = (
        "post_id",
        "publication_timestamp",
        "post_text",
        "metric:replies",
        "metric:reposts",
        "metric:quotes",
        "metric:likes",
        "metric:bookmarks",
        "metric:impressions",
        "media_metadata",
    )
    available = {name: field_counts[name] for name in tracked}
    missing = {name: total - field_counts[name] for name in tracked}
    return {
        "result": "synthetic_or_local_inspection_summary",
        "post_record_count": total,
        "availability_counts": available,
        "missing_counts": missing,
        "topology_record_counts": {
            name: topology_counts[name] for name in ("reply", "repost", "quote")
        },
        "media_type_record_counts": {
            name: media_counts[name] for name in ("photo", "video", "animated_gif")
        },
        "provenance": {
            "selected_entry": entry_name,
            "container": "zip",
            "content_format": wrapper,
            "selected_entry_bytes": byte_count,
            "selected_entry_crc32": f"{crc:08x}",
            "field_mapping_version": "x-archive-candidate-fields-v1",
            "metric_observation_time": "not_present_inferred_from_archive",
        },
        "limitations": [
            "Field names are candidate mappings; verify them against a current owner-provided export.",
            "Counts indicate field presence only; metric values and post text are never emitted.",
            "A single archive snapshot cannot establish early-age metric trajectories.",
        ],
    }


def inspect_archive(path: Path) -> dict[str, Any]:
    """Inspect only exact allowlisted post-history paths in a local ZIP archive."""
    archive = _validate_archive(path)
    try:
        selected = [info for info in archive.infolist() if info.filename in POST_HISTORY_PATHS]
        if len(selected) != 1:
            raise ArchiveInspectionError(
                "archive must contain exactly one allowlisted post-history entry"
            )
        info = selected[0]
        data = _read_selected_entry(archive, info)
        value, wrapper = _unwrap_json(data)
        posts = _records(value)
        return summarize_posts(
            posts,
            entry_name=info.filename,
            wrapper=wrapper,
            byte_count=len(data),
            crc=info.CRC,
        )
    finally:
        archive.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Locally inspect field availability in one explicitly provided X archive ZIP. "
            "No network access; raw content is not printed or saved."
        )
    )
    parser.add_argument("archive", type=Path, help="explicit local path to an X archive ZIP")
    args = parser.parse_args(argv)
    try:
        result = inspect_archive(args.archive)
    except ArchiveInspectionError as exc:
        print(f"inspection refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
