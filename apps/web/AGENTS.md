# Web application — agent instructions

Applies to `apps/web/**`. Root `../../AGENTS.md` applies too.

## Stack and source of truth

- React 19, TypeScript in strict mode, Vite, pnpm 10, ESLint and Prettier.
- Read `../../docs/product.md` for UX and feature intent, `../../docs/architecture.md` for client/API boundaries, and `../../docs/security.md` for authentication or sensitive display.
- FastAPI OpenAPI is the API contract source. Generate and commit typed frontend bindings when the real endpoint integration is introduced; do not invent backend endpoints in the UI.
- Add packages through pnpm and commit resolver-generated `pnpm-lock.yaml`.

## Boundary rules

- The browser only calls the authenticated API. It must **never** connect directly to PostgreSQL or hold X access/refresh tokens.
- Authentication sessions use server-issued HttpOnly cookies; don't store provider credentials in localStorage or sessionStorage.
- Distinguish observed metrics, predictions, and unknown/unavailable metrics visually and semantically.
- For predictions show a creator-relative range, comparable evidence and evidence strength; don't imply guaranteed performance, causal uplift or internal X scores.
- Show loading, missing data, API errors, rate limits, stale observations and insufficient evidence as explicit states.
- The existing `/api/health` integration is a smoke test, not user authentication. Avoid showing future UI as if it already works.

## Commands

From `apps/web`:

```bash
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm build
pnpm format:check
```

`format:check` is available locally; it isn't currently a required CI step. Add Vitest and Playwright when meaningful unit/flow tests are implemented, not as empty placeholders.

## PR expectations

Keep views accessible (semantic elements, keyboard support, contrast), predictable, and typed. Test material UI state transitions. Update the product guide when behavior changes, and avoid introducing backend/server dependencies into client code.
