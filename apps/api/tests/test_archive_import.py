"""Synthetic-only parser and canonical mapping evidence; no external transports."""

import json
import stat
import zipfile
from datetime import UTC, datetime
from uuid import UUID

import pytest

from bipme.integrations.x_archive_inspection import ArchiveInspectionError
from bipme.posts import archive as parser

OWNER = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 11, 11, tzinfo=UTC)


def record(**changes):
    return {
        "id_str": "123",
        "created_at": "Mon Nov 09 10:00:00 +0000 2026",
        "full_text": "synthetic text",
        **changes,
    }


def fixture(path, records=None, *, payload=None, name="data/tweets.json", extra=()):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload if payload is not None else json.dumps(records))
        for entry, content in extra:
            archive.writestr(entry, content)
    return path


def parse(path, **kwargs):
    return parser.parse_synthetic_archive(
        path, creator_id=OWNER, synthetic_fixture=True, now=NOW, **kwargs
    )


@pytest.mark.parametrize("wrapped", [False, True])
def test_mapping_missingness_identity_and_no_fabricated_observations(tmp_path, wrapped):
    payload = json.dumps([{"tweet": record(favorite_count="4", impression_count=200)}])
    if wrapped:
        payload = "window.YTD.tweets.part0 = " + payload + ";"
    path = fixture(
        tmp_path / "fixture.zip",
        payload=payload,
        name="data/tweets.js" if wrapped else "data/tweets.json",
    )
    batch = parse(path)
    assert batch.import_identity == parse(path).import_identity
    assert (
        batch.import_identity
        != parser.parse_synthetic_archive(
            path, creator_id=OTHER, synthetic_fixture=True, now=NOW
        ).import_identity
    )
    post = batch.posts[0]
    assert post.external_post_id == "123"
    assert post.published_at == datetime(2026, 11, 9, 10, tzinfo=UTC)
    assert post.text is None
    assert post.counters[0].value == 4
    assert post.counters[1].value is None
    assert post.counters[1].missing_reason == "not_present"
    assert all(c.observed_at is None and c.unit == "count" for c in post.counters)
    assert batch.unsupported_field_records == 1
    canonical = parser.synthetic_canonical_posts(batch)[0]
    assert canonical.creator_id == OWNER
    assert canonical.source == parser.SOURCE
    assert canonical.source_observed_at is None
    assert canonical.provenance["imported_at"] == NOW.isoformat()
    assert canonical.text is None
    explicit_text = parse(path, include_text=True)
    assert explicit_text.posts[0].text == "synthetic text"
    assert explicit_text.import_identity != batch.import_identity
    assert "synthetic text" not in repr(explicit_text)
    assert "synthetic text" not in repr(explicit_text.posts[0])


@pytest.mark.parametrize(
    "fields,topology",
    [
        ({}, "original"),
        ({"in_reply_to_status_id_str": "12"}, "reply"),
        ({"is_quote_status": True, "quoted_status_id_str": "12"}, "quote"),
    ],
)
def test_topology(tmp_path, fields, topology):
    batch = parse(fixture(tmp_path / "fixture.zip", [record(**fields)]))
    assert batch.posts[0].topology == topology
    assert parser.synthetic_canonical_posts(batch)[0].topology == topology


def test_reposts_excluded_and_counted(tmp_path):
    batch = parse(fixture(tmp_path / "fixture.zip", [record(retweeted_status={"id_str": "45"})]))
    assert batch.posts == ()
    assert batch.record_count == batch.excluded_reposts == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"id_str": 123},
        {"id_str": "secret-invalid-id"},
        {"created_at": "2026-11-09"},
        {"favorite_count": True},
        {"favorite_count": -1},
        {"favorite_count": 1.5},
        {"favorite_count": "nan"},
        {"favorite_count": 10**18},
        {"full_text": 12},
        {"full_text": "x" * 10001},
        {"is_quote_status": True},
        {"is_quote_status": "true"},
        {"is_quote_status": False, "quoted_status_id_str": "45"},
        {"in_reply_to_status_id_str": ""},
        {"in_reply_to_status_id_str": "12", "quoted_status_id_str": "45"},
        {"retweeted_status": {}},
        {"in_reply_to_status_id": "12"},
        {"referenced_tweets": [{"type": "retweeted", "id": "45"}]},
    ],
)
def test_partial_record_failure_is_atomic_and_safe(tmp_path, fields):
    path = fixture(tmp_path / "fixture.zip", [record(id_str="999"), record(**fields)])
    with pytest.raises(parser.SyntheticArchiveError) as exc:
        parse(path)
    assert "secret-invalid-id" not in str(exc.value)
    assert "synthetic text" not in str(exc.value)


def test_duplicate_posts_rejected(tmp_path):
    with pytest.raises(parser.SyntheticArchiveError, match="duplicate"):
        parse(fixture(tmp_path / "fixture.zip", [record(), record()]))


@pytest.mark.parametrize(
    "payload",
    [
        b"not zip",
        b"\xff",
        b"window.YTD.tweets = alert(1);",
        b'[{"id_str":"1","id_str":"2"}]',
        b"[NaN]",
        b"[" * 65 + b"]" * 65,
        b"[1]",
        b"{}",
    ],
)
def test_malformed_payloads(tmp_path, payload):
    with pytest.raises((parser.SyntheticArchiveError, ArchiveInspectionError)):
        parse(fixture(tmp_path / "fixture.zip", payload=payload))


def test_malformed_zip(tmp_path):
    path = tmp_path / "not-zip"
    path.write_bytes(b"not zip")
    with pytest.raises(ArchiveInspectionError):
        parse(path)


@pytest.mark.parametrize(
    "name", ["../data/tweets.json", "/data/tweets.json", "data/posts.json", "C:/data/tweets.json"]
)
def test_bad_paths(tmp_path, name):
    with pytest.raises((parser.SyntheticArchiveError, ArchiveInspectionError)):
        parse(fixture(tmp_path / "fixture.zip", [record()], name=name))


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR])
def test_unsafe_types(tmp_path, mode):
    info = zipfile.ZipInfo("data/tweets.json")
    info.external_attr = (mode | 0o600) << 16
    with zipfile.ZipFile(tmp_path / "fixture.zip", "w") as archive:
        archive.writestr(info, json.dumps([record()]))
    with pytest.raises(ArchiveInspectionError):
        parse(tmp_path / "fixture.zip")


def test_no_unrelated_entry_bodies_opened_or_retained(tmp_path, monkeypatch):
    path = fixture(
        tmp_path / "fixture.zip",
        [record()],
        extra=[
            ("data/direct-messages.js", "SYNTHETIC_SECRET"),
            ("data/account.js", "SYNTHETIC_TOKEN"),
        ],
    )
    original = zipfile.ZipFile.open
    opened = []

    def guarded(self, name, *args, **kwargs):
        opened.append(name.filename)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", guarded)
    batch = parse(path)
    assert opened == ["data/tweets.json"]
    assert "SYNTHETIC_SECRET" not in repr(batch)
    assert "SYNTHETIC_TOKEN" not in repr(batch)
    assert list(tmp_path.iterdir()) == [path]  # no extraction or temporary copies


def test_limits_and_deadline(tmp_path, monkeypatch):
    path = fixture(tmp_path / "fixture.zip", [record()])
    monkeypatch.setattr(parser, "MAX_PAYLOAD_BYTES", 1)
    with pytest.raises(parser.SyntheticArchiveError, match="byte limit"):
        parse(path)
    monkeypatch.setattr(parser, "MAX_PAYLOAD_BYTES", 4 * 1024 * 1024)
    monkeypatch.setattr(parser, "MAX_RECORDS", 0)
    with pytest.raises(parser.SyntheticArchiveError, match="record limit"):
        parse(path)
    monkeypatch.setattr(parser, "MAX_RECORDS", 10_000)
    times = iter([0.0, 6.0])
    monkeypatch.setattr(parser, "monotonic", lambda: next(times))
    with pytest.raises(parser.SyntheticArchiveError, match="deadline"):
        parse(path)


def test_synthetic_context_and_timezone_required(tmp_path):
    path = fixture(tmp_path / "fixture.zip", [record()])
    with pytest.raises(parser.SyntheticArchiveError, match="synthetic"):
        parser.parse_synthetic_archive(path, creator_id=OWNER, synthetic_fixture=False)
    with pytest.raises(parser.SyntheticArchiveError, match="timezone"):
        parser.parse_synthetic_archive(
            path, creator_id=OWNER, synthetic_fixture=True, now=datetime(2026, 11, 11)
        )


def test_no_production_archive_route_is_registered():
    from bipme.api.app import create_app

    assert not any("archive" in path for path in create_app().openapi()["paths"])
