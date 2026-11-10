# Original BipMe research and design documents

These source specifications were produced in September 2026. They provide **detailed research and historical design rationale**; use the [root README](../../README.md) to find the current [product guide](../product.md), [architecture](../architecture.md), [development guide](../development.md), and [security controls](../security.md).

Current archive format, data-rights and metric-coverage findings are recorded in [X creator archive feasibility — COD-369](X_ARCHIVE_FEASIBILITY.md). The official archive help page does not specify a versioned post schema; no current creator export has been inspected.

The [COD-419 creator niche pilot preparation](COD-419_CREATOR_NICHE_PILOT.md) contains the gated cohort protocol, participant drafts, data mapping and execution checklist. Real recruitment and processing remain No-Go.

Current one-account V1 integration readiness and outstanding acceptance dependencies are recorded in [COD-368 V1 acceptance readiness](COD-368_V1_ACCEPTANCE_READINESS.md). This report distinguishes synthetic contract coverage from real-account and end-to-end verification.

1. [X Discovery & Distribution MVP](X_DISCOVERY_DISTRIBUTION_MVP.md) — original thesis and X-first scope.
2. [X Distribution Intelligence Research Findings](X_DISTRIBUTION_INTELLIGENCE_RESEARCH_FINDINGS.md) — platform architecture, exposed data, limits and API/policy research.
3. [X Distribution Outlook V1 Design](X_DISTRIBUTION_OUTLOOK_V1_DESIGN.md) — Post Profiles, comparable retrieval, baselines, prediction and evaluation.
4. [X Distribution Intelligence Implementation Blueprint](X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md) — original detailed engineering plan and test ideas.

## How to use these sources

- Read the relevant portion when implementing or validating creator intelligence, not all four files for every minor task.
- The original blueprint contains a **historical recommended TypeScript/NestJS stack**. The accepted application now uses Python/FastAPI; see [Architecture](../architecture.md).
- Example weights, confidence values, scoring outputs and UX numbers are hypotheses or **illustrations** until validated with actual creator data.
- Recheck X API fields, prices, access tiers, licenses and policies against current official information. These documents are not perpetual live references.
- When research conflicts with current code or an approved living specification, determine why and update the appropriate current guide; don't silently override it.

The original content is preserved for traceability rather than rewritten to make outdated assumptions appear current.
