"""Synthetic security and field-count tests for the local X archive inspector."""

from __future__ import annotations

import json
import stat
import zipfile
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).parents[1] / "tools" / "inspect_x_archive.py"
TOOL_SPEC = spec_from_file_location("inspect_x_archive", TOOL_PATH)
assert TOOL_SPEC is not None and TOOL_SPEC.loader is not None
inspector = module_from_spec(TOOL_SPEC)
TOOL_SPEC.loader.exec_module(inspector)


def _archive(path: Path, entries: list[tuple[str, bytes, int | None]]) -> Path:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content, mode in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, content)
    path.write_bytes(buffer.getvalue())
    return path


def _post_entry(posts: list[dict[str, object]], *, wrapped: bool = False) -> bytes:
    data = json.dumps(posts, separators=(",", ":"))
    if wrapped:
        data = f"window.YTD.tweets.part0 = {data};"
    return data.encode("utf-8")


def test_counts_candidate_fields_and_never_emits_post_values(tmp_path: Path, capsys) -> None:
    secret_text = "synthetic-private-post-text-never-print-this"
    records = [
        {
            "tweet": {
                "id_str": "synthetic-id-001",
                "created_at": "Mon Nov 09 10:00:00 +0000 2026",
                "full_text": secret_text,
                "in_reply_to_status_id": "synthetic-reply-id",
                "favorite_count": 8,
                "retweet_count": 2,
                "entities": {
                    "media": [{"type": "photo", "media_url_https": "synthetic-private-url"}]
                },
            }
        },
        {
            "tweet": {
                "id": "synthetic-id-002",
                "timestamp_ms": "1794218400000",
                "is_quote_status": True,
                "public_metrics": {"impression_count": 50, "reply_count": 1},
                "extended_entities": {"media": [{"type": "video"}]},
            }
        },
        {"tweet": {"retweeted_status": {"id": "synthetic-nested-id"}}},
    ]
    archive = _archive(
        tmp_path / "synthetic.zip",
        [("data/tweets.js", _post_entry(records, wrapped=True), None)],
    )

    summary = inspector.inspect_archive(archive)
    exit_code = inspector.main([str(archive)])
    printed = capsys.readouterr()
    rendered = summary | {"cli_output": printed.out, "stderr": printed.err}

    assert exit_code == 0
    assert summary["post_record_count"] == 3
    assert summary["availability_counts"]["post_id"] == 2
    assert summary["availability_counts"]["publication_timestamp"] == 2
    assert summary["availability_counts"]["metric:likes"] == 1
    assert summary["availability_counts"]["metric:impressions"] == 1
    assert summary["topology_record_counts"] == {"reply": 1, "repost": 1, "quote": 1}
    assert summary["media_type_record_counts"]["photo"] == 1
    assert summary["media_type_record_counts"]["video"] == 1
    assert summary["provenance"]["content_format"] == "javascript_assignment_json"
    assert secret_text not in json.dumps(rendered)
    assert "synthetic-id-001" not in json.dumps(rendered)
    assert "synthetic-private-url" not in json.dumps(rendered)


def test_ignores_unallowlisted_sensitive_entries(tmp_path: Path) -> None:
    post_records = [{"tweet": {"id_str": "synthetic-post", "favorite_count": 1}}]
    archive = _archive(
        tmp_path / "synthetic-with-unrelated-data.zip",
        [
            ("data/tweets.json", _post_entry(post_records), None),
            ("data/direct-messages.js", b"private synthetic DM content", None),
            ("data/account.js", b"synthetic credentials", None),
        ],
    )

    result = inspector.inspect_archive(archive)

    assert result["post_record_count"] == 1
    assert result["provenance"]["selected_entry"] == "data/tweets.json"
    assert "DM" not in json.dumps(result)
    assert "credentials" not in json.dumps(result)


@pytest.mark.parametrize(
    "entry_name",
    ["../data/tweets.js", "/data/tweets.js", "C:/data/tweets.js", r"data\tweets.js"],
)
def test_rejects_traversal_or_non_posix_entry_paths(tmp_path: Path, entry_name: str) -> None:
    archive = _archive(
        tmp_path / "unsafe.zip",
        [(entry_name, _post_entry([{"id": "synthetic"}]), None)],
    )

    with pytest.raises(inspector.ArchiveInspectionError, match="unsafe entry path"):
        inspector.inspect_archive(archive)


def test_rejects_symlink_entries_even_outside_the_allowlist(tmp_path: Path) -> None:
    archive = _archive(
        tmp_path / "symlink.zip",
        [
            ("data/tweets.json", _post_entry([{"id": "synthetic"}]), None),
            ("data/unrelated-link", b"target", stat.S_IFLNK | 0o777),
        ],
    )

    with pytest.raises(inspector.ArchiveInspectionError, match="symbolic link"):
        inspector.inspect_archive(archive)


def test_rejects_high_compression_ratio_and_excess_entry_count(tmp_path: Path, monkeypatch) -> None:
    bomb = _archive(
        tmp_path / "ratio.zip",
        [
            ("data/tweets.json", _post_entry([{"id": "synthetic"}]), None),
            ("unrelated.bin", b"0" * 100_000, None),
        ],
    )
    with pytest.raises(inspector.ArchiveInspectionError, match="compression-ratio"):
        inspector.inspect_archive(bomb)

    small = _archive(
        tmp_path / "many.zip",
        [
            ("data/tweets.json", _post_entry([{"id": "synthetic"}]), None),
            ("ignored/one", b"1", None),
        ],
    )
    monkeypatch.setattr(inspector, "MAX_ENTRIES", 1)
    with pytest.raises(inspector.ArchiveInspectionError, match="entry-count"):
        inspector.inspect_archive(small)


def test_rejects_javascript_execution_syntax_and_unknown_archive_layouts(tmp_path: Path) -> None:
    executable = _archive(
        tmp_path / "executable.zip",
        [("data/tweets.js", b"window.YTD.tweets = process.exit(1);", None)],
    )
    with pytest.raises(inspector.ArchiveInspectionError, match="inert JSON"):
        inspector.inspect_archive(executable)

    unknown = _archive(
        tmp_path / "unknown-layout.zip",
        [("data/posts.json", _post_entry([{"id": "synthetic"}]), None)],
    )
    with pytest.raises(inspector.ArchiveInspectionError, match="exactly one allowlisted"):
        inspector.inspect_archive(unknown)


def test_rejects_duplicate_allowlisted_entries_and_requires_explicit_input(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = _archive(
            tmp_path / "duplicate.zip",
            [
                ("data/tweets.json", _post_entry([{"id": "synthetic"}]), None),
                ("data/tweets.json", _post_entry([{"id": "synthetic-other"}]), None),
            ],
        )
    with pytest.raises(inspector.ArchiveInspectionError, match="duplicate entry names"):
        inspector.inspect_archive(duplicate)

    with pytest.raises(SystemExit) as missing_argument:
        inspector.main([])
    assert missing_argument.value.code == 2
