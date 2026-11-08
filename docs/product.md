# BipMe — Product guide

**Status:** Active design and development. Application features described as planned are **not yet implemented**.

## Product definition

BipMe is a **creator distribution-intelligence platform** that helps creators make better-informed content decisions using insights from their historical performance, so they can understand what works, discover opportunities worth testing, and improve their approach to reaching their audience.

**Distribution is the goal; better content decisions are the method.** BipMe uses eligible historical posts and observed metrics as evidence, not as a guarantee of future reach. Comparable-post analysis and Distribution Outlook support creator decisions rather than promise to predict the next viral post.

The product is **not** an X algorithm cracker, a universal content-quality score, a viral guarantee, an automated publisher, or a generic AI writing assistant.

## Creator value and learning loop

The core creator experience is **Understand → Evaluate → Improve → Experiment → Learn**: distinguish recurring historical patterns from isolated viral outliers; assess a draft or content idea against eligible comparables; receive one or two **evidence-linked observations and a testable next action** when justified; publish manually; and review whether the actual outcome supports, contradicts or leaves the original hypothesis inconclusive.

Creators should be able to:

- Recognize approaches that repeatedly performed better or worse, while flagging single viral hits and sparse samples instead of treating them as a repeatable formula.
- Evaluate a draft using inspectable, relevant historical examples rather than generic advice.
- Consider a concrete, optional next action (repeat, revise or test a new format) and a simple hypothesis, without being told what they must publish.
- See what happened after publishing and whether the original assessment and testable hypothesis were supported, contradicted or inconclusive.
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
5. **Make a decision, not just a forecast.** Show matched evidence, recurring pattern vs possible outlier, evidence strength and **one or two specific observations with an optional testable action**. Provide a creator-relative Distribution Outlook **only when sufficiently supported**; otherwise explain why no reliable range is available.
6. **Record a lightweight experiment.** The creator may choose one question or hypothesis to test for this draft (for example, whether a storytelling format produces stronger conversation engagement). This is an optional field on the existing draft/outlook record, **not** a separate experiment-management system or A/B test.
7. **Publish manually on X.** Let the creator attach the published post URL/ID and preserve the original versioned assessment/hypothesis; no automatic posting permission.
8. **Measure and learn.** Capture actual metrics at observed timestamps, compare only valid equal-age histories, and label the hypothesis as *supported, contradicted or inconclusive* only to the extent observational evidence permits. Evaluate forecast quality via time-respecting backtests when possible; do not imply causal proof or uplift.

## Output contract

BipMe's result should distinguish:

- **Observed:** Post content, timestamps, X-provided metrics and historical records.
- **Inferred:** Topic/format fit, matched performance range and evidence strength.
- **Evidence-backed decision guidance:** One or two concise observations connected to comparable IDs, calculations and data limitations; one optional *suggested experiment/next action* clearly labeled as a hypothesis, never a guaranteed improvement. Deterministic rules suffice in V1.
- **Unknown:** Exact X ranking score, why any particular post went viral, who saw each candidate, private recommendation decisions and unobserved early-history trajectories.

Use wording such as **Expected relative reach: top 25–40% of comparable historical posts; Evidence: Moderate** only when backed by real calculations and eligible data. Do not use invented figures in actual product responses.

Evidence strength is **High / Moderate / Low / Insufficient**, not an uncalibrated percentage. If data is sparse, private metrics are missing, or a metric window was missed, explicitly display the limitation.

## Intelligence behaviors

- The **Creator Baseline** represents robust performance distributions and consistency across multiple eligible posts, flags extreme outliers, and reports how many observations support a pattern; it is not just an average or a top-post list.
- **Comparable Retrieval** uses eligible earlier posts with similar content, format, topology, intent, creator era and other known context; its weights are versioned and subject to backtesting.
- **Decision guidance** distinguishes a repeatable association from a single successful post, supplies traceable observations and an optional experiment, and abstains when evidence is insufficient. **Distribution Outlook** is secondary: where supported, it may show robust creator-relative ranges for observed reach/conversation/redistribution metrics, not a viral score or guaranteed outcome.
- **Monitoring** uses real observation timestamps, and never presents mature cumulative historical metrics as if they were 5-minute/1-hour outcomes.
- **Postmortem** links draft → chosen hypothesis → manually published post → actual observed outcomes, showing whether evidence supports/contradicts the hypothesis or is inconclusive. It preserves the original outlook and evaluates errors without claiming BipMe caused uplift.

## Initial delivery sequence

1. **Foundation (implemented):** monorepo, FastAPI health endpoint, React shell, PostgreSQL/pgvector, Alembic foundation, lockfiles, and CI.
2. **X feasibility (next):** private sign-in, secure OAuth connection, explicit spending limits, small live read, mapping and persistence.
3. **Intelligence spine:** canonical posts, Post Profiles, embeddings, comparable retrieval, baseline engine, draft analysis.
4. **Feedback loop:** attach published post, delayed metric snapshots, matched trajectories, postmortem and evaluation.
5. **Validation:** run the one-account journey end to end, confirm evidence integrity and evaluate accuracy.

Each phase is a deliverable, not a promise that its features are already running.

## V1 success gate (hypothesis, not demonstrated value)

For one authorized account, a creator should be able to: inspect at least one eligible historical pattern and see its supporting posts/sample limitations; evaluate a draft; understand a concrete evidence-backed next action or a clear **insufficient evidence** state; optionally record a lightweight experiment; link the manual publication; and compare its actual result with the pre-publication assessment. No assertion of improved reach or willingness to pay is made. Compare this experience with the creator's normal native-analytics workflow after V1 ships; formal pre-launch interviews are not a launch blocker.

Historical data may later come from a creator-exported X archive **if** import format, provenance, permissions and metric coverage can be verified; archive import is an optional ingestion alternative, **not** an assumed V1 dependency or a policy bypass.

## Deferred

Multi-platform support, follower graphs, auto-posting or scheduling, proprietary trained models, multi-user launch, monetization, complex deployments, a standalone experiment dashboard, generative rewriting, competitor crawling and a promised viral-score predictor.

## Source details

See [X-first MVP](research/X_DISCOVERY_DISTRIBUTION_MVP.md), [Outlook design](research/X_DISTRIBUTION_OUTLOOK_V1_DESIGN.md) and [implementation blueprint](research/X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md) for detailed earlier specification.
