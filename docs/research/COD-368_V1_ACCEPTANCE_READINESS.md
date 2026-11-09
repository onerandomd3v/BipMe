# COD-368 — BipMe V1 acceptance readiness

**Checked against `main` at `d9bd57b` on 9 November 2026.** This report prepares verification; it is not a full V1 acceptance sign-off. All code evidence listed below is from synthetic fixtures or mocked services unless explicitly stated otherwise. No real X account, archive, provider request, or post-observation window was used.

**Local API verification on this branch:** Ruff lint passed; Ruff format check passed (64 files); mypy passed (39 source files); pytest passed (**328 passed, 15 skipped**). The focused unknown-version regression passed (**1 passed**). The skips are one opt-in model download and 14 PostgreSQL cases requiring `BIPME_TEST_DATABASE_URL`; PostgreSQL migration/integration behavior is therefore not locally verified in this run. `git diff --check` passed. GitHub PR CI subsequently passed all three jobs (`api-checks`, including PostgreSQL-backed tests; `web-checks`; `workspace-checks`) on PR #39.

## Acceptance coverage

| Acceptance area | Current implementation and test evidence | Readiness |
| --- | --- | --- |
| Secure creator authentication | Private session, CSRF, expiry/revocation, X account allowlist and token redaction contracts. `test_auth.py` covers session lifecycle, CSRF, rejected accounts and secret-free responses; `test_analysis_api.py` covers fail-closed behavior when production auth is not configured. | Synthetic/API verified. No real creator login or X OAuth handshake. |
| Creator niche, audience and goals onboarding | Creator-declared profile revisions via `/api/v1/creators/me/profile`. `test_creator_profile_report_api.py::test_profile_validation_and_revision_are_creator_declared` checks revision, validation, and no inferred demographics. | Synthetic/API verified. No Web onboarding flow. |
| Initial report before a draft | `/api/v1/creators/me/report` generates/replays an immutable versioned report without draft input. `test_onboarding_without_draft_returns_awaiting_import_report` and `test_opted_in_report_is_deterministic_personal_only_and_creator_scoped`. | Synthetic/API verified. Real creator history and usefulness are unverified. |
| Creator history and niche evidence | Creator-owned canonical history can feed a personal-only partial report when policy permits. Niche source selection is rejected while discovery is unavailable. Tests include `test_personal_history_requires_creator_consent_and_default_off_policy_gate`, `test_niche_source_selection_is_rejected_until_discovery_is_available`, and `test_metric_definition_conflicts_are_excluded_without_failing_other_metrics`. | Personal path is synthetic/API verified. Real history import is blocked by COD-348/COD-370; real niche evidence is blocked by COD-344 and COD-372. |
| Personal-only and insufficient-evidence states | Empty, unconsented, policy-blocked, missing-metric, and bounded-history states return explicit limitations or insufficient evidence. Covered in `test_creator_profile_report_api.py`, `test_creator_report.py`, and `test_report_evidence.py`. | Synthetic/API verified. No real-data coverage measurement. |
| Draft analysis and explainable Distribution Outlook | Authenticated baseline and immutable draft-assessment routes use deterministic retrieval and Outlook assembly. `test_analysis_api.py`, `test_persistence_postgres.py::test_creator_baseline_endpoint_returns_exact_window_zero_values_and_scoped_history`, `test_outlooks.py`, and `test_retrieval.py` cover contracts and core failure cases. | Synthetic/API verified. No creator-facing Web flow or real-data calibration claim. |
| Evidence and recommendation limitations | Exact metric definitions/windows, future cutoffs, source IDs, sample limitations, outliers, and non-causal language are checked by `test_outlooks.py`, `test_report_evidence.py`, and `test_postmortems.py`. | Synthetic verified. These are descriptive contracts, not proof of useful real-world advice. |
| Manual publication attachment | No production route or persistence workflow is present on `main`. The pure `PublishedPost` handoff is exercised by `test_postmortems.py`; it is not an attachment integration test. | Blocked by COD-361 (Platform). |
| Assessed-version match/mismatch/unknown | Pure postmortem verifies matching versions and withholds scoring for mismatch. This PR adds an explicit unknown-version case in `test_postmortems.py::test_unknown_publication_version_is_not_scored_as_the_assessed_draft`. | Synthetic contract verified. No publication-link API exists yet. |
| Real metric observation scheduling | COD-347 provides a budgeted read boundary; durable worker work is still in progress and real snapshot collection is not implemented. | Blocked by COD-362 (worker) and COD-363 (snapshot capture), plus COD-344 rights/cost gates. |
| Time-aligned postmortem | Pure COD-364 postmortem compares only compatible, age-aligned observations and abstains for missing, future, duplicate, sparse, mismatched-window/definition, cross-creator, or unverified-version inputs. `test_postmortems.py` covers these cases. | Synthetic engine verified. No persisted/API postmortem or genuine 24-hour observation. |
| Privacy, revocation, deletion and budgets | Report permission gates, creator scoping, revocation/deletion, session protections, and fail-closed X read budget/rights checks are tested in `test_creator_profile_report_api.py`, `test_auth.py`, `test_x_read.py`, and `test_persistence_postgres.py`. | Synthetic/API verified. Real account policy, entitlement, pricing and deletion operations remain unverified. |

## Independent synthetic gap closed

The existing postmortem tests covered an exact version match and a mismatch, but had no direct test for an explicitly **unknown** publication version. The added test confirms the observed metric remains visible while forecast deviation and hypothesis scoring are withheld. It does not create an attachment API or make a claim about real published content.

The other requested negative cases were already covered on the inspected `main`: empty/sparse history, a single viral outlier, missing or incompatible observation windows, conflicting metric definitions, insufficient evidence, cross-creator exclusion, rights-blocked processing, and budget denial. No duplicate services or tests were added for those behaviors.

## Current readiness and blockers

The independently runnable backend contracts can be checked with the repository API commands, and the Intelligence backtest suite is available as a synthetic, time-respecting evaluation. The complete one-account product journey cannot yet be accepted:

- **COD-344 — In Progress (Aliameen):** X account-specific endpoint entitlement, processing rights, approved analysis/inference scope, and enforceable live cost limits remain unresolved. No live request was made.
- **COD-349 — Backlog (Aliameen):** real authorized account connection and bounded real-data history verification remain pending.
- **COD-348 and COD-370 — Backlog (Yusuf):** canonical history import/normalization and safe archive import are not available for the journey.
- **COD-361 — Backlog (Yusuf):** publication attachment persistence and assessed-version linkage are not implemented.
- **COD-362 — In Progress (Yusuf) and COD-363 — Backlog (Yusuf):** durable observation scheduling and real metric snapshots are not yet available.
- **COD-367 — Backlog (Web owner):** Playwright coverage for the complete creator flow is not present. The current Web application remains a shell, so no UI end-to-end journey was run.
- **COD-372 — In Review (Aliameen):** niche evidence remains a separate pilot; it does not enable production niche search. COD-344 rights and budget gates still apply.

COD-354, COD-364, COD-366, and COD-378 are Done; their deterministic Outlook, pure time-aligned postmortem/backtest, and report-first API contracts are available for this synthetic verification preparation. Their completion does not satisfy missing Platform/Web integrations or the real-data gates above.

## Verification boundaries

- Synthetic fixtures and mocked providers establish deterministic contract behavior only. They do not establish X entitlement, data-processing rights, actual archive field coverage, live cost, rate behavior, or creator usefulness.
- No live X calls, real archive processing, third-party inference, billing, or real observation scheduling was performed.
- Do not claim improved reach, calibrated real-world predictive performance, representative niche evidence, or full V1 acceptance from these results.
- Re-run CI and the real one-account acceptance checklist on the final integrated branch after COD-348/349/361/362/363/367 and the COD-344 policy gate are ready. Do not close COD-368 before a genuine post-observation window is collected and reviewed.

## Reproduction

From `apps/api`, use the checks prescribed in `docs/development.md`:

```bash
uv run ruff check src tests alembic
uv run ruff format --check src tests alembic
uv run mypy src
uv run pytest -q
```

The focused added case can be run with `uv run pytest -q tests/test_postmortems.py -k unknown_publication_version`.
