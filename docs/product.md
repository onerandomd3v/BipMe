# BipMe — Product guide

**Status:** Active design and development. Application features described as planned are **not yet implemented**.

## Product definition

BipMe is a **creator-specific distribution-intelligence product**, starting with X. It helps a creator understand how a draft might perform **relative to their own comparable posts**, shows the evidence for that outlook, then measures what happened after publication.

The product is **not** an X algorithm cracker, a universal content-quality score, a viral guarantee, an automated publisher, or a generic AI writing assistant.

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
