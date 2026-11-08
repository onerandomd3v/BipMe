# BipMe — Technical architecture

**Status:** Current architecture and intended module boundaries. Marked `planned` components are **not yet implemented**. This is the living reference for engineers and coding agents.

## System at a glance

```text
React / TypeScript / Vite browser client
                  |
           HTTP / OpenAPI
                  |
         FastAPI Python app -----------------> Optional official X API
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

## Attention evidence and archive-first source boundary (planned; validation gated)

**V1 direction (8 Nov 2026):** support one private, authenticated creator with self-declared niche, audience and outcome preferences; prioritize feasibility of a creator-supplied post-history archive. Optional official X API connection is for permitted ingestion refresh or budgeted post-publication snapshots. Archive-only activity must have a secure server-side BipMe session independent of X OAuth; until built, COD-358 routes remain fail-closed. See COD-369 (archive format/rights gate), COD-370 (archive importer), COD-371 (goals/attention features) and COD-372 (niche pilot).

**Source-neutral, rights-aware ingestion boundary:**

```text
Creator-selected archive files (gated) --+
                                         +--> validated source adapter
Official X API (gated, budget-capped) ---+            |
                                                     v
                                    canonical posts + provenance +
                                    explicit metric/window availability
                                                     |
                                     versioned profiles / embeddings
                                                     |
                       +-----------------------------+------------------+
                       |                                                |
                 personal evidence                        permissioned niche evidence
                   (creator-owned)                         (research only; rights gated)
                       |                                                |
                       +--------------> separate comparisons <----------+
                                        |
                                goal-aligned observations,
                                optional experiment and limitations
```

- Archive parser must whitelist necessary post-history entries, guard against ZIP bombs/path traversal and ignore or promptly delete private unrelated material (DMs, contacts, account metadata). Require authenticated creator ownership, bounded uploads, idempotent import, provenance and deletion controls. No real X-derived text embedding/AI processing until applicable terms permit it.
- Archive records may have post text, publication timestamps and some engagement counters, but field availability must be measured on an actual export. Do not synthesize impressions, engagement-per-impression denominators, first-hour signals or historical attention-to-distribution sequences from a single export snapshot.
- Keep publication time separate from observation time, exact metric definition and age/cumulative window distinct, and source-of-truth/provenance attached to each imported observation. Do not blend unknown with known zero.
- Niche intelligence is a **separate, permissioned research pool** rather than cross-creator mixing in COD-352's same-creator retrieval. Sample strong/typical/weak comparables to avoid viral-only selection bias; control for available creator size, niche, format and observation age. Ship no shared training, raw-content display, crawling or cross-account pipeline without explicit rights clearance and an evaluated data-quality case.
- Extend features only through versioned content/goal contracts, preserving COD-350's descriptive-only fields and COD-353/354's outcome separation. Test whether attention-oriented features add explanatory value above the current baselines; don't claim to model X's private ranking, viewer exposure cohorts or engagement-caused amplification.
- COD-344 retains policy/entitlement/spend verification for official X use; COD-346 keeps secure X OAuth for optional connections and coordinates a separate private session; COD-348 stays responsible for budgeted API ingestion/normalization; COD-363 remains optional real-snapshot monitoring. COD-358's existing authenticated API and immutable decisions should not be weakened.

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

**Not currently implemented:** X adapter, login/session system, background worker, real X ingestion, calibrated prediction or metrics collection. COD-352 pure retrieval/reranking, COD-353 baseline calculations, COD-354 deterministic Outlook assembly and the COD-358 private analysis API/data adapters are implemented. The COD-358 production routes remain fail-closed until COD-346 provides a verified server session. Local synthetic CPU embedding inference is available; no live X text is processed.

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
                           (structure, topology, topic,
                            intent, format) + separate embedding
                                   |
Draft -> draft Post Profile -> comparable post retrieval
                                   |
                          persisted Comparable Set
                                   |
                      outcomes of selected historical posts
                                   |
                    robust baseline + repeatability /
                       outlier / sample-strength checks
                                   |
                      evidence-backed observations
                      + optional testable next action
                      + Outlook only when justified
                                   |
                     manually published attached X Post
                     + original assessment / hypothesis
                                   |
                    real timestamped metric snapshots
                                   |
                    evidence-aware learning postmortem
                                   |
                     versioned prediction evaluation
```

### Non-negotiable data separation

- **Post description/features** cannot include the outcome being predicted.
- **Post outcomes/metrics** remain separate, timestamped records.
- **Comparable sets** must be reproducible and bounded by `features_as_of`.
- **Future observations** cannot be used in a historical backtest.
- **Model, feature, retrieval and baseline versions** must be recorded for reproducibility.

### COD-350 Post Profile contract

`apps/api/src/bipme/intelligence/post_profiles.py` extracts `post-profile-v1` from provider-neutral, timestamped input. Its frozen output is the typed descriptive input consumed by the pure COD-352 retrieval engine; embedding vectors remain in the separate COD-351 interface and observed outcomes remain separate records. COD-345 supplies the shared persistence representation and migration; full runtime integrations remain separate work.

- `features_as_of` bounds both the content/format observation and creator-context snapshot. Future observations, naive timestamps, and unsupported feature versions are rejected. The profile stores input and creator-context observation times so consumers can assess provenance and staleness.
- `None` means unknown; empty text and an empty media tuple mean known absence. Text length counts Unicode code points, word count counts Unicode word tokens after URLs are removed, and sentence count uses punctuation boundaries (`.`, `!`, `?`) after URL removal. These are lexical heuristics, not language understanding.
- Hashtags are case-folded topic signals, with duplicates retained in the structural list and removed in the topic-signal list. A topic or intent label is included only when explicitly supplied by the creator. `question_marker` and `reply_invitation` describe visible wording, not the creator's true intent or likely performance.
- Format uses known media metadata, topology and thread role; missing metadata stays unknown. The input and profile have no impression, engagement, outcome or future audience fields. A new extraction algorithm must receive a new supported version, and historical profiles must be regenerated before retrieval mixes versions.

### COD-352 comparable retrieval contract

`apps/api/src/bipme/intelligence/retrieval.py` implements deterministic, provider-neutral retrieval and re-ranking over a bounded candidate page. `VectorCandidateSource` is the persistence boundary; `InMemoryVectorCandidateSource` provides an exact-cosine synthetic implementation. COD-345 supplies the canonical schema, migration and partial pgvector HNSW index. COD-358's `PostgresVectorCandidateSource` executes the bounded query, maps canonical rows, and returns total/vector candidate counts, deterministic truncation and storage-side exclusion reasons. The intelligence engine rechecks eligibility after retrieval.

- A candidate must be available, belong to the assessment creator, have been published strictly before the cutoff, and have a valid embedding in the exact model/revision/dimensions/preprocessing/normalization/embedding-version space. Candidate embedding observation, profile `features_as_of`, profile input observation and creator-context observation must all be no later than the assessment cutoff. Draft-side profile and embedding are likewise validated at construction.
- A missing profile, incompatible profile version, duplicate post ID, missing/corrupt embedding, future timestamp or unavailable post is excluded with explicit reasons. Known topology, thread-role and content-format mismatches are hard exclusions; unknown fields stay unknown and are omitted from scoring. When configured for a baseline, required metric definition/window evidence must be usable and observed after publication but no later than the assessment. Metric values are not part of the retrieval contract.
- The versioned starter ranking uses cosine mapped to `[0,1]`, `0.30 × semantic + 0.18 × topic Jaccard + 0.15 × intent agreement + 0.12 × format compatibility`; it computes structural-length similarity too, but its default weight is zero. Available configured components are normalized by their active weights. These are the illustrative, configurable values from the research design, not validated weights. The default minimum relevance of `0.55`, three-match evidence minimum, 100-candidate query limit and 20-result limit are configurable engineering heuristics, not calibrated quality thresholds. Ties resolve by stable post ID. No outcome value participates in score calculation.
- Output is a frozen `ComparableSet` with assessment ID, algorithm/config version, embedding identity, cutoff, ranked IDs, component scores, relevance, inclusion/exclusion reasons, candidate counts, source truncation and explicit `matched`, `insufficient_evidence` or `no_match` state. `insufficient_evidence` and `no_match` never force low-scoring matches.
- COD-345 supplies canonical post/creator IDs, publication/availability, versioned profiles and observation timestamps, exact embedding identities and vectors, plus outcome metric definition/window and observed/missing state. COD-358 implements the read adapter and bounded candidate metadata without changing COD-352's public contracts. It does not use outcomes to select or rank candidates.
- A COD-353 caller can map returned post IDs and positive relevance-derived weights to its `OutcomeObservation` inputs only after retrieval; outcome values cannot flow back into retrieval. COD-354 can consume the same IDs, component scores, reasons, evidence state and coverage limitations for creator-facing explanations.

### COD-345 canonical persistence contract

`apps/api/src/bipme/persistence/models.py` is the SQLAlchemy owner of the initial canonical PostgreSQL schema. Migration `0002_canonical_persistence` extends the already-applied `0001_enable_vector` foundation; it does not rewrite the initial migration.

- `creators` owns stable internal UUIDs. `creator_platform_identities` maps `(platform, external_creator_id)` uniquely to one creator. `x_account_connections` references the identity and same creator with a composite foreign key; its opaque token columns require a `BIPME-ENC` v1 envelope marker and retain key-version/expiry/rotation metadata. The marker only rejects ordinary plaintext values; Platform code must encrypt before writing and clear both tokens on revocation. This schema does not provide encryption or OAuth.
- `canonical_posts` stores platform/external ID, creator, publication time, availability/deletion state and known reply/quote/thread topology. Provider payloads and raw post text are excluded. `(platform, external_post_id)` and creator-scoped ingestion keys make repeated imports idempotent. Reply links and assessment links are creator-scoped by composite foreign keys.
- `post_profiles` stores a versioned COD-350 descriptive `PostProfile` JSON object plus queryable version/cutoff/observation columns. JSON `null` retains unknown values and empty arrays retain known absence. Outcome metrics and embeddings are separate tables. The adapter round-trips the frozen `PostProfile`; unsupported versions fail closed.
- `post_embeddings` stores the COD-351 vector and every `EmbeddingIdentity` field, with a unique key per post and full identity. V1 uses `vector(384)` and a partial HNSW cosine index for the pinned E5 identity only. A dimension/model/configuration change requires an explicit migration and reindex; vectors from different identities are never compared.
- `outcome_observations` is append-only by exact metric definition, unit, window kind/key and observed timestamp. `observed`, `missing` and `invalid` states distinguish zero from missing. `mature_cumulative` and `age_aligned` are distinct. The stored publication timestamp is protected by a composite foreign key against the canonical post; measurement times cannot predate publication. The COD-353 adapter encodes identity as `definition|unit=<unit>` and `<window_kind>:<window_key>` because its current contract has one definition and one window string. It skips invalid records and requires caller-provided, non-outcome relevance weights.
- `api_usage_ledger` records sanitized provider/operation/request metadata, units, estimated/actual costs and reconciliation state with provider-scoped idempotency keys. Do not put tokens, headers, raw payloads or unnecessary user content in metadata.
- `draft_assessments` stores a versioned immutable COD-354 decision snapshot and optional creator-accepted hypothesis. A database trigger rejects updates. A published `canonical_posts` row can reference one assessment from the same creator and records `match`, `mismatch` or `unknown` version status; attaching a post never rewrites the original outlook or hypothesis. COD-358 should persist the full stable JSON snapshot and accepted hypothesis at creation time; COD-361 owns the later attachment/version comparison. This is a small snapshot/link boundary, not an experiment service.

`persistence/contracts.py` maps canonical rows to existing intelligence dataclasses without changing their public contracts. `pgvector_candidate_statement(VectorCandidateQuery)` applies same-creator, available-post, strict publication cutoff, latest eligible profile, profile/context/embedding observation cutoffs and exact full embedding identity before cosine-distance ordering and bounded top-K. `PostgresVectorCandidateSource` adds total and vector-eligible counts, truncation and reasons for storage-filtered rows; COD-352 still owns final eligibility/reranking. The HNSW index only serves the current E5 identity. `BIPME_TEST_DATABASE_URL` enables real PostgreSQL tests for query execution and migration upgrades/downgrades.

### COD-358 API and persistence orchestration

- `GET /api/v1/creators/me/baseline` accepts an exact metric, definition, unit, window kind/key and optional `as_of`. It returns COD-353's version, eligible/effective sample sizes, robust percentiles, repeatability/outlier indicators, exclusions and limitations. Known incompatible definitions, units or windows return structured 422 errors; no historical series returns a valid Insufficient result.
- `POST /api/v1/creators/me/draft-assessments` accepts a validated draft, descriptive metadata, optional exact metric preferences, an optional creator-selected hypothesis, and an `Idempotency-Key`. It extracts COD-350 features, generates a COD-351 local embedding, retrieves/reranks via COD-352, reads outcomes only after comparable selection, and assembles COD-354's immutable response.
- `GET /api/v1/creators/me/draft-assessments/{assessment_id}` returns only assessments owned by the verified creator; foreign or absent IDs both return 404. Creator identity is never accepted from request content.
- The analysis input fingerprint uses SHA-256 over a version marker and canonical sorted JSON. Draft text is NFC-normalized, CRLF/CR become LF, and meaningful leading/trailing whitespace is preserved. Fingerprinted metadata includes topology, media, declared labels and exact metric preferences. Raw draft text is not persisted. Same creator/key/fingerprint replays the original snapshot; a different input under the same key returns 409.
- `draft_assessments` stores the immutable response snapshot, original assessment time/fingerprint, algorithm/configuration/embedding identity through the snapshot, and optional accepted hypothesis at insert time. The database trigger prevents edits; later observations cannot revise it. The accepted hypothesis is creator-supplied with the initial assessment because the COD-345 row is immutable. COD-361 remains responsible for manual publication linkage.
- OpenAPI is generated to `apps/api/openapi.json` from `create_app().openapi()`. Authenticated endpoints currently fail closed with `authentication_not_configured` until COD-346's server-side session dependency is implemented; tests override the dependency with synthetic verified creator identities.

## V1 creator decision and experiment contract (planned)

- **Decision-first output:** never expose only a "viral potential" score. For an analyzed draft return the eligible comparables and relevance reasons, supported pattern observations, named uncertainty and an actionable *suggestion to test* only when justified. Relative outcome intervals are **secondary** and optional: when evidence is insufficient, abstain rather than fabricate a range.
- **Pattern repeatability:** compute robust distributions and effective samples across eligible posts; surface the number of supporting examples, consistency or dispersion and outlier sensitivity. A single high-performing post does **not** establish a repeatable content formula. Prefer robust summaries over the highest-impression post.
- **No causal inference:** topic/style correlations cannot establish why an X post was distributed or what intervention will increase reach. Suggested next actions are **hypotheses**, not directives, probabilities or proven optimizations. Only include a concrete suggestion when it can cite comparable IDs and measured features/outcomes; otherwise show an insufficient-evidence message.
- **Lightweight experiment:** reuse the draft/Outlook record for one optional, short hypothesis or test question and a supported target metric/window when the creator chooses to test an idea. Do **not** add a separate experiment service, cohort allocation, auto-publishing or complex dashboard. Persist the *original* assessment and hypothesis immutably so observed outcomes cannot rewrite pre-publication reasoning.
- **After publishing:** link the attached X Post to the **immutable original assessment/hypothesis**, its content fingerprint, and **real** metric observations. Verify whether the published content matches the draft version that was assessed. If materially revised, retain the earlier advice as context but require reassessment of the published version **or exclude the mismatched version from forecast-error/backtest evaluation**; never score a different draft's outcome as the original forecast's accuracy. Return *supported*, *contradicted* or *inconclusive* strictly as an evidence-limited descriptive status, **not** causal proof. Avoid equal-age comparisons unless real snapshots for the matching windows exist; missing historical trajectories remain unavailable.
- **API/storage coordination:** intelligence owns pure repeatability, evidence and suggestion logic; Platform owns canonical records, optional hypothesis persistence and FastAPI/OpenAPI contracts; Web renders the same evidence/action/outcome loop. Keep schema changes minimal and agree contracts before migrations (COD-345, COD-358, COD-354).
- **V1 acceptance:** one authorized creator can move from meaningful historical evidence to a draft decision, optional experiment and linked actual outcome. No claim of validated demand, better reach or predictive accuracy without measured evidence. V1 user testing may occur after shipping; extensive interviews are not a prerequisite.

## Baselines and evidence

1. Eligible comparables are **earlier posts by the same creator** with compatible topology and usable metrics.
2. Prefer semantic nearest-neighbor retrieval (pgvector) followed by deterministic feature-based re-ranking; weights remain configuration, not magic constants.
3. Use weighted robust quantiles, historical percentile comparisons, effective sample size and hierarchical fallback for sparse evidence.
4. Report evidence quality **High / Moderate / Low / Insufficient**.
5. Keep mature historical metrics and captured **same-window** snapshots in different outcome categories.
6. Audit prediction error via time-respecting backtests before making accuracy claims.

See [the original detailed scoring design](research/X_DISTRIBUTION_OUTLOOK_V1_DESIGN.md). Experimental default weights in that document are hypotheses, not validated facts.

### COD-353 creator baseline contract

`apps/api/src/bipme/intelligence/baselines.py` implements the pure, provider-neutral
`creator-baseline-v1` calculation over timestamped `OutcomeObservation` values. A caller
provides the creator identity, metric definition, exact comparison window, assessment
timestamp, optional target value, hierarchical segment path and non-outcome-derived weights.
The engine excludes observations from another creator or metric definition. The record keeps `published_at`
separate from the actual `observed_at`; both must be no later than the assessment time and
the observation cannot predate publication. A metric/window pair is never mixed: mature
cumulative totals and snapshots such as `age:1h` are separate distributions. A known missing
measurement must be passed explicitly with a `None` value; the engine does not fabricate
missing snapshots from cumulative history.

Weighted empirical inverse-CDF P10/P25/P50/P75/P90, IQR, normalized dispersion, 3×IQR
outlier counts, central-consistency share, weight concentration and Kish effective sample
size are exposed. Percentile rank uses a weighted midrank. The outlier-adjusted median and
its shift in IQR units show sensitivity to extreme observations. Hierarchical segments use
the most specific prefix with effective N≥3; otherwise the baseline backs off to the
broader prefix and reports the level and supporting post IDs. When a specific group has
effective N≥3, each weighted quantile shrinks toward the immediately broader distribution
with λ=N_eff/(N_eff+8). These calculations are deterministic and intentionally use only
eligible historical inputs.

Evidence labels are initial engineering heuristics, not calibrated probabilities: High
requires effective N≥20, ≥70% of values within 3×IQR fences and no observation above 20% of
total weight; Moderate requires effective N≥8, ≥60% within fences and no observation above
35% of weight; Low is effective N≥3 when stronger criteria fail; below 3, the engine returns
Insufficient and abstains from an interpretation. Outlier flags and consistency describe
repeatability only; they do not establish causation. The thresholds need walk-forward
evaluation before being treated as product confidence.

The pure input/output dataclasses are an intelligence contract, not a shared database
schema. COD-345 should map its canonical outcome records to these values and preserve the
metric unit/definition, creator identity, exact observation window, publication time, actual observation time,
stable post ID, missing-window knowledge and caller-computed comparable weight/segments.
COD-352 may provide eligible comparable IDs and relevance-derived weights; COD-354 can
consume the versioned result and exclusion/evidence reasons without changing this engine.

## Embedding inference and portability

- **V1 starting model:** `intfloat/multilingual-e5-small` (384 dimensions), run locally on a **CPU** first. This is the practical implementation default, **not a validated accuracy winner**. Confirm resource use and actual retrieval quality on the intended machine before declaring readiness.
- **Hosting:** run pretrained inference in the existing Python application/worker environment (local development machine or CPU VPS). No dedicated model-serving microservice, GPU or paid hosted embedding endpoint is required for the first version. Load model weights once per process rather than per post.
- **Model-agnostic boundary:** intelligence logic calls a small internal embedding interface for batched text encoding; the selected model, its text-prefix/task rules and local/hosted inference mechanism remain behind that boundary. Do not create an elaborate plugin framework in advance.
- **Model identity and reproducibility:** persist model identifier, pinned checkpoint revision, vector dimension, normalization, text preprocessing/prompt strategy and embedding generation version alongside the indexed data. For E5, follow the official `query:`/`passage:` task guidance. Do not compare vectors created by different models/configurations; a model change requires a deliberate re-embedding and index migration or version-partitioned indexes.
- **Evaluation:** implement small deterministic synthetic relevance/quality tests plus CPU latency and memory measurements in V1. Keep `Qwen/Qwen3-Embedding-0.6B` and `google/embeddinggemma-2` as optional challengers for a later task-driven comparison; do not block the first working retrieval pipeline on a three-model competition.
- **Policy/security:** before processing real X-derived post text, verify that the applicable X terms permit this inference use case. Local inference is preferred to limit unnecessary external data transfer; do not train/fine-tune on X content without independently verified permission.
- **Deployment portability:** the same internal embedding contract can later use a local CPU/GPU, a self-managed inference process or an approved external provider without rewriting feature extraction, retrieval or baselines. Hosted inference is not part of V1.

### Social-platform boundary

Keep X-specific authentication, API field mapping, pagination, cost policy and metric availability in `integrations/`. The canonical post/profile/outcome representations and intelligence algorithms should not rely on raw X response objects. This makes future platforms possible **without** promising that different networks expose interchangeable metrics or building additional integrations now.

### COD-351 embedding contract

- `apps/api/src/bipme/intelligence/embeddings.py` now defines a `TextEmbedder` protocol, `EmbeddingIdentity`, and CPU-only E5 adapter with official `query:`/`passage:` prefixes and normalized, validated 384-dimensional vectors. The model is loaded lazily and cached per process.
- `EmbeddingIdentity.index_key` records model ID, **immutable checkpoint commit SHA**, vector dimensions, preprocessing version, embedding generation version, and normalization. Persistence/index design is owned by COD-345. A change in any of these must trigger re-embedding and reindexing, never cross-model vector comparison.
- The default pinned model revision is [`fd1525a9fd15316a2d503bf26ab031a61d056e98`](https://huggingface.co/intfloat/multilingual-e5-small/commit/fd1525a9fd15316a2d503bf26ab031a61d056e98), independently verified on Hugging Face (MIT license). `BIPME_EMBEDDING_MODEL` selects the initial E5 model; unsupported models fail explicitly until their adapter exists. Override the checkpoint only with an explicitly verified immutable revision via `BIPME_EMBEDDING_REVISION` (40-character SHA). No checkpoint weights or X data are committed. Routine unit tests use synthetic text and a fake encoder; they do **not** download weights.
- `sentence-transformers` and the CPU-only PyTorch wheel are locked runtime dependencies; uv uses PyTorch's CPU wheel index on Windows and Linux. Local inference on an Intel Core i7-8565U with 16 GiB RAM loaded the pinned checkpoint offline from cache and returned normalized 384-dimensional vectors. With the final CPU wheel, process load (including lazy Python imports) took 144.3 seconds; encoding four synthetic passages took 0.466 seconds and three synthetic queries took 0.063 seconds. After loading, process working set was 1033 MiB, private memory 1631 MiB and peak working set 1077 MiB. All three synthetic queries ranked the intended passage first. The initial online run with the earlier PyPI wheel took 265 seconds including weight download; those timings are not directly comparable. These are smoke measurements on one Windows CPU machine, not a throughput, VPS, multilingual-quality, or accuracy benchmark.
- For a different model, implement its `TextEmbedder` adapter and explicitly configure its model ID, immutable revision, dimensions, preprocessing rules, normalization and embedding version. Do not reuse an E5 identity or vector index. Backfill all eligible historical texts through the new adapter into a new versioned vector space, build its index, validate retrieval, then switch reads to that version; retire the old index only after the backfill and consumers are verified. COD-345 owns the persistence schema and migration, so no existing row or index is claimed to be updated by this adapter alone.
- To repeat the real synthetic smoke check locally after installing locked API dependencies, run `BIPME_RUN_LIVE_EMBEDDING_SMOKE=1 uv run pytest -q tests/test_embeddings.py` from `apps/api` (set the environment variable with PowerShell syntax on Windows). Routine CI leaves that variable unset and does not download weights.
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
- `intelligence/outlooks.py` implements a pure `build_distribution_outlook(OutlookRequest)` service over the existing draft, comparable-set and baseline contracts. The caller supplies a validated `sha256:` content fingerprint and may supply selected comparable profiles for pattern testing; the service does not derive a hash or receive raw post text.
- The frozen `DistributionOutlook` preserves retrieval and baseline versions, embedding identity, cutoff, ranked comparable IDs/relevance/components/inclusion reasons, retrieval counts/exclusion reasons/coverage limits, exact metric/definition/window evidence, evidence strength, limitations, up to two historical observations and at most one optional measurable experiment. Positive retrieval relevance is the only outcome weight. Weighted P25–P75 values are historical reference ranges, emitted only for High/Moderate evidence at or above the configured, versioned metric-coverage threshold (60% by default) with complete, untruncated retrieval. The result has stable JSON serialization and contains no provider payload.
- Suggestions are considered only for a descriptive feature present on the assessed draft, with at least three effective measured comparables in both the matching and comparison groups. They report weighted historical medians and an optional same-window test question; they do not claim that the feature caused the outcomes.
- COD-358 exposes the baseline, draft-analysis and same-creator assessment-read routes listed above. The draft-analysis response carries the stable input fingerprint, algorithm/config versions, comparable IDs and relevance evidence, exact metric/window observations and limitations, optional reference ranges/suggestion, and explicit insufficient-evidence state. Post-publication outcomes must not revise the original response.

FastAPI's generated OpenAPI output is the source of truth for client generation. No hand-maintained TypeScript response interfaces are introduced. COD-356/COD-360 should consume the generated schema artifact and routes described above; production requests remain unavailable until COD-346 authorization is wired.

## Security, constraints and references

See [Security](security.md), [Product](product.md), [Development](development.md), and the [original engineering blueprint](research/X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md). Avoid elevating dated research about API prices, permissions or X's internal algorithm into current implementation fact without verification.
