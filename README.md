# BipMe

**BipMe** is a creator-specific distribution-intelligence product, starting with X. It learns from an account's own historical posts to provide evidence-backed predictions of relative distribution performance—and eventually checks those predictions against actual outcomes.

**Current status:** Early product implementation. The monorepo, API health endpoint, web shell, PostgreSQL/pgvector foundation, migrations and CI are scaffolded. **X login, historical ingestion, comparable retrieval, predictions and monitoring are not yet implemented.** Initial work targets a single authorized X account, not a public launch.

## Repository layout

```text
apps/api/     Python FastAPI API, intelligence modules, persistence and future worker
apps/web/     React 19 + TypeScript + Vite
docs/         Product, architecture, developer and safety documentation
docs/research/Original research, scoring design and implementation blueprint
docs/adr/     Historical architecture decision records
infra/        Infrastructure notes
compose.yaml  Local PostgreSQL/pgvector
AGENTS.md     Repository-wide instructions for coding agents
```

The API and web applications have additional scoped `AGENTS.md` instructions.

## Quick start

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 24, pnpm 10 and Docker Compose.

From repository root, start PostgreSQL:

```bash
docker compose up -d db
```

The initial Alembic setup expects `BIPME_DATABASE_URL` **in the environment** (not merely in an automatically loaded `.env` file).

For Bash:

```bash
export BIPME_DATABASE_URL='postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
```

Or for PowerShell:

```powershell
$env:BIPME_DATABASE_URL = 'postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
```

Start the API in one terminal:

```bash
cd apps/api
uv sync --locked --group dev
uv run alembic upgrade head
uv run uvicorn bipme.api.app:app --reload
```

Start the web app in another:

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

The Vite URL appears in the terminal. The shell displays API health at `/api/health`. See [Development](docs/development.md) for test commands, troubleshooting and Git workflow.

## Documentation

- [Documentation index](docs/README.md)
- [Product definition and milestone scope](docs/product.md)
- [Living system architecture](docs/architecture.md)
- [Local development and contribution workflow](docs/development.md)
- [Important engineering invariants](docs/important.md)
- [Security, privacy and X API cost controls](docs/security.md)
- [Original research and design specifications](docs/research/README.md)

Coding agents: read the applicable [root `AGENTS.md`](AGENTS.md) and the nested app-specific instructions for your working area.

## Current priorities

1. Verify X developer access, read-only OAuth and spending limits for the single test account.
2. Build canonical creator history ingestion and persisted post profiles.
3. Implement matched historical retrieval, creator baselines and draft Distribution Outlooks.
4. Add scheduled metric observations and prediction-versus-outcome evaluation.

No live X API credentials or creator-private data belong in this repository. Developer-console billing and current X policy must be checked before the first real integration.
