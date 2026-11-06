# BipMe documentation

These guides describe the **current intended product and its implementation**. The four September research documents are preserved under `research/` as detailed source material. Architecture decision records under `adr/` are historical records, not a substitute for current developer documentation.

| Document | Read it when |
| --- | --- |
| [Product](product.md) | Defining user behavior, scope, acceptance criteria or feature priority |
| [Architecture](architecture.md) | Changing boundaries, database design, intelligence logic or APIs |
| [Development](development.md) | Setting up, testing, working with branches or preparing a PR |
| [Important](important.md) | Checking high-risk product invariants and known limitations |
| [Security](security.md) | Working on X OAuth, tokens, account access, logging, deletion, API billing or third-party models |
| [Original research](research/README.md) | Working on creator baselines, retrieval, metrics, X algorithm references or historical rationale |
| [Architecture records](adr/) | Understanding why an earlier decision was made |

## Documentation ownership

- Root `README.md`: quick introduction and working setup.
- Root `AGENTS.md`: short repository-wide coding-agent instructions.
- `apps/api/AGENTS.md` and `apps/web/AGENTS.md`: rules specific to each application.
- These `docs/*.md` files: the current human-readable product and technical contracts.
- `docs/research/`: original detailed source designs; API and policy statements in them may have aged.
- `docs/adr/`: records of previous decisions; do not generate new ADRs for routine implementation.

When implementing a change, read the directly relevant guide, not every document. If behavior, architecture or commands change, update the **corresponding guide in the same PR**. Do not create parallel descriptions that drift.
