# BipMe — Technical architecture

**Status:** Current architecture and intended module boundaries. Marked `planned` components are **not yet implemented**. This is the living reference for engineers and coding agents.

## System at a glance

```text
React / TypeScript / Vite browser client
                  |
           HTTP / OpenAPI
                  |
         FastAPI Python app -----------------> Official X API
                  |                             OAuth 2.0 + PKCE
     +------------+--------------+
     |                           |
     v                           v
BipMe intelligence         SQLAlchemy/Alembic
(in-process modules)              |
     |                            v
     +-------------------> PostgreSQL + pgvector
                                      ^
                                      |
                         PostgreSQL-backed worker
                            (planned, separate process)
```

The API and future worker share one `apps/api/src/bipme` Python codebase. The intelligence engine is an **in-process package**, not a separately deployed microservice. PostgreSQL is the sole state store; Redis or an external vector DB is not needed initially.

## Technology (approved)

| Area | Selection |
| --- | --- |
| API | Python 3.13, FastAPI |
| Python dependencies | uv, pinned lockfile |
| Data / schema | PostgreSQL 17 with pgvector, SQLAlchemy 2, Alembic |
| Intelligence computations | NumPy, SciPy, scikit-learn (add dependencies when implementation needs them) |
| Semantic embeddings | SentenceTransformers with pretrained inference, model candidate to be benchmarked |
| Browser | React 19, TypeScript, Vite |
| Frontend dependencies | pnpm 10, committed lockfile |
| Jobs | PostgreSQL-backed delayed jobs; choose maintained runner after a narrow test |
| Quality | Ruff, mypy, pytest, ESLint, TypeScript, Playwright when E2E flows exist |
| Local infrastructure | Docker Compose for PostgreSQL |

**Not currently implemented:** X adapter, login/session system, background worker, embeddings, prediction, baseline or metrics collection. An installed library does not imply a working feature.

## Repository

- `apps/api/src/bipme/api/`: HTTP entrypoint and route validation.
- `apps/api/src/bipme/integrations/`: provider-specific clients; official X API responses map to internal structures here.
- `apps/api/src/bipme/intelligence/`: deterministic profiling/retrieval/baselines/prediction/backtesting.
- `apps/api/src/bipme/persistence/`: SQLAlchemy schema and database coordination.
- `apps/api/src/bipme/jobs/`: shared job handlers/worker entrypoint when built.
- `apps/api/alembic/`: schema migration history.
- `apps/web/src/`: client views, state and typed API access.
- `docs/research/`: original product and prediction design sources.

Create new modules for an implemented domain as needed; do not pre-create dozens of empty modules merely to match the early blueprint.

## Data path (planned)

```text
X history read -> X adapter -> canonical post + creator state
                                   |
                                   v
                             descriptive Post Profile
                           (content, topology, topic,
                            intent, format, embedding)
                                   |
Draft -> draft Post Profile -> comparable post retrieval
                                   |
                          persisted Comparable Set
                                   |
                      outcomes of selected historical posts
                                   |
                    robust creator baseline (P25/P50/P75)
                                   |
                       evidence-backed Distribution Outlook
                                   |
                  manual publication / attached X Post
                                   |
                   time-stamped metric snapshots -> postmortem
                                   |
                         versioned prediction evaluation
```

### Non-negotiable data separation

- **Post description/features** cannot include the outcome being predicted.
- **Post outcomes/metrics** remain separate, timestamped records.
- **Comparable sets** must be reproducible and bounded by `features_as_of`.
- **Future observations** cannot be used in a historical backtest.
- **Model, feature, retrieval and baseline versions** must be recorded for reproducibility.

## Baselines and evidence

1. Eligible comparables are **earlier posts by the same creator** with compatible topology and usable metrics.
2. Prefer semantic nearest-neighbor retrieval (pgvector) followed by deterministic feature-based re-ranking; weights remain configuration, not magic constants.
3. Use weighted robust quantiles, historical percentile comparisons, effective sample size and hierarchical fallback for sparse evidence.
4. Report evidence quality **High / Moderate / Low / Insufficient**.
5. Keep mature historical metrics and captured **same-window** snapshots in different outcome categories.
6. Audit prediction error via time-respecting backtests before making accuracy claims.

See [the original detailed scoring design](research/X_DISTRIBUTION_OUTLOOK_V1_DESIGN.md). Experimental default weights in that document are hypotheses, not validated facts.

## X integration boundary (planned)

- Use official X OAuth 2.0 PKCE and only necessary read scopes.
- Treat X response JSON as untrusted, optional external input. The canonical internal model must **not mirror provider payload shapes**.
- Store tokens securely (encrypted, with lifecycle controls); do not put OAuth tokens into frontend storage or logs.
- Record actual request usage/cost estimates and enforce hard ceilings before first live import.
- Handle revocation, rate limits, pagination, partial/missing metrics and retries honestly.

## Current implemented contract

- `GET /api/health` → `{"status":"ok"}` (liveness only, not a database-readiness check).
- Alembic initial migration enables the `vector` extension.
- The frontend checks `/api/health` through the Vite development proxy.

All other endpoints are **proposals**, not committed API contracts. When introduced, FastAPI's OpenAPI output becomes the source of truth for generating frontend API types.

## Security, constraints and references

See [Security](security.md), [Important](important.md), [Product](product.md), [Development](development.md), and the [original engineering blueprint](research/X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md). Avoid elevating dated research about API prices, permissions or X's internal algorithm into current implementation fact without verification.
