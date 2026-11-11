"""Safety and fixture parsing tests for the opt-in synthetic demo seeder."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from uuid import UUID

import pytest

from bipme.api.source_policy import synthetic_demo_enabled_for
from bipme.devtools import synthetic_demo
from bipme.devtools.synthetic_demo import (
    EMBEDDING_IDENTITY,
    SyntheticDemoEmbedder,
    SyntheticDemoError,
    _read_archive,
    _read_scenarios,
    _require_environment,
)
from bipme.intelligence.embeddings import EmbeddingIdentity

CREATOR_ID = UUID("8aee3494-76a3-4a12-9c1d-56671a36c63a")


def _enable_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIPME_ENVIRONMENT", "development")
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_DATABASE_NAME", "bipme_synthetic_demo")
    monkeypatch.setenv(
        "BIPME_DATABASE_URL", "postgresql+psycopg://demo:demo@localhost/bipme_synthetic_demo"
    )
    monkeypatch.setenv("BIPME_EMBEDDING_PROVIDER", "synthetic_demo")


def _archive(path: Path, content: str) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data/tweets.js", content)


def test_seeder_refuses_without_explicit_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_demo(monkeypatch)

    with pytest.raises(SyntheticDemoError, match="--synthetic-demo"):
        _require_environment(CREATOR_ID, confirmed=False)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("BIPME_ENVIRONMENT", "production", "development or demo"),
        ("BIPME_SYNTHETIC_DEMO_ENABLED", "false", "is required"),
        ("BIPME_CREATOR_ID", "11111111-1111-4111-8111-111111111111", "must match"),
        ("BIPME_SYNTHETIC_DEMO_DATABASE_NAME", "bipme", "isolated demo database"),
    ],
)
def test_seeder_refuses_incorrect_environment(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, message: str
) -> None:
    _enable_demo(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(SyntheticDemoError, match=message):
        _require_environment(CREATOR_ID, confirmed=True)


def test_synthetic_policy_is_creator_bound_and_requires_explicit_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_demo(monkeypatch)
    assert synthetic_demo_enabled_for(CREATOR_ID)
    assert not synthetic_demo_enabled_for(UUID("11111111-1111-4111-8111-111111111111"))
    monkeypatch.delenv("BIPME_ENVIRONMENT")
    assert not synthetic_demo_enabled_for(CREATOR_ID)


def test_seeder_refuses_non_local_database_even_with_matching_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_demo(monkeypatch)
    monkeypatch.setenv(
        "BIPME_DATABASE_URL", "postgresql+psycopg://demo:demo@example.com/bipme_synthetic_demo"
    )

    with pytest.raises(SyntheticDemoError, match="hosted on this machine"):
        _require_environment(CREATOR_ID, confirmed=True)


def test_archive_parser_reads_allowlisted_json_without_running_javascript(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.zip"
    body = (
        "window.YTD.tweets.part0 = "
        '[{"tweet":{"id_str":"post-1","created_at":"2026-01-01T00:00:00Z",'
        '"full_text":"Synthetic post"}}];'
    )
    _archive(path, body)

    posts, digest = _read_archive(path)

    assert posts[0]["id_str"] == "post-1"
    assert len(digest) == 64


def test_archive_parser_rejects_executable_javascript_and_non_allowlisted_paths(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "executable.zip"
    _archive(executable, "window.YTD.tweets = evil();")
    with pytest.raises(SyntheticDemoError, match="inert JSON"):
        _read_archive(executable)

    unrelated = tmp_path / "unrelated.zip"
    with zipfile.ZipFile(unrelated, "w") as archive:
        archive.writestr("data/direct-messages.js", "[]")
    with pytest.raises(SyntheticDemoError, match="allowlisted"):
        _read_archive(unrelated)


def test_scenario_parser_is_explicit_bounded_json(tmp_path: Path) -> None:
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps({"scenarios": [{"state": "pending"}]}), encoding="utf-8")
    scenarios, digest = _read_scenarios(path)
    assert scenarios == [{"state": "pending"}]
    assert len(digest) == 64


def test_cli_reports_missing_required_fixture_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "bipme_synthetic_x_archive.zip"
    scenarios = tmp_path / "bipme_synthetic_monitoring_scenarios.json"
    assert synthetic_demo.main(["--archive", str(archive), "--scenarios", str(scenarios)]) == 2
    assert "missing required synthetic demo input(s)" in capsys.readouterr().err


def test_demo_embedder_environment_selection_never_uses_production_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_demo(monkeypatch)

    from bipme.intelligence import embeddings
    from bipme.intelligence.embeddings import embedder_from_environment

    embedder = embedder_from_environment()
    assert isinstance(embedder, SyntheticDemoEmbedder)
    assert embedder.identity != EmbeddingIdentity(
        "intfloat/multilingual-e5-small",
        "fd1525a9fd15316a2d503bf26ab031a61d056e98",
        384,
        "e5-prefix-strip-v1",
    )
    monkeypatch.setattr(
        embeddings,
        "_load_model",
        lambda *_args: pytest.fail("synthetic embeddings must not load a model"),
    )
    assert embedder.encode(["synthetic creator evidence"], role="passage")[0]


def test_synthetic_embeddings_are_stable_normalized_and_isolated() -> None:
    embedder = SyntheticDemoEmbedder()
    first = embedder.encode(["synthetic creator evidence"], role="passage")[0]
    second = embedder.encode(["synthetic creator evidence"], role="query")[0]
    assert first == second
    assert EMBEDDING_IDENTITY.model_id == "bipme/synthetic-demo-hash-embedding"
    assert len(first) == 384
    assert sum(value * value for value in first) == pytest.approx(1.0)
