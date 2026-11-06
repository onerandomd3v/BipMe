# Important — BipMe engineering guardrails

Use this as a **short checklist for high-consequence mistakes**, not another design document. For the rationale, read the linked guides.

## Critical product invariants

1. **Creator-relative, not universal.** Do not label a post as an objectively good/bad post or claim to know X's private recommendation score. [Product](product.md)
2. **No outcome leakage.** Comparable-post matching uses only information available at the prediction time; future metrics are excluded. [Architecture](architecture.md)
3. **Different histories, different clocks.** A 6-month-old post's cumulative impressions are not its 1-hour impressions. Compare at aligned windows only when that evidence exists. [Architecture](architecture.md)
4. **No fabricated precision.** Use expected ranges and High/Moderate/Low/Insufficient evidence labels. An arbitrary “81% confidence” is not a calibrated probability. [Product](product.md)
5. **No causal claims by default.** Outperformance versus baseline does not demonstrate that BipMe's recommendation caused the uplift. [Product](product.md)
6. **No silent X API spending.** Before any real import, record/limit reads, confirm billing and permissions, and reject budget-exceeding operations. [Security](security.md)
7. **No unsafe X-data handling.** Never commit tokens or creator datasets, scrape around the API, or train models on X content without verifying policy permission. [Security](security.md)
8. **No fake completion.** Current code implements an API health check and UI shell, **not** a working X connection or predictions. Clearly mark planned functionality until implemented and verified. [Architecture](architecture.md)
9. **No unapproved merges.** Open focused PRs and wait for explicit authorization before merging. [Development](development.md)

## Immediate external dependencies

The following must be resolved **before first live X read**, not before working on the scaffold:

- X Developer Console application permissions and OAuth redirect configuration.
- Authenticated test account allowlist and encryption/session-secret handling.
- Current endpoint accessibility, retention/display requirements and policy constraints.
- Current API pricing, monthly budget and per-operation hard limits.
- Validation that model inference/processing complies with developer terms.

## Scope discipline

Initially one test account, one codebase, one PostgreSQL database, read-only X integration. No public launch, multi-platform ingestion, automatic posting, complex deployment topology or speculative performance optimizations.

For source-level details use [research](research/README.md); for everyday operations use [development](development.md).
