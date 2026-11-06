# API and intelligence package — agent instructions

Applies to `apps/api/**`. Root `../../AGENTS.md` applies too.

## Scope and tools

- API/worker/intelligence are modules in the **same Python package**, not independently deployed services.
- Python 3.13, uv, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/pgvector, Ruff, mypy and pytest.
- Read `../../docs/architecture.md` when changing module boundaries, models, retrieval or prediction. Read `../../docs/security.md` for X API, OAuth, tokens, logging or costs. Consult relevant `../../docs/research/` source when implementing intelligence.
- Add Python dependencies using uv and commit resolver-generated `uv.lock`. Keep `pyproject.toml` and lockfile aligned.

## Domain boundaries

- `src/bipme/api/`: HTTP routing, validated inputs/outputs and application dependency injection.
- `src/bipme/integrations/`: X OAuth/API adapter, retries, error mapping, payload normalization.
- `src/bipme/persistence/`: SQLAlchemy models, DB access and transactions; migrations live in `alembic/`.
- `src/bipme/intelligence/`: deterministic, independently testable Post Profiles, comparable retrieval, baseline and outlook algorithms.
- `src/bipme/jobs/`: background work with idempotent identifiers and real observation times, once the worker is implemented.
- Don't add fake placeholder modules solely because an early blueprint listed a possible module name.

## Hard invariants

- Store descriptive features separately from observed outcomes. Disallow look-ahead, target leakage and arbitrary weighted prediction bonuses.
- Similarity selects comparables; historical outcomes determine baseline ranges. No fake algorithm-score or confidence probabilities.
- Distinguish historical mature observations from standardized time-window snapshots; never backfill fabricated timestamps.
- Map X responses to provider-independent canonical records. Handle missing fields, pagination, 401/403/429 and partial failures.
- Before any live X reads: verified server-side account allowlist, real OAuth token protections, cost ceiling and explicit usage instrumentation.
- No X scraping, unapproved model training on X content, raw token logging or non-synthetic sensitive test fixtures.

## Commands

From `apps/api`:

```bash
uv sync --locked --group dev
uv run ruff check src tests alembic
uv run ruff format --check src tests alembic
uv run mypy src
uv run pytest -q
```

For migrations, supply `BIPME_DATABASE_URL` explicitly as described in `../../docs/development.md`; do not assume `.env` is auto-loaded.

## Before opening a PR

- Add tests for new routes, migrations, model transformations and failure states.
- Backtesting changes must prove time-order isolation and no data leakage.
- Update the appropriate living doc if the API contract, boundaries or behavior changed.
- Don't claim a planned feature is implemented without execution evidence.
