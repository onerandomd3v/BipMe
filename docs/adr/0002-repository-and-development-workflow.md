# ADR-0002: Monorepo and Development Workflow

- **Status:** Accepted
- **Date:** 2026-11-06
- **Project:** BipMe
- **Scope:** Repository foundation for the initial one-account experimental product
- **Relationship:** Complements ADR-0001; it does not supersede the accepted application stack.

## Context

BipMe combines a Python API/worker/intelligence engine and a React web client. The first milestone is correctness and reproducibility using one authorized X account. We want one cohesive repository, small reviewable PRs, and predictable local/CI workflows without premature scaling and operations complexity.

## Decision: a single monorepo

```text
BipMe/
  apps/
    api/
      src/bipme/
        api/                 # HTTP routes and dependencies
        auth/                # private app session and X OAuth integration
        integrations/x/      # official X API adapter
        creators/            # creator state and history
        posts/               # canonical posts and metric observations
        intelligence/        # profiles, retrieval, baselines and outlook
        jobs/                # background job entrypoint/handlers
        persistence/         # SQLAlchemy models and connection management
        core/                # settings, logging and shared internal utilities
      tests/
      alembic/
      pyproject.toml
      uv.lock
      .python-version
    web/
      src/
      package.json
      pnpm-lock.yaml
      tsconfig.json
      vite.config.ts
  docs/
    adr/
    research/
  infra/
  .github/workflows/
  compose.yaml
  AGENTS.md
  README.md
```

API and worker are separate **process entrypoints**, not separate services or repositories. `src/bipme/intelligence/` is a local Python package with no network boundary. PostgreSQL + pgvector is the one persistent database; no independent vector DB or Redis for initial development. Avoid adopting Nx/Turborepo because they do not solve a current requirement.

## Tooling decisions

- Python **3.13**, managed using **uv**; version constrained in `pyproject.toml` and `.python-version`.
- Node.js **24**, **pnpm** for the web app; use `packageManager` in `apps/web/package.json`.
- Commit both lockfiles (`apps/api/uv.lock` and `apps/web/pnpm-lock.yaml`) after generating them with package tooling. Do not handcraft or fabricate dependency lockfiles.
- Python: **Ruff** for lint and formatting, a type checker (start with **mypy**), and **pytest**; strict typing for app-facing code.
- Web: TypeScript in strict mode, **ESLint**, **Prettier**, **Vitest** for unit-level checks as relevant, and **Playwright** for core E2E flows.
- **FastAPI OpenAPI is authoritative** for the API contract. Generate TypeScript API types with a codegen tool; do not maintain duplicate handwritten schemas.
- Local development uses **Docker Compose** for required infrastructure and reproducible services. Development binaries may also run on the host using the documented tooling.
- Document critical development decisions with ADRs and feature behavior in short versioned specifications; keep an `AGENTS.md` for coding-agent project rules.

## Git workflow

- `main` is the protected integration branch.
- Use short-lived `feature/*`, `fix/*`, `chore/*`, and `docs/*` branches and **PRs for every change**.
- Require passing CI checks, resolved review conversations, up-to-date PR branches, and linear history; allow **0 required human approvals** while working solo.
- Block force pushes and branch deletion of `main`; no bypass permissions when ruleset enforcement is supported.
- Prefer squash merge and automatically delete merged PR branches.
- No permanent `dev` or `beta` branch until there is a demonstrated need for separate integration/deployment tracks.
- Establish exact CI job names (`api-checks`, `web-checks`, `workspace-checks`), get them reporting successfully, **then** configure required checks. Never invent the check identifiers before they are observed.
- GitHub rulesets and merge settings must be applied separately through authorized repository settings. ADR approval by itself does not mean those remote settings have changed.

## Authentication and initial access

- First product flow uses **X OAuth 2.0 Authorization Code + PKCE** for sign-in and X data authorization; use secure server-side application sessions.
- Initially restrict use to an explicitly configured allowed X account ID. Validate identity server-side before granting application access, not by username display or client-side checks.
- Read-only X permissions plus offline access as needed; encrypt OAuth tokens at rest, never log secrets, protect cookies with secure/HttpOnly/SameSite settings, and revoke credentials on disconnect.
- A public repository must contain **no** credentials, real X payloads, private creator datasets, or committed environment files. Keep `.env.example` with placeholders only.

## Infrastructure and testing

- Keep Python API and worker in one codebase; background jobs may share the application's database session and domain logic.
- Database schema managed through Alembic migrations; do not create production schema opportunistically at runtime.
- Initial required CI jobs: `api-checks` (Ruff, typing, pytest), `web-checks` (lint, typecheck, tests/build), `workspace-checks` (repository hygiene and structural validation). E2E can be a separate job when a working user journey exists.
- Do not make live X API requests from PR CI. Use mocked API payloads and local database fixtures.
- Set API call budget/usage controls before enabling any real X data ingestion.

## Deferred decisions

The exact pretrained embedding checkpoint, the PostgreSQL-backed job runner library (evaluate Procrastinate), external deployment host, X developer account entitlements and billing limits, and formal retention/deletion policy will be finalized with targeted proofs of concept. These do not block the **repository scaffold**, but the X API and data-policy checks block live integration.

## Execution order

1. Review/merge ADR-0001 and ADR-0002 separately.
2. Scaffold applications, local DB, conventions, and automated CI in a small PR.
3. Verify CI check names and then configure GitHub protections.
4. Conduct X OAuth/history-read feasibility testing with explicit cost ceilings.
5. Build and validate the intelligence spine before expanding features.

## Non-goals

Do not introduce multi-tenancy, public launch workflows, payments, high-availability clusters, microservices, elaborate dashboards or platform integrations beyond X during the initial experiment.
