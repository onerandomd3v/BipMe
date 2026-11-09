"""Versioned, source-separated evidence contract for creator intelligence reports.

Pure data contract only: callers must establish ownership/permission before passing
records. No X access, LLM, storage, inferred demographics or performance prediction.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from bipme.intelligence.creator_goals import CreatorGoalsSnapshot

REPORT_EVIDENCE_VERSION = "creator-report-evidence-v1"
EvidencePool = Literal["personal", "niche"]
EvidenceKind = Literal["observation", "inference", "hypothesis", "unknown"]
ReportCoverage = Literal["personal_and_niche", "personal_only_partial", "insufficient_evidence"]


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True)
class ReportSource:
    """Traceable, authorized source metadata; never includes raw provider content."""

    source_id: str
    pool: EvidencePool
    observed_at: datetime
    source_version: str
    authorization_basis: str
    coverage_note: str

    def __post_init__(self) -> None:
        for name in ("source_id", "source_version", "authorization_basis", "coverage_note"):
            _nonempty(getattr(self, name), name)
        _aware(self.observed_at, "observed_at")
        if self.pool not in ("personal", "niche"):
            raise ValueError("unknown evidence pool")


@dataclass(frozen=True)
class ReportEvidence:
    """One bounded claim supported by source IDs and optional exact-window metric.

    An evidence claim is descriptive. Its numeric value is never interpreted as
    a probability, causal lift or a metric from another source population.
    """

    evidence_id: str
    pool: EvidencePool
    kind: EvidenceKind
    statement: str
    source_ids: tuple[str, ...]
    post_ids: tuple[str, ...] = ()
    metric: str | None = None
    metric_definition: str | None = None
    metric_window: str | None = None
    metric_value: float | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.evidence_id, "evidence_id")
        _nonempty(self.statement, "statement")
        if self.pool not in ("personal", "niche"):
            raise ValueError("unknown evidence pool")
        if self.kind not in ("observation", "inference", "hypothesis", "unknown"):
            raise ValueError("unknown evidence kind")
        if not self.source_ids or len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be nonempty and unique")
        if len(set(self.post_ids)) != len(self.post_ids):
            raise ValueError("post_ids must be unique")
        for item in (*self.source_ids, *self.post_ids, *self.limitations):
            _nonempty(item, "evidence reference or limitation")
        fields = (self.metric, self.metric_definition, self.metric_window)
        if any(field is not None for field in fields) and not all(
            field is not None for field in fields
        ):
            raise ValueError("metric, definition and window must be supplied together")
        for field in fields:
            if field is not None:
                _nonempty(field, "metric field")
        if self.metric_value is not None:
            if self.metric is None or not math.isfinite(self.metric_value):
                raise ValueError("metric_value requires a complete finite metric")


@dataclass(frozen=True)
class CreatorReportEvidenceBundle:
    """Frozen evidence to be consumed by deterministic reports or later synthesis.

    Personal and niche observations are deliberately separate collections.
    The bundle is not a validated X data-ingestion or permission system.
    """

    creator_key: str
    as_of: datetime
    goals: CreatorGoalsSnapshot
    personal_sources: tuple[ReportSource, ...]
    niche_sources: tuple[ReportSource, ...]
    personal_evidence: tuple[ReportEvidence, ...]
    niche_evidence: tuple[ReportEvidence, ...]
    limitations: tuple[str, ...] = ()
    version: str = REPORT_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        _nonempty(self.creator_key, "creator_key")
        _aware(self.as_of, "as_of")
        if self.version != REPORT_EVIDENCE_VERSION:
            raise ValueError("unsupported evidence bundle version")
        self.goals.require_available_by(self.as_of, self.creator_key)
        source_ids: dict[str, str] = {}
        for pool, sources in (
            ("personal", self.personal_sources),
            ("niche", self.niche_sources),
        ):
            for source in sources:
                if source.pool != pool:
                    raise ValueError("source placed in the wrong evidence pool")
                if source.observed_at > self.as_of:
                    raise ValueError("source was observed after report cutoff")
                if source.source_id in source_ids:
                    raise ValueError("duplicate source ID across evidence pools")
                source_ids[source.source_id] = pool
        evidence_ids: set[str] = set()
        for pool, records in (
            ("personal", self.personal_evidence),
            ("niche", self.niche_evidence),
        ):
            for evidence in records:
                if evidence.pool != pool:
                    raise ValueError("evidence placed in the wrong pool")
                if evidence.evidence_id in evidence_ids:
                    raise ValueError("duplicate evidence ID")
                evidence_ids.add(evidence.evidence_id)
                if any(source_ids.get(source_id) != pool for source_id in evidence.source_ids):
                    raise ValueError("evidence references missing or cross-pool source")
        for limitation in self.limitations:
            _nonempty(limitation, "limitation")

    @property
    def coverage(self) -> ReportCoverage:
        if not self.personal_evidence:
            return "insufficient_evidence"
        if not self.niche_evidence:
            return "personal_only_partial"
        return "personal_and_niche"

    def to_json(self) -> str:
        """Deterministic, provenance-preserving JSON, without raw post text."""
        return json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: (
                value.isoformat() if isinstance(value, datetime) else _unsupported(value)
            ),
            allow_nan=False,
        )


def _unsupported(value: object) -> object:
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
