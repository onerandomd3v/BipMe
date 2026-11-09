"""Synthetic-only contract tests for COD-371 report evidence handoff."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.creator_goals import CreatorGoalsSnapshot
from bipme.intelligence.report_evidence import (
    CreatorReportEvidenceBundle,
    ReportEvidence,
    ReportSource,
)

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def goals() -> CreatorGoalsSnapshot:
    return CreatorGoalsSnapshot(
        creator_key="creator-1",
        recorded_at=NOW - timedelta(days=2),
        niche="software engineering",
        intended_audience="developers",
        priority_outcomes=("conversation",),
    )


def source(pool: str, source_id: str) -> ReportSource:
    return ReportSource(
        source_id=source_id,
        pool=pool,
        observed_at=NOW - timedelta(hours=1),
        source_version="synthetic-v1",
        authorization_basis="synthetic_test_fixture",
        coverage_note="Synthetic, not representative",
    )


def evidence(pool: str, evidence_id: str, source_id: str) -> ReportEvidence:
    return ReportEvidence(
        evidence_id=evidence_id,
        pool=pool,
        kind="observation",
        statement="One observed pattern in this synthetic fixture",
        source_ids=(source_id,),
        post_ids=("synthetic-post-1",),
        metric="replies",
        metric_definition="observed reply count",
        metric_window="age:24h",
        metric_value=3.0,
        limitations=("No causal interpretation",),
    )


def bundle() -> CreatorReportEvidenceBundle:
    return CreatorReportEvidenceBundle(
        creator_key="creator-1",
        as_of=NOW,
        goals=goals(),
        personal_sources=(source("personal", "owned-1"),),
        niche_sources=(),
        personal_evidence=(evidence("personal", "e-1", "owned-1"),),
        niche_evidence=(),
    )


def test_partial_and_full_coverage_and_serialization() -> None:
    partial = bundle()
    assert partial.coverage == "personal_only_partial"
    payload = json.loads(partial.to_json())
    assert payload["version"] == "creator-report-evidence-v1"
    assert payload["goals"]["niche"] == "software engineering"
    assert payload["personal_evidence"][0]["metric_window"] == "age:24h"
    assert partial.to_json() == partial.to_json()
    full = replace(
        partial,
        niche_sources=(source("niche", "niche-1"),),
        niche_evidence=(evidence("niche", "e-2", "niche-1"),),
    )
    assert full.coverage == "personal_and_niche"
    assert replace(full, personal_evidence=()).coverage == "insufficient_evidence"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"creator_key": "creator-2"}, "another creator"),
        ({"as_of": NOW - timedelta(days=3)}, "after the report cutoff"),
        ({"niche_sources": (source("personal", "bad"),)}, "wrong evidence pool"),
        ({"personal_evidence": (evidence("niche", "e-1", "owned-1"),)}, "wrong pool"),
        ({"personal_evidence": (evidence("personal", "e-1", "absent"),)}, "missing or cross-pool"),
        ({"niche_sources": (source("niche", "owned-1"),)}, "duplicate source ID"),
        (
            {"personal_evidence": (evidence("personal", "e-1", "owned-1"),) * 2},
            "duplicate evidence ID",
        ),
        (
            {
                "personal_sources": (
                    replace(source("personal", "owned-1"), observed_at=NOW + timedelta(seconds=1)),
                )
            },
            "after report cutoff",
        ),
    ],
)
def test_rejects_invalid_provenance(change: dict, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        replace(bundle(), **change)


def test_rejects_missing_metric_dimensions_and_nonfinite_numbers() -> None:
    record = evidence("personal", "e-1", "owned-1")
    with pytest.raises(ValueError, match="supplied together"):
        replace(record, metric_window=None)
    with pytest.raises(ValueError, match="finite metric"):
        replace(record, metric_value=float("nan"))
    with pytest.raises(ValueError, match="finite metric"):
        replace(record, metric_value=float("inf"))


def test_rejects_naive_cutoffs_and_future_goals() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(bundle(), as_of=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="after the report cutoff"):
        replace(bundle(), goals=replace(goals(), recorded_at=NOW + timedelta(days=1)))
