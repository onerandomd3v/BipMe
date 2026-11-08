# BipMe — Development guide

**Status:** Commands and checks reflect the current scaffold. X authentication, data ingestion, background jobs and intelligence features are still planned.

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

The scaffold's Alembic configuration reads `BIPME_DATABASE_URL` **from the process environment**. Merely copying `.env.example` does **not** currently auto-load it.

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

Check `http://127.0.0.1:8000/api/health`. Migration `0001_enable_vector` creates the pgvector extension; `0002_canonical_persistence` creates the V1 canonical creator/post, profile, embedding, outcome, connection, usage and immutable assessment records.

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
