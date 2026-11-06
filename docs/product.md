# BipMe — Product guide

**Status:** Active design and development. Application features described as planned are **not yet implemented**.

## Product definition

BipMe is a **creator-specific distribution-intelligence product**, starting with X. It helps creators understand what has worked for their content, make better-informed publishing decisions, and learn from how their posts actually perform. It compares new drafts with relevant posts from the creator's own history, explains the supporting evidence, and evaluates original predictions against observed outcomes.

The product is **not** an X algorithm cracker, a universal content-quality score, a viral guarantee, an automated publisher, or a generic AI writing assistant.

## Creator value and learning loop

The core creator experience is **Understand → Evaluate → Improve → Experiment → Learn**: examine historical performance patterns; compare a new draft with relevant prior posts; offer one or two specific, evidence-linked observations when justified; let the creator revise or publish a new idea; and use actual results to inform future comparisons.

Creators should be able to:

- Recognize which historical content patterns have tended to perform better or worse for their own audience.
- Evaluate a draft using inspectable, relevant historical examples rather than generic advice.
- Consider evidence-backed revisions or new experiments without being told what they must publish.
- See what actually happened after publishing and whether the original outlook held up.
- Discover themes and approaches worth exploring over time, without expecting a guaranteed formula.

These are intended **product benefits**, not proven improvements in reach or evidence of causation. Historical associations cannot identify X's private ranking decisions or establish why any specific post was distributed.

## Initial scope

- One authorized X account, initially the maintainer's own account.
- Read-focused X integration, with minimal authorized permissions.
- Real historical post data and creator-owned metrics **only when available and permitted**.
- A private experimental workflow; no public signup, payment system, multi-tenancy or scalability targets yet.

## Core creator journey (planned)

1. **Sign in and connect X.** Use OAuth 2.0 Authorization Code Flow with PKCE. Permit the configured X account ID only, verified on the server.
2. **Build a baseline.** Import a cost-bounded portion of the creator's history and capture creator state; normalize to canonical posts and descriptive profiles.
3. **Analyze a draft.** Extract semantic, structural, topical, format and intent features without looking at the draft's future outcome.
4. **Find comparable posts.** Filter and rank prior posts from the same creator; preserve evidence and exclusions.
5. **Generate a Distribution Outlook.** Estimate a **range** of creator-relative performance and show comparable historical posts, strengths, limitations, and an evidence-strength label.
6. **Publish manually on X.** Let the creator attach the published post URL/ID; no automatic posting permission.
7. **Measure actual outcomes.** Capture metrics at observation windows, compare with valid same-age historical snapshots when available, and produce a postmortem.
8. **Evaluate predictions.** Use recorded outcomes and time-respecting backtests to identify where estimates are reliable or weak.

## Output contract

BipMe's result should distinguish:

- **Observed:** Post content, timestamps, X-provided metrics and historical records.
- **Inferred:** Topic/format fit, matched performance range and evidence strength.
- **Evidence-backed explanation:** One or two concise observations connected to the selected comparables and calculations, or an explicit explanation that there is insufficient evidence. V1 can generate these from deterministic logic without a generative LLM.
- **Unknown:** Exact X ranking score, who saw each candidate, private recommendation decisions and unobserved early-history trajectories.

Use wording such as **Expected relative reach: top 25–40% of comparable historical posts; Evidence: Moderate** only when backed by real calculations and eligible data. Do not use invented figures in actual product responses.

Evidence strength is **High / Moderate / Low / Insufficient**, not an uncalibrated percentage. If data is sparse, private metrics are missing, or a metric window was missed, explicitly display the limitation.

## Intelligence behaviors

- The **Creator Baseline** represents performance distributions, not just averages.
- **Comparable Retrieval** uses eligible earlier posts with similar content, format, topology, intent, creator era and other known context; its weights are versioned and subject to backtesting.
- **Distribution Outlook** uses robust weighted historical outcomes to estimate reach and, where supported, conversation, redistribution and conversion.
- **Monitoring** uses real observation timestamps, and never presents mature cumulative historical metrics as if they were 5-minute/1-hour outcomes.
- **Postmortem** compares original predictions with actual outcomes and evaluates error; it does **not** imply BipMe caused any uplift.

## Initial delivery sequence

1. **Foundation (implemented):** monorepo, FastAPI health endpoint, React shell, PostgreSQL/pgvector, Alembic foundation, lockfiles, and CI.
2. **X feasibility (next):** private sign-in, secure OAuth connection, explicit spending limits, small live read, mapping and persistence.
3. **Intelligence spine:** canonical posts, Post Profiles, embeddings, comparable retrieval, baseline engine, draft analysis.
4. **Feedback loop:** attach published post, delayed metric snapshots, matched trajectories, postmortem and evaluation.
5. **Validation:** run the one-account journey end to end, confirm evidence integrity and evaluate accuracy.

Each phase is a deliverable, not a promise that its features are already running.

## Deferred

Multi-platform support, follower graphs, auto-posting or scheduling, proprietary trained models, multi-user launch, monetization and complex deployments.

## Source details

See [X-first MVP](research/X_DISCOVERY_DISTRIBUTION_MVP.md), [Outlook design](research/X_DISTRIBUTION_OUTLOOK_V1_DESIGN.md) and [implementation blueprint](research/X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md) for detailed earlier specification.
