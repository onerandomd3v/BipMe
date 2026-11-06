# BipMe agent instructions

## Project direction

- BipMe is a creator-specific X distribution-intelligence product, not a hackathon-only prototype or a generic social scheduler.
- First test with one authorized X account; prioritize correctness, explainability, reproducibility, privacy, and API cost discipline.
- Follow the architecture ADRs and four research/design specifications before modifying prediction behavior.
- The Python intelligence engine stays inside `apps/api/src/bipme/intelligence/`, with no microservice boundary unless a new ADR justifies it.

## Engineering workflow

- Use small PRs; do not directly commit to `main` or merge without user authorization.
- Avoid broad refactors or unrelated scope expansion.
- Before changing code, inspect its current module, tests, and relevant specifications.
- Python: uv, Ruff, mypy, pytest. JavaScript: pnpm, strict TypeScript, ESLint, Prettier.
- FastAPI OpenAPI is the source of truth for API types; do not hand-maintain duplicate client contracts.
- Database changes use Alembic migrations. Maintain tests for edge cases and new behavior.
- Do not invent lockfiles: generate with uv/pnpm and commit the results.

## Intelligence invariants

- Select historical comparables using information available **before** their outcomes.
- Keep post features separate from performance outcomes to prevent leakage.
- Treat observations, inferences, and unknowable X ranking information separately.
- Display evidence strength, not fabricated calibrated probabilities.
- Do not train/fine-tune on X-derived data unless X's terms have been verified to permit that usage.
- Preserve observation timestamps and explicit missing/stale states.

## Security and costs

- Never commit secrets, real creator data, or OAuth tokens.
- Only official X APIs; test with mocks in CI, not live endpoints.
- Implement hard API spend ceilings before real history sync.
- Restrict initial private sign-in by verified X user ID on the server.
