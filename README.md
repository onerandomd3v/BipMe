# BipMe

**Creator Distribution Intelligence**

BipMe is a creator distribution-intelligence platform that helps creators make better-informed content decisions using insights from their historical performance, so they can understand what works, discover opportunities worth testing, and improve their approach to reaching their audience.

Starting with X, BipMe aims to connect historical content patterns, evidence-backed draft guidance, and real post-publication outcomes.

**Distribution is the goal. Better content decisions are the method.** BipMe does not guarantee reach or virality.

## How it works

1. **Understand:** Find patterns in eligible historical posts and available metrics.
2. **Evaluate:** Compare a new draft with relevant prior content.
3. **Improve:** Consider evidence-linked observations and ideas worth testing.
4. **Experiment:** Publish manually and optionally record a testable hypothesis.
5. **Learn:** Review real outcomes and use them to inform future decisions.

These steps describe the intended product workflow, not a claim that all features are already implemented.

## Stack

- **API & intelligence:** Python 3.13, FastAPI, SQLAlchemy, Alembic; deterministic post features and CPU-first text embeddings
- **Web:** React 19, TypeScript, Vite
- **Database:** PostgreSQL, pgvector
- **Development:** uv, Node.js 24, pnpm 10, Docker Compose, GitHub Actions

## Repository layout

```text
apps/api/       API, intelligence modules and persistence
apps/web/       Web application
docs/           Product, architecture, development and security guides
infra/          Infrastructure notes
compose.yaml    Local PostgreSQL/pgvector
AGENTS.md       Instructions for coding agents
```

## Quick start

Requires Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 24, pnpm 10 and Docker Compose.

From the repository root, start the local database:

```bash
docker compose up -d --wait db
```

Set `BIPME_DATABASE_URL` in the process environment (the initial Alembic setup does not automatically load `.env`):

**Bash (Linux/macOS)**

```bash
export BIPME_DATABASE_URL='postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
```

**PowerShell (Windows)**

```powershell
$env:BIPME_DATABASE_URL = 'postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
```

Start the API:

```bash
cd apps/api
uv sync --locked --group dev
uv run alembic upgrade head
uv run uvicorn bipme.api.app:app --reload
```

In a separate terminal, start the web app:

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

Open the Vite URL shown in the terminal. See the [development guide](docs/development.md) for tests, troubleshooting and the PR workflow.

## Documentation

- [Product](docs/product.md)
- [Architecture](docs/architecture.md)
- [Development](docs/development.md)
- [Security & X data policies](docs/security.md)
- [Research](docs/research/README.md)

Contributors and coding agents should read [AGENTS.md](AGENTS.md) and any scoped app instructions.

## Status

BipMe is in active development. V1 is a **private X-first experiment with one authorized account**, not a public launch. The embedding and Post Profile foundations are implemented; X integration, historical ingestion, retrieval, creator-facing guidance and monitoring are still in progress.

Real X data may only be collected or processed after applicable permissions, data-use rights and spending safeguards are verified. Never commit credentials or private creator data.
