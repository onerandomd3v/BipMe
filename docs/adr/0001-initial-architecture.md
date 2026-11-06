# ADR-0001: Initial BipMe Architecture

- **Status:** Accepted
- **Date:** 2026-11-06
- **Project:** BipMe
- **Decision scope:** First functional, single-creator experimental implementation

## Context

BipMe is a creator-specific distribution-intelligence product, beginning with X. The first goal is to validate an end-to-end intelligence workflow using one authorized X account and real post data—not to launch publicly or optimize for large-scale use. Architecture choices must be driven by the nature of the workload rather than an engineer's familiarity with a stack.

BipMe's primary work involves creator history ingestion, semantic post representations, comparable-post retrieval, robust statistical baselines, evidence-backed Distribution Outlooks, post-publish metric snapshots, and outcome evaluation.

## Decision

| Layer | Selected technology | Purpose |
| --- | --- | --- |
| API and application backend | **Python + FastAPI** | Typed API, OAuth integration, and direct access to statistical libraries |
| Intelligence package | **Python + NumPy, SciPy, scikit-learn** | Similarity, feature processing, robust statistics, evaluation and backtesting |
| Database | **PostgreSQL** | Canonical posts, profiles, creator state, forecasts, and metric observations |
| Similarity retrieval | **pgvector** | Post-embedding storage and nearest-neighbor retrieval in PostgreSQL |
| Persistence and migrations | **SQLAlchemy 2 + Alembic** | Explicit schema and query management, including vector SQL |
| Web client | **React + TypeScript + Vite** | Lightweight authenticated UI with no server-rendering requirement |
| Semantic embeddings | **SentenceTransformers**, using a locally hosted pretrained model | Reproducible inference without sending creator content to a third-party model by default |
| Background processing | **PostgreSQL-backed job queue and worker** | Delayed metric snapshots, history sync, retries, and postmortems; assess Procrastinate before adoption |
| Tests | **pytest + Playwright** | Unit, integration, integration-adapter and end-to-end tests |
| Local runtime | **Docker Compose** | Start database, API, worker and frontend locally |

**Clarification:** `intfloat/multilingual-e5-small` is an initial embedding-model candidate for benchmarking, **not a locked production selection**. Procrastinate is a candidate implementation of the PostgreSQL-backed job approach, **not yet a locked library**. Exact Python, PostgreSQL, pgvector and dependency versions will be pinned after compatibility checks.

**Explicitly not selected:** Prisma, NestJS, Redis/BullMQ, microservices, Kubernetes, a separate vector database, or a custom trained prediction model for this phase. These are not rejected forever; none is currently justified by the workload.

## System shape

```text
React / Vite web app
       |
       v
FastAPI application -------- Official X API (OAuth 2.0 + PKCE)
       |
       +---- BipMe intelligence Python package
       |        +-- canonical post profiling
       |        +-- semantic representation
       |        +-- comparable-post retrieval
       |        +-- robust creator baselines
       |        +-- distribution outlook
       |        +-- evidence / confidence
       |        +-- postmortem and backtesting
       |
       +---- PostgreSQL + pgvector
                    ^
                    |
             Python background worker
             (history sync, scheduled snapshots)
```

The intelligence engine is an **in-process Python package** reused by the API and worker, not a separate deployed microservice. Internal domains should remain modular and testable.

## Initial product workflow

1. Access a private BipMe environment and connect one authorized X account.
2. Fetch a cost-controlled portion of the account's history through official X endpoints.
3. Normalize source data into stable internal Post and Post Profile schemas.
4. Embed and classify eligible historical posts, then create a creator baseline.
5. Analyze a draft; retrieve comparable historical posts; provide a relative Distribution Outlook, expected range, evidence quality, and examples of contributing historical posts.
6. After a post is published manually on X, attach its URL/ID and capture observations over time.
7. Compare the actual 24-hour outcome with the original prediction and record evaluation metrics.

## Intelligence methodology: retained decisions

- Match against **the creator's own comparable historical posts**, not an arbitrary universal content-quality score.
- Keep **descriptive features** separate from performance **outcomes**, preventing selection and evaluation leakage.
- Start with **deterministic, statistical** baselines using robust weighted quantiles (especially P25/P50/P75), hierarchical backoff and explicit evidence strength.
- Keep retrieval, baseline, profile, embedding model and prediction configurations **versioned and reproducible**.
- Use **high/moderate/low/insufficient evidence** labels; do not present uncalibrated confidence scores as probabilities.
- Distinguish **mature historical outcomes** from **time-aligned snapshots**. Historical API data generally cannot reconstruct a post's original early trajectory.
- Validate through time-respecting walk-forward backtesting before making accuracy claims.
- Never claim access to X's hidden ranking score, viewer-level recommendation decisions, or causal recommendation lift without suitable evidence.

## X access, costs, and privacy guardrails

- Use the **official X API** and OAuth 2.0 Authorization Code Flow with PKCE. Request only required read scopes and offline access where necessary.
- Encrypt OAuth tokens at rest, never log them, and allow connection revocation/deletion.
- Use small progressive history syncs; record requests, estimated billable usage, and hard spend limits before the first real import.
- Recheck current pricing, rate limits, retention, display requirements, developer policy, and data-processing rights at integration time. Developer-console entitlements—not a historical research document—are authoritative.
- Prefer local pretrained inference; do not train or fine-tune on X-derived data without verified policy permission.
- Store observation timestamps honestly; handle rate limits and missing metrics explicitly.

## Non-goals for the experimental stage

Public launch, broad user signup, multi-tenancy, revenue/billing, follower-graph crawling, automatic X publishing, content automation, a high-scale event pipeline, multi-platform integrations, elaborate analytics dashboards, microservices, and learned ranking models.

## Initial implementation checkpoints

1. **Repository foundation:** folder structure, dependency and version pinning, Docker Compose, PostgreSQL/pgvector, SQLAlchemy/Alembic, lint/test/CI, basic protected access.
2. **X feasibility spike:** create developer application, validate OAuth with the test account, fetch a small set of posts and inspect actual metrics/permissions while logging cost.
3. **Intelligence spine:** canonical data models, Post Profiles, local embeddings, comparable retrieval, robust baseline and explainable Distribution Outlook.
4. **Feedback loop:** post attachment, background metric snapshots, 24-hour postmortem and walk-forward evaluation.

## Open decisions requiring a small proof of concept

- The specific locally run multilingual embedding model and its license, inference speed, retrieval quality and memory footprint.
- Which maintained PostgreSQL-backed worker library to select (Procrastinate is the first candidate).
- The exact account access/session design for a private single-user environment.
- Developer-console API billing limits, actual endpoint permissions and historical import cost.
- Formal data retention/deletion policy and allowed X-derived-data processing operations.
- Production hosting only when there is a reason to deploy externally.

## References

- `X_DISCOVERY_DISTRIBUTION_MVP.md`
- `X_DISTRIBUTION_INTELLIGENCE_RESEARCH_FINDINGS.md`
- `X_DISTRIBUTION_OUTLOOK_V1_DESIGN.md`
- `X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md`
- https://github.com/xai-org/x-algorithm
- https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code
- https://docs.x.com/x-api/fundamentals/metrics
- https://docs.x.com/x-api/getting-started/pricing
