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
| Correctness constraints and data boundaries | `docs/architecture.md` and `docs/security.md` |
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

## Linear issue execution (Codex and human contributors)

- **Source of truth for implementation tasks:** [BipMe V1 project](https://linear.app/codeddevs/project/bipme-v1-distribution-intelligence-efa2574db806) in the **CodedDevs** Linear workspace (issues `COD-344` onward). Do not turn existing issues into separate Markdown task plans by default.
- Before implementation, retrieve the requested issue **and its blocking dependencies** through an authorized Linear connector (for Codex CLI/IDE, the user can connect the Linear MCP server at `https://mcp.linear.app/mcp`). `AGENTS.md` does not itself grant access or configure authentication. If Linear is inaccessible, ask for the issue's full text; **never invent acceptance criteria**.
- Treat the issue's acceptance criteria, owned paths, dependencies and milestone as the task contract. Confirm blockers are complete before integrating; independent fixture/mock work may proceed without pretending downstream dependencies are ready.
- Use **one issue per focused branch/PR** (example: `cod-351-embedding-benchmark`), branched from the latest `main`. Include the Linear issue ID in the branch/PR title or body and link the issue.
- Respect the three workstream boundaries: **Platform & Data** owns X integration, authentication, SQLAlchemy/Alembic and published HTTP contracts; **Intelligence** owns `apps/api/src/bipme/intelligence/` and algorithm tests; **Web** owns `apps/web/` and generated-client integration. Coordinate shared data/OpenAPI changes with the owning lane first; do not silently modify another lane's files.
- If permitted to update Linear, move the issue to **In Progress** when beginning work; add the PR link and verification notes, then move to **In Review** when ready. Move to **Done** only after the PR is confirmed merged and acceptance criteria are satisfied. If write access is absent, report the intended status changes instead of claiming they happened.
- Do not assign issues to people, change milestones, bypass dependency blockers, merge PRs, or close issues unless explicitly authorized.
- Before marking work complete, run applicable checks, verify the diff and current CI, and summarize implementation, tests, limitations, and the remaining blocker/handoff in the Linear issue/PR.

## Workflow

1. Inspect current code and relevant scoped instructions.
2. Create a short-lived branch from current `main`; make changes with tests.
3. Run relevant local checks and review the diff; update living docs when behavior changes.
4. Open a PR against `main`; address actionable review comments and confirm CI results on the latest head.
5. **Never merge, force-push, delete protected branches or deploy without explicit user authorization.**

Existing GitHub CI jobs are `api-checks`, `web-checks`, and `workspace-checks`. The existence of an ADR or workflow file does **not** prove remote branch protection settings are configured.
