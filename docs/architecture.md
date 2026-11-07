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
| Semantic embeddings | CPU-first local SentenceTransformers inference; initial implementation model `intfloat/multilingual-e5-small` (384d), replaceable via a narrow embedding adapter |
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

## Embedding inference and portability (approved direction, not yet implemented)

- **V1 starting model:** `intfloat/multilingual-e5-small` (384 dimensions), run locally on a **CPU** first. This is the practical implementation default, **not a validated accuracy winner**. Confirm resource use and actual retrieval quality on the intended machine before declaring readiness.
- **Hosting:** run pretrained inference in the existing Python application/worker environment (local development machine or CPU VPS). No dedicated model-serving microservice, GPU or paid hosted embedding endpoint is required for the first version. Load model weights once per process rather than per post.
- **Model-agnostic boundary:** intelligence logic calls a small internal embedding interface for batched text encoding; the selected model, its text-prefix/task rules and local/hosted inference mechanism remain behind that boundary. Do not create an elaborate plugin framework in advance.
- **Model identity and reproducibility:** persist model identifier, pinned checkpoint revision, vector dimension, normalization, text preprocessing/prompt strategy and embedding generation version alongside the indexed data. For E5, follow the official `query:`/`passage:` task guidance. Do not compare vectors created by different models/configurations; a model change requires a deliberate re-embedding and index migration or version-partitioned indexes.
- **Evaluation:** implement small deterministic synthetic relevance/quality tests plus CPU latency and memory measurements in V1. Keep `Qwen/Qwen3-Embedding-0.6B` and `google/embeddinggemma-2` as optional challengers for a later task-driven comparison; do not block the first working retrieval pipeline on a three-model competition.
- **Policy/security:** before processing real X-derived post text, verify that the applicable X terms permit this inference use case. Local inference is preferred to limit unnecessary external data transfer; do not train/fine-tune on X content without independently verified permission.
- **Deployment portability:** the same internal embedding contract can later use a local CPU/GPU, a self-managed inference process or an approved external provider without rewriting feature extraction, retrieval or baselines. Hosted inference is not part of V1.

### Social-platform boundary

Keep X-specific authentication, API field mapping, pagination, cost policy and metric availability in `integrations/`. The canonical post/profile/outcome representations and intelligence algorithms should not rely on raw X response objects. This makes future platforms possible **without** promising that different networks expose interchangeable metrics or building additional integrations now.

### COD-351 embedding contract (initial implementation, not yet fully deployable)

- `apps/api/src/bipme/intelligence/embeddings.py` now defines a `TextEmbedder` protocol, `EmbeddingIdentity`, and CPU-only E5 adapter with official `query:`/`passage:` prefixes and normalized, validated 384-dimensional vectors. The model is loaded lazily and cached per process.
- `EmbeddingIdentity.index_key` records model ID, **immutable checkpoint commit SHA**, vector dimensions, preprocessing version, and normalization; persistence/index design is owned by COD-345. A change in any of these must trigger re-embedding and reindexing, never cross-model vector comparison.
- The runtime uses `BIPME_EMBEDDING_REVISION` (an explicit 40-character model commit SHA). No checkpoint weights or X data are committed. Unit tests use synthetic text and a fake encoder; they do **not** download weights.
- **Still required to close COD-351:** add `sentence-transformers` through uv with a genuine regenerated `uv.lock`, choose/verify the pinned checkpoint hash, and run a measured real CPU-only smoke test (latency/memory and retrieval sanity) on the intended hardware. Do not claim real embeddings are deployed based on fake encoder tests.
- Processing real X post text remains disallowed until COD-344 resolves applicable inference data-use rights; archive-based data imports are a separate future ingestion decision, not an authorization bypass.

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

See [Security](security.md), [Product](product.md), [Development](development.md), and the [original engineering blueprint](research/X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md). Avoid elevating dated research about API prices, permissions or X's internal algorithm into current implementation fact without verification.
