# BipMe — Product guide

**Status:** Active design and development. Application features described as planned are **not yet implemented**.

## Product definition

BipMe is an **attention-informed creator distribution-intelligence platform** that helps creators make better-informed content decisions using their own historical evidence and, where authorized and useful, clearly separated niche comparisons. It helps creators identify repeatable approaches associated with goal-relevant audience attention, understand limitations, choose experiments and learn from observed distribution outcomes.

**Distribution is the goal; better content decisions are the method.** The product considers whether content earns the *kind of attention the creator wants*, rather than optimizing raw likes or a fabricated virality score. BipMe uses eligible historical posts and observed metrics as evidence, not as a guarantee of future reach. Comparable-post analysis and Distribution Outlook support creator decisions rather than promise to predict the next viral post.

The product is **not** an X algorithm cracker, a universal content-quality score, a viral guarantee, an automated publisher, or a generic AI writing assistant.

## Definitive product journey: report first, draft second

**Decision (8 Nov 2026):** BipMe is proactive creator intelligence, **not primarily a paste-your-draft tool**. The **first user value is a personalized Creator Intelligence Report automatically assembled after secure onboarding and data availability, before the creator writes a new post**.

1. **Define goals:** The creator provides their niche, intended audience, desired outcomes (relevant replies, qualified interest, reach) and preferred style. Treat these as declared targets, not verified audience facts.
2. **Understand the creator:** Import a bounded owner-supplied X post archive if COD-369 finds format, rights and security viable, or use approved official X owner-history access. Identify personal content themes, available engagement/distribution evidence, baselines, outliers and missing metrics.
3. **Discover the niche independently:** Using **official X search APIs** under verified entitlement, data-use rights and a hard spend cap, search for relevant recent posts and discussions in the declared niche. Sample strong, typical and weak comparables across creators/periods rather than only 'viral' winners; account for search-selection bias, creator size, post age, format, missing impressions and prohibited processing. Archive upload does **not** replace niche discovery.
4. **Deliver the initial report without a draft:** Clearly separate **Your Content History** from **What's Happening in Your Niche**; show relevant observed posts/conversations, recurring attention associations, evidence quality and freshness, gaps relative to the creator's goals, and 1–3 testable content opportunities with supporting references and limitations. If no permitted niche access, output only an explicitly labeled **personal-only partial report**, not fabricated trends.
5. **Analyze a draft later:** When the creator submits an idea/draft, use their existing report/declared goals plus appropriately current personal and authorized niche comparables to suggest evidence-linked improvements/experiments. Do not promise reach or claim early engagement caused amplification. Preserve original assessments.
6. **Learn from actual posting:** After manual publication, attach the version-matched post and, where authorized API monitoring exists, gather real timestamped metrics; compare against pre-recorded hypotheses and update future reports, without retroactive prediction editing.

**V1 full-model acceptance:** Demonstrate the first report using both valid personal and *authorized official X niche-search evidence*, followed by a draft decision and post-publication learning. If niche search cannot be licensed, accessed or financed, a usable personal-only interim build may ship as a limited pilot, but it does not establish completion of the intended two-source product. All value and reach-improvement claims await creator testing.

**Engineering coordination:** COD-344 must extend feasibility to X official search/data-use/cost; COD-347 remains the bounded provider adapter, with discovery implementation separated where possible. COD-371 owns creator goal and report intelligence contracts. COD-359 becomes the report-first web home, COD-360 is draft-second UX, and COD-368 tests the new full user journey. Dedicated search, report-API and report-UI tasks should be created once Linear issue capacity is available; existing completed COD-345/350–354/358 code remains intact.

## Attention-informed, archive-first direction (approved refinement; validation pending)

BipMe's first question is **what content approaches appear to earn meaningful attention for this creator's goals and what is worth testing next?** We are not reverse-engineering a fixed X distribution gate. Early engagement may be associated with later exposure, but correlation does not show that engagement caused X to distribute a post.

**Creator goals:** Allow the creator to declare a niche, intended audience, priorities such as conversation, qualified interest or reach, and preferred style. These are self-declared preferences, not verified audience demographics.

**Two evidence pools:** (1) Personal posts and outcomes from the creator's own authorized history; (2) permissioned niche comparisons only after data-use rights and measurement quality are verified. Keep provenance, creator identity, metric definition, observation time, missingness and source-specific limitations. Do not silently combine personal and cross-creator distributions. Sample successful, typical and weak content rather than collecting only viral winners; otherwise survivorship bias prevents credible comparisons.

**Archive-first onboarding:** Prioritize feasibility of a recent creator-exported X archive as an alternative to paid API history reads. The account owner should supply only necessary post-history files. Verify actual export fields, archive format, parsing safety, platform processing terms, completeness and metric coverage before implementation. Archive snapshots cannot establish original impression trajectories, first-hour engagement or follower/non-follower reach without actual matching observations. Creator-owned archive ingestion is not permission for arbitrary AI training or cross-creator redistribution. Archive-only creators should eventually access BipMe through a secure private app session **without mandatory X OAuth**; an archive upload must never bypass authentication.

**Optional X connection:** X OAuth and API reads remain available for explicitly authorized refresh and time-stamped post-publication monitoring when approved, with enforceable per-operation and total cost caps. Monitoring is not required for archive-only descriptive analysis, and source-specific missing data must lead to explicit abstention rather than fabricated forecasts.

**V1 gates:** COD-369 validates archive structure/rights/metrics; COD-370 implements a safe post-only import if viable; COD-371 tests goal-aligned attention descriptors against baselines; COD-372 pilots carefully permissioned niche comparisons only after policy approval. COD-344 remains the X API/processing policy and cost gate. Treat all purported improvement in creator decisions or reach as hypotheses until evaluated on real permitted data.

## V1 delivery principle — ship working, improve iteratively

**Approved 8 November 2026:** BipMe V1 is a **working product release**, not a perfectly calibrated creator intelligence service. Ship the simplest safe report-first journey as soon as its required access/data rights and actual end-to-end workflow are proven. Do not hold launch for comparing multiple generative models, expensive evaluations, optional agent orchestration, fully automated report refresh, elaborate experiments or feature polish. Improve narrative accuracy and creator usefulness from observed feedback **after launch**.

For V1, use **one hosted generative model: `openai/gpt-oss-120b` via GroqCloud**, behind a model-agnostic and provider-agnostic internal adapter. Groq is the inference provider; GPT-OSS is the model. Groq free-tier usage is subject to organization-level request/token limits, so rate-limit handling and deterministic fallback are part of V1. No paid upgrade or external fallback without explicit approval. Its function is to explain precomputed evidence and propose clearly labeled hypotheses, not compute invented statistics. No mandatory model bake-off or challenger integration. Retain the deterministic template report if LLM use is unavailable or disallowed, and show personal-only partial status if approved X niche discovery is unavailable. Do not mislabel that partial mode as the completed two-source intended product. Model availability and rights for X-derived content must still be checked in the actual developer accounts.

**Minimum release quality:** the creator can securely onboard, inspect permitted history and source-backed initial report without supplying a draft, then access draft guidance and the intentionally scoped follow-on learning experience. Security, permission gates, source integrity, evidence attribution and cost ceilings are launch requirements; superior recommendation quality, extensive prelaunch benchmarking and secondary model/provider support are post-V1 improvements.

## Generative AI in BipMe (approved product role; integration pending)

BipMe uses embeddings to find relevant material, statistical intelligence to evaluate evidence, and a **generative language model to synthesize and explain** findings for the report-first experience and later draft decisions. The LLM should turn validated, source-linked observations into understandable personalized narratives and optional testable content directions; it should not substitute for the calculation, fabricate current niche trends, assert why X distributed a post, or promise better reach.

Use deterministic report assembly when a model is unavailable, unaffordable or not authorized to process a given source. The output must visibly distinguish **observed evidence**, **inference**, **suggested experiment** and **unknowns**. Personal and X niche evidence stay separately labeled; evidence-backed recommendations must remain useful without a generative model. This is planned behavior, **not a deployed feature**.

V1 selects GroqCloud serving `openai/gpt-oss-120b`, while the interface remains model-agnostic/provider-agnostic and bounded by evidence provenance, processing permissions and usage budgets. [COD-380](https://linear.app/codeddevs/issue/COD-380) is the existing implementation ticket. No additional generative model or benchmark is required to ship V1.

## Creator value and learning loop

The core creator experience is **Understand → Discover → Report → Evaluate → Experiment → Learn**: distinguish recurring historical patterns from isolated viral outliers; assess a draft or content idea against eligible comparables; receive one or two **evidence-linked observations and a testable next action** when justified; publish manually; and review whether the actual outcome supports, contradicts or leaves the original hypothesis inconclusive.

Creators should be able to:

- Recognize approaches that repeatedly performed better or worse, while flagging single viral hits and sparse samples instead of treating them as a repeatable formula.
- Evaluate a draft using inspectable, relevant historical examples rather than generic advice.
- Consider a concrete, optional next action (repeat, revise or test a new format) and a simple hypothesis, without being told what they must publish.
- See what happened after publishing and whether the original assessment and testable hypothesis were supported, contradicted or inconclusive.
- Discover themes and approaches worth exploring over time, without expecting a guaranteed formula.

These are intended **product benefits**, not proven improvements in reach or evidence of causation. Historical associations cannot identify X's private ranking decisions or establish why any specific post was distributed.

## Initial scope

- One private, verified creator identity to start, initially the maintainer; X OAuth is optional for archive-only users and required for authorized X API access.
- Creator-provided post archive where verified/allowed, plus optional read-focused X integration with minimal scopes and spend caps.
- Real historical post data and creator-owned metrics **only when available and permitted**.
- A private experimental workflow; no public signup, payment system, multi-tenancy or scalability targets yet.

## Core creator journey (planned)

1. **Secure private access and define goals.** Verify a BipMe creator session, record the creator's niche, intended audience and desired outcomes. An X OAuth 2.0 PKCE connection is optional for archive analysis, and required only for authorized X API functions.
2. **Build a baseline.** After archive format/rights validation, import a bounded post-only export or use a cost-bounded authorized X history read. Normalize canonical posts, data provenance, metric coverage and descriptive profiles.
3. **Analyze a draft.** Extract semantic, structural, topical, format and intent features without looking at the draft's future outcome.
4. **Find comparable posts.** Filter and rank earlier personal posts first, preserving evidence and exclusions. If a permissioned niche dataset later passes the viability gate, present those comparisons separately with provenance and sample-bias caveats.
5. **Make a decision, not just a forecast.** Show matched evidence, recurring pattern vs possible outlier, evidence strength and **one or two specific observations with an optional testable action**. Provide a creator-relative Distribution Outlook **only when sufficiently supported**; otherwise explain why no reliable range is available.
6. **Record a lightweight experiment.** The creator may choose one question or hypothesis to test for this draft (for example, whether a storytelling format produces stronger conversation engagement). This is an optional field on the existing draft/outlook record, **not** a separate experiment-management system or A/B test.
7. **Publish manually on X.** Let the creator attach the published post URL/ID, preserving the original versioned assessment/hypothesis and linking the assessed draft version (content fingerprint) to what was published. If the published content differs materially, retain the original advice for learning but **do not score its range as a valid forecast** without a new assessment of the published version; no automatic posting permission.
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

Creator-exported X archive import is now a **priority feasibility gate**, not a pre-validated integration or a policy bypass. Do not turn it into a mandatory V1 capability if real format, rights, security or metric constraints fail COD-369. Optional authorized API ingestion remains a fallback.

## Deferred

Unapproved cross-creator content pooling, mass public-post crawling/scraping, proprietary model training, follower graphs, automatic post rewriting/scheduling/publishing, platform expansion, multi-user launch, monetization, complex deployment, standalone experiment dashboards, and promised virality scores. Permissioned niche evidence (COD-372) is initially a research pilot, not a guaranteed V1 production feature.

## Source details

See [X-first MVP](research/X_DISCOVERY_DISTRIBUTION_MVP.md), [Outlook design](research/X_DISTRIBUTION_OUTLOOK_V1_DESIGN.md) and [implementation blueprint](research/X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md) for detailed earlier specification.
