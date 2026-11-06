# BipMe — repository agent instructions

These instructions apply to the entire repo. For files under `apps/api/` or `apps/web/`, follow that application's **nested `AGENTS.md`** as well. `AGENTS.md` is for durable working rules, **not a copy of every product specification**.

## What this project is

BipMe is a creator-specific X distribution-intelligence product. The first milestone is one authorized X account using real history to validate matched historical baselines, evidence-backed Distribution Outlooks and post-publish evaluation. It is **not** a social scheduler, automatic publisher, viral-guarantee tool, or public multi-user launch.

The current application is still a **scaffold**. Do not claim OAuth, history ingestion or predictions already work.

## Where to find context

| Task | Read |
| --- | --- |
| Product scope or UX | `docs/product.md` |
| System architecture, database and intelligence logic | `docs/architecture.md` |
| Setup, checks, branches and PR workflow | `docs/development.md` |
| High-risk correctness constraints | `docs/important.md` |
| OAuth, tokens, X API costs, privacy, third-party processing | `docs/security.md` |
| Detailed comparable-post methodology or original research | `docs/research/README.md` and its relevant source file |

Read **only the documents relevant to the requested change**. Historical `docs/adr/` records explain past decisions; the living docs above describe the current implementation contract.

## Engineering rules

- Respect the one-repo layout: `apps/api` (Python/FastAPI + in-process intelligence and future worker), `apps/web` (React/Vite), PostgreSQL + pgvector.
- Use uv for Python and pnpm for web. Commit **genuine** generated lockfiles; never hand-edit/fabricate them.
- Keep SQLAlchemy and Alembic changes aligned. FastAPI OpenAPI is the authoritative API definition for generated web API types.
- Implement only agreed scope; keep changes focused, tested and reviewable. Do not introduce microservices, new platforms or elaborate scaling infrastructure by default.
- Preserve source-of-truth boundaries: features separate from observed outcomes; no look-ahead in predictions/backtests; real observation timestamps; explicit data gaps.
- Never represent uncalibrated confidence as a probability or X's internal ranking as known.
- No committed secrets or private creator datasets, no X API calls in PR CI, and **no live X data ingestion before hard cost limits and relevant protections exist**.

## Workflow

1. Inspect current code and relevant scoped instructions.
2. Create a short-lived branch from current `main`; make changes with tests.
3. Run relevant local checks and review the diff; update living docs when behavior changes.
4. Open a PR against `main`; address actionable review comments and confirm CI results on the latest head.
5. **Never merge, force-push, delete protected branches or deploy without explicit user authorization.**

Existing GitHub CI jobs are `api-checks`, `web-checks`, and `workspace-checks`. The existence of an ADR or workflow file does **not** prove remote branch protection settings are configured.
