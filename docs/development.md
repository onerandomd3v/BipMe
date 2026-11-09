# BipMe — Development guide

**Status:** Deterministic intelligence, canonical persistence, COD-358 analysis routes, COD-346 private session/auth contracts, and COD-362 PostgreSQL worker infrastructure are implemented. Private sessions and the current creator endpoints remain fail-closed until the configured creator, database and private login secret are provisioned. X OAuth is opt-in and remains disabled until COD-344's account-specific access and rights gates are verified.

## Prerequisites

- Python **3.13**, with [uv](https://docs.astral.sh/uv/)
- Node.js **24** and **pnpm 10**
- Docker with Compose
- Git and a GitHub account with repo access

From the repository root, `apps/api` and `apps/web` are independent dependency roots, even though the code lives in one monorepo. Commit both `uv.lock` and `pnpm-lock.yaml` on dependency changes.

## Local database

```bash
docker compose up -d --wait db
docker compose ps
```

The `--wait` flag waits for the configured PostgreSQL health check to pass before proceeding to migrations. If the service never becomes healthy, check `docker compose logs db` before continuing.

The local service exposes PostgreSQL on `127.0.0.1:5432` with **development-only** credentials in `compose.yaml`. Never reuse them outside local development. The volume persists between restarts.

The scaffold's Alembic configuration reads `BIPME_DATABASE_URL` **from the process environment**. Merely copying `.env.example` does **not** currently auto-load it. Authentication secrets and creator IDs are also read from the process environment; keep real values out of Git.

Linux/macOS Bash:

```bash
export BIPME_DATABASE_URL='postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
```

Windows PowerShell:

```powershell
$env:BIPME_DATABASE_URL = 'postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
```

## Start the API

```bash
cd apps/api
uv sync --locked --group dev
uv run alembic upgrade head
uv run uvicorn bipme.api.app:app --reload
```

Run a separate durable job worker with the same database URL:

```powershell
cd apps/api
uv run python -m bipme.jobs
```

The worker listens only to the `bipme` queue, retains runner jobs, uses a 30-second graceful timeout, and checks for stalled workers by heartbeat. Recovery is supervised alongside the worker; a recovery failure stops intake and drains the worker before returning a sanitized failure. A handler must complete within a bounded duration because Python cannot cancel its synchronous thread; shutdown waits for in-flight handler work to finish, even after Procrastinate's graceful timeout. On Windows use Ctrl+C for cooperative shutdown; Python does not install Procrastinate signal handlers there, so do not assume SIGTERM drains active work. Scheduling is currently an internal service API; no public scheduling route or COD-363 metric handler is enabled. Migration `0005_durable_jobs` installs the pinned Procrastinate schema snapshot and permanent BipMe receipts. The runner schema snapshot is fixed at Procrastinate 3.10.0 and is not dynamically upgraded by Alembic. Consent-generation invalidation is deferred to COD-363. Procrastinate startup/prune lifecycle behavior and sanitization of its own exception logs have not been verified beyond BipMe receipt/outcome logging.

The PostgreSQL delay/restart integration test first confirms that a future job is not claimed, then manually clears its `scheduled_at` value to make it eligible. It creates a fresh runtime against the same database in the same test process; it does not wait for wall-clock eligibility or kill/restart a subprocess.

Check `http://127.0.0.1:8000/api/health`. Migration `0001_enable_vector` creates the pgvector extension; `0002_canonical_persistence` creates canonical creator/post records; `0003_private_auth_sessions` adds revocable sessions and short-lived OAuth transactions. COD-346 provides `POST /api/auth/private/session`, `GET /api/auth/session`, `POST /api/auth/logout`, `GET /api/auth/x/authorize`, `GET /api/auth/x/callback`, and authenticated X status/refresh/disconnect routes. Protected endpoints require a configured existing `BIPME_CREATOR_ID`; private sign-in additionally requires a high-entropy `BIPME_PRIVATE_LOGIN_SECRET` (at least 32 bytes). For local OAuth callback cookies, use the same loopback host in `BIPME_APP_ORIGIN` and the registered callback URI. X OAuth stays disabled unless explicitly enabled after COD-344's access and rights checks.

X OAuth also requires operator-supplied `BIPME_X_IDENTITY_READ_ESTIMATED_COST_USD` and `BIPME_X_DAILY_COST_LIMIT_USD` values from verified current pricing. The callback reserves the configured worst-case identity lookup cost in `api_usage_ledger` before calling X and fails closed at the UTC daily ceiling. Reservations stay pending until reconciled against X account usage. Keep OAuth disabled until COD-344's account-specific access/rights gates and current pricing are confirmed.

COD-347 adds a mockable creator-history read adapter over that same `api_usage_ledger`. It reserves the maximum configured page/retry envelope before each HTTP request, then records response count separately from the still-estimated cost until usage reconciliation. Total, daily, operation and import ceilings and a current, source-referenced price must be supplied explicitly; the adapter defaults disabled and has no live API route. The only implemented endpoint is the creator-owned timeline; niche discovery remains unavailable pending COD-375/COD-344. Do not enable real reads until account access, usage rights, billable fields/pricing and limits have been verified.

The PostgreSQL-backed API CI job starts `pgvector/pgvector:pg17` and sets `BIPME_TEST_DATABASE_URL`; migration integration tests create an isolated schema, apply the full chain, downgrade to `0001_enable_vector`, verify the extension remains, then upgrade again. To run those tests locally, start the Compose database and run:

```bash
export BIPME_TEST_DATABASE_URL='postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
cd apps/api
uv run pytest -q tests/test_persistence_postgres.py
```

The test URL must point at a disposable development database; tests create and drop an isolated schema inside it.

## Start the web app

In a separate terminal:

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

Open the Vite URL printed by the process. The Vite development proxy forwards `/api` calls to `http://127.0.0.1:8000`. The web UI is currently only a development shell with health status.

## Verify changes

Run each block **from the repository root** (or in a separate terminal). The first `cd` changes your working directory.

API:

```bash
cd apps/api
uv run ruff check src tests alembic
uv run ruff format --check src tests alembic
uv run mypy src
uv run pytest -q
```

Web:

```bash
cd apps/web
pnpm lint
pnpm typecheck
pnpm build
pnpm format:check
```

`pnpm format:check` is available locally but is **not currently a CI step**. Add browser E2E tests when actual user flows are introduced. `api-checks`, `web-checks` and `workspace-checks` are the three existing GitHub Actions jobs.

## OpenAPI and Web handoff

FastAPI owns the API contract. Regenerate the committed OpenAPI artifact from the app when routes or schemas change:

```bash
cd apps/api
uv run python -c 'import json; from bipme.api.app import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))' > openapi.json
```

`tests/test_analysis_api.py` checks that the artifact matches the generated schema. COD-356 and COD-360 should generate their client types from `apps/api/openapi.json`; do not hand-copy response interfaces. Draft text is fingerprinted but is not stored. Reusing an `Idempotency-Key` with the same creator and canonical input replays the original immutable assessment; a different input returns 409.

The Web client contract is generated from that checked-in artifact with pinned `openapi-typescript`, `openapi-fetch`, MSW and Vitest versions. From `apps/web`, run:

```bash
pnpm generate:api
pnpm check:api
pnpm test
```

`generate:api` writes `src/api/generated/schema.d.ts`; `check:api` regenerates into a temporary directory and fails when the checked-in output is stale. Neither command starts the API or makes network requests. `src/api/client.ts` is the reusable same-origin client: it sends cookies, retains the server-provided CSRF token only in memory, accepts `AbortSignal` for cancellable reads, maps structured API errors to `ApiRequestError`, and preserves HTTP status, API codes, validation details and rate-limit headers. Synthetic MSW handlers and fixtures live in `src/api/mocks.ts` and `src/api/fixtures.ts`; they must not be treated as production creator data.

COD-378 adds typed `/api/v1/creators/me/profile`, `/data-permissions`, `/report`, `/report/latest` and `/reports/{id}` contracts. Profile updates append revisions; report generation is draft-free and replays by creator-scoped `Idempotency-Key`. `data_sources` currently accepts only explicitly opted-in personal history; the server-side X-history policy gate requires both `BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED=true` and a valid `BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT` timestamp, niche discovery is unavailable, and synthesis is disabled. The latest report response exposes coverage, source freshness, processing permission snapshot and limitations so Web can render insufficient/partial states without inventing data. Regenerate `openapi.json` when these schemas change.

The GitHub Actions workflow runs on PRs targeting `main`; it uses locked Python installation and frozen pnpm installation. The API job's PostgreSQL service is pgvector-enabled so persistence tests exercise real PostgreSQL constraints, vector queries and Alembic upgrades/downgrades. No CI job should call live X endpoints.

## Repository workflow

1. Read the relevant file(s), applicable `AGENTS.md`, and only the necessary documentation for the task.
2. Confirm task scope and acceptance criteria; create a **short-lived branch from current `main`**.
3. Implement a cohesive change with corresponding tests. For features, update their documented behavior when it changes.
4. Run targeted checks and relevant full checks; review the diff for accidental secrets, data leakage and unrelated changes.
5. Open a PR to `main` with scope, verification, limitations and risk notes. Resolve real review findings and rerun CI on the latest commit.
6. **Do not merge without explicit authorization.** Prefer squash merges. Delete merged branches when GitHub configuration allows.

No permanent `dev`/`beta` branch is needed for the one-account phase. GitHub ruleset and merge preferences must be verified in the **repository settings**; this guide alone does not enforce them.

## Database and API changes

- All persistent schema changes use SQLAlchemy models plus an Alembic migration; check forward and downgrade behavior.
- Keep the X payload adapter separate from canonical application entities.
- Maintain FastAPI OpenAPI as the authoritative API contract; generate TypeScript API types rather than manually duplicating contracts.
- Add Python dependencies via `uv add` (or `uv add --dev`) and frontend dependencies via `pnpm add`, then commit resolver-produced lockfile changes.
- Do not add network services, queues or separate databases without a demonstrated need.

## Testing live X integration

No real X API credentials are required for routine local/CI scaffold tests. Before testing real OAuth or ingesting post data, see [Security](security.md); verify developer console permissions, enforce an API budget, and use a small initial read. Do not commit screenshots, logs or fixtures containing tokens or private creator data.

## Troubleshooting

- **API unavailable in web shell:** confirm the FastAPI process runs on port 8000 and the Vite proxy is active.
- **Migration cannot connect:** check `docker compose ps`, the host port, and exported `BIPME_DATABASE_URL`.
- **Dependency mismatch:** regenerate locks using the real package managers; do not edit lockfiles manually.
- **Type/lint failures:** run the exact job commands above and fix underlying code, not just CI configuration.
