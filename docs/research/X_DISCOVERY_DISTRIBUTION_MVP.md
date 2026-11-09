# X-Only Discovery & Distribution MVP

## Purpose

This document captures the current product direction for the **Discovery & Distribution** track of the African Creator Economy brief.

The core decision is:

> **Do not attempt to build an accurate distribution intelligence system for every social platform in V1. Start with X only.**

The reason is simple: for this product, **accuracy and measurable outcomes matter more than breadth**.

A tool that supports five platforms but gives weak recommendations is less useful than a tool that supports one platform and consistently helps creators improve distribution.

X is the best place to start because important parts of its recommendation architecture are publicly available in open-source repositories. That gives us a stronger technical foundation than trying to reverse-engineer closed platforms purely from creator folklore, anecdotes, or generic growth advice.

---

# 1. Product Thesis

The product should not be positioned as:

- an AI tweet writer;
- a scheduler;
- a generic X analytics dashboard;
- a social media management suite;
- a replacement for X;
- a tool that claims to know X's exact internal ranking score.

Instead, the product should be:

> **A data-driven X distribution intelligence tool that helps creators understand how likely a post is to reach the right audience, what can be improved before publishing, and whether the recommendation actually improved performance after publishing.**

The core promise is:

> **Increase the probability that the right audience on X discovers a creator's work.**

---

# 2. Why X First

## 2.1 Accuracy is the main product

For discovery and distribution, the quality of the recommendation is effectively the product.

If the system recommends:

- the wrong audience;
- the wrong timing;
- the wrong content format;
- the wrong optimization;
- the wrong interpretation of performance;

then creators will quickly lose trust.

This means the MVP should optimize for:

1. accuracy;
2. calibration;
3. explainability;
4. measurable results;
5. continuous learning.

Supporting many platforms too early would make all five harder.

---

## 2.2 X has public recommendation-system code

Unlike many other major social platforms, X has released substantial parts of its recommendation system.

This does **not** mean that we can perfectly reproduce X's production ranking system.

We still do not have access to:

- X's complete live user graph;
- all real-time production data;
- production-scale model weights;
- every internal experiment;
- every ranking configuration;
- every feature or anti-abuse system;
- all infrastructure-specific optimizations;
- every future algorithm change.

However, the open-source code gives us a much better understanding of the system's architecture and recommendation concepts.

That lets us build a product based on real recommendation-system mechanics instead of generic assumptions.

---

# 3. Relevant X Open-Source Repositories

## 3.1 Current X For You recommendation system

### xAI / X Algorithm

**Repository:**  
https://github.com/xai-org/x-algorithm

This should be treated as the **primary technical reference** for the current X-only MVP.

The repository describes the core system powering the X **For You** feed.

Important concepts include:

- in-network candidate sourcing;
- out-of-network candidate sourcing;
- query hydration;
- candidate hydration;
- filtering;
- retrieval;
- transformer-based ranking;
- multi-action engagement prediction;
- post-selection processing;
- author diversity;
- candidate isolation;
- content understanding.

The repository includes newer components such as:

- **Home Mixer**
- **Thunder**
- **Phoenix**
- **Candidate Pipeline**
- content-understanding components
- retrieval and ranking pipelines

### Phoenix

**Repository section:**  
https://github.com/xai-org/x-algorithm/tree/main/phoenix

**Technical documentation:**  
https://github.com/xai-org/x-algorithm/blob/main/phoenix/README.md

Phoenix is particularly relevant because it exposes the two-stage recommendation pattern:

1. **Retrieval** — narrow a very large candidate set into a much smaller candidate pool.
2. **Ranking** — score and order those candidates using a transformer-based model.

That architecture is useful for understanding how X separates:

> "Could this content be relevant?"

from:

> "How relevant is this content compared with other candidates?"

### Candidate Pipeline

Repository root:  
https://github.com/xai-org/x-algorithm

The candidate-pipeline architecture is useful for studying how recommendation stages can be composed through:

- candidate sources;
- hydrators;
- filters;
- scorers;
- selection;
- post-selection validation.

This structure may influence our own internal recommendation pipeline.

---

# 4. Historical X / Twitter Recommendation Repositories

These repositories are extremely valuable for understanding the evolution of X's recommendation architecture.

However, they should not automatically be assumed to represent the current production system.

## 4.1 Twitter / X "The Algorithm"

**Repository:**  
https://github.com/twitter/the-algorithm

This repository contains the older open-source recommendation architecture originally released by Twitter/X.

Important components include:

- Home Mixer;
- CR Mixer;
- User Signal Service;
- Unified User Actions;
- SimClusters;
- TwHIN;
- graph features;
- follow recommendations;
- candidate generation;
- ranking;
- filtering and heuristics.

This repository is especially useful for understanding recommendation-system concepts that may still influence or contextualize the newer architecture.

---

## 4.2 Home Mixer

**Documentation:**  
https://github.com/twitter/the-algorithm/blob/main/home-mixer/README.md

Historically, Home Mixer was responsible for constructing timelines including the For You feed.

Its published architecture describes stages such as:

1. candidate generation;
2. feature hydration;
3. scoring and ranking;
4. filters and heuristics.

The historical system fetched thousands of ranking features before ML ranking.

This provides a useful comparison against the newer transformer-heavy X architecture.

---

## 4.3 Twitter Recommendation ML Models

**Repository:**  
https://github.com/twitter/the-algorithm-ml

This repository contains open-source ML components from the older Twitter recommendation system.

Notable areas include:

- the historical **For You Heavy Ranker**;
- **TwHIN embeddings**.

This repository is useful for studying:

- recommendation-model architecture;
- multi-task ranking;
- graph embeddings;
- historical feature engineering;
- model training patterns.

---

# 5. Important Recommendation Concepts We Can Learn From X

The goal is **not to copy X's recommender**.

The goal is to understand which signals and system concepts are relevant to creator distribution.

## 5.1 Candidate generation

Before ranking can happen, a recommender needs candidate content.

For X, candidates can come from:

- accounts a user follows;
- out-of-network retrieval;
- recommendation models;
- graph relationships;
- topical relationships;
- other candidate sources.

For our product, this teaches us that creator distribution is not simply:

> "Is this a good post?"

It is also:

> "For which audience is this a strong candidate?"

---

## 5.2 User and audience context

Distribution depends on the relationship between:

- the post;
- the creator;
- the viewer;
- the viewer's previous behavior;
- the creator's historical audience;
- topic affinity;
- network relationships.

Therefore our product needs to move toward **audience-fit prediction**, not generic content scoring.

---

## 5.3 Multi-action engagement prediction

The current X architecture predicts multiple possible user actions rather than treating engagement as a single number.

Relevant actions can include probabilities of:

- like/favorite;
- reply;
- repost;
- quote;
- click;
- profile click;
- video view;
- photo expansion;
- share;
- dwell;
- follow author;
- negative feedback;
- block;
- mute;
- report.

This is important for our product.

A post that is likely to generate replies may behave differently from one optimized for reposts, profile visits, follows, or long dwell time.

Therefore our model should eventually avoid one simplistic:

> "Engagement score"

and instead think in terms of **distribution outcomes**.

---

## 5.4 Positive and negative feedback

Good recommendations do not only maximize positive engagement.

Negative reactions matter too.

A post can receive attention while still being a poor recommendation if it produces:

- "not interested";
- mute;
- block;
- report;
- negative feedback.

Our product should eventually distinguish between:

> **raw reach**

and:

> **qualified reach**

Qualified reach means reaching people who are genuinely relevant and likely to become useful audience members.

---

# 6. The MVP Product Flow

The MVP should operate in two major stages:

1. **Pre-publish intelligence**
2. **Post-publish intelligence**

Together they create a learning loop.

---

# 7. Pre-Publish Intelligence

Before publishing, a creator can provide a draft post.

The system analyzes the draft alongside the creator's historical account and content performance.

Possible analysis areas:

- topic;
- semantic meaning;
- intended audience;
- creator-audience alignment;
- historical performance of similar posts;
- format;
- media type;
- length;
- opening/hook;
- likely conversation potential;
- reply potential;
- repost potential;
- dwell/read potential;
- profile-click potential;
- likely audience communities;
- timing;
- recent creator posting history;
- audience saturation.

The system then generates a prediction.

Example:

```text
Distribution Fit: 72/100

Likely Audience:
Nigerian software and AI community

Strongest Signal:
High relevance to audiences that historically engage with your engineering posts.

Primary Weakness:
The first sentence requires context before the reader understands the main result.

Suggested Change:
Move the result or strongest claim into the opening sentence.

Predicted Outcome:
Above-average reply probability
Moderate repost potential
Strong profile-click potential
```

---

# 8. Never Pretend We Know X's Exact Score

The product must be extremely careful with language.

We should **never** say:

> "X will rank this post 72/100."

We do not have X's complete production model or internal ranking state.

Instead:

> **"Our model predicts a distribution potential of 72/100."**

or:

> **"Based on your account history and observed X distribution patterns, this post has above-average distribution potential."**

Our score belongs to **our model**, not X.

This distinction is essential for trust and technical honesty.

---

# 9. Confidence and Explainability

Instead of giving absolute instructions such as:

> "Post at exactly 7:00 PM."

the system should expose uncertainty.

Example:

```text
Recommended Window:
6:30 PM – 8:00 PM WAT

Confidence:
82%

Reason:
Your short-form engineering posts have historically received stronger early engagement during this window.
```

This creates a much better product than pretending every recommendation is certain.

The system should explain:

- what it predicts;
- why it predicts it;
- how confident it is;
- what evidence contributed to the prediction.

---

# 10. Post-Publish Intelligence

The second half of the product begins after the creator publishes.

The system should evaluate the post's real distribution trajectory over time.

Potential observation windows:

- 0–5 minutes;
- 5–30 minutes;
- 30 minutes–2 hours;
- 2–6 hours;
- 6–24 hours;
- longer windows where useful.

Example:

```text
Your post is outperforming your 30-day baseline by 1.8× during its initial distribution period.
```

Another:

```text
Impressions are strong, but engagement conversion is below your normal baseline.
```

Another:

```text
Replies are unusually strong relative to impressions.

This content appears to be functioning better as conversation-driven content than as repost-driven content.
```

---

# 11. The Critical Feedback Loop

The heart of the product should be:

```text
Draft
  ↓
Content Understanding
  ↓
Audience Matching
  ↓
Distribution Prediction
  ↓
Recommendations
  ↓
Publish on X
  ↓
Observe Real Performance
  ↓
Compare Prediction vs Outcome
  ↓
Measure Error
  ↓
Recalibrate
  ↓
Improve Future Predictions
```

This is where the real long-term product value comes from.

---

# 12. Prediction Calibration

Suppose our system predicts:

```text
Expected impressions:
7,000–12,000
```

Actual:

```text
4,200
```

The system should record the prediction error.

Over time, perhaps:

```text
Prediction:
5,000–8,000

Actual:
6,400
```

As more posts are observed, the prediction intervals should become better calibrated.

The goal is not just to generate recommendations.

The goal is to create a system that can say:

> **When we predict a certain result with a certain confidence, reality increasingly matches that prediction.**

---

# 13. Personalization Is Critical

There should not be one universal "X algorithm score" for every creator.

Different creators have:

- different audiences;
- different content niches;
- different posting histories;
- different network graphs;
- different follower quality;
- different engagement patterns;
- different geographic audiences;
- different content formats.

Therefore the system should gradually move from:

```text
General X Distribution Model
```

toward:

```text
General Distribution Model
        +
Creator-Specific Historical Model
        +
Post-Specific Content Understanding
        +
Audience Context
        +
Real Outcome Feedback
```

This personalization is likely to become a major competitive advantage.

---

# 14. Accuracy Dimensions

Accuracy is not one metric.

The product should measure multiple forms of accuracy.

## Content Classification Accuracy

Did we correctly understand:

- topic;
- niche;
- format;
- intent;
- audience?

## Audience-Match Accuracy

Did the content actually perform with the audience segment we expected?

## Engagement-Type Accuracy

Did we correctly predict whether the post would generate:

- replies;
- reposts;
- likes;
- clicks;
- profile visits;
- follows;
- dwell?

## Timing Accuracy

Did the recommended distribution window outperform alternatives?

## Outcome Accuracy

How close were our predicted performance ranges to actual outcomes?

## Recommendation Lift

Most importantly:

> Did following our recommendation improve performance relative to a reasonable baseline?

---

# 15. The Core Success Metric

The product should not be judged by:

- number of generated suggestions;
- number of AI analyses;
- number of creators connected;
- number of dashboards viewed.

The key metric should eventually be something like:

> **Median qualified distribution lift compared with each creator's historical baseline.**

Example:

```text
Creators following our recommendations achieved a median 23% improvement in qualified reach compared with their own historical baseline.
```

That would be much more defensible than simply saying:

> "Our AI helps creators grow."

---

# 16. Qualified Reach vs Raw Reach

Raw impressions should not be the only optimization target.

The system should eventually distinguish between:

## Raw Reach

How many people saw the post.

## Qualified Reach

How many relevant people saw the post and produced valuable downstream signals such as:

- meaningful engagement;
- follows;
- profile visits;
- replies;
- reposts;
- conversions;
- return engagement.

This matters because viral reach from the wrong audience may not help the creator.

---

# 17. MVP Boundary

The V1 should remain intentionally narrow.

## Platform

**X only**

## User

**Creators**

Potentially narrow further during initial testing to a specific creator segment.

## Core Job

**Improve content distribution to relevant audiences on X.**

## Primary Workflow

```text
Analyze draft
→ predict distribution
→ recommend improvements
→ publish
→ measure actual performance
→ compare with prediction
→ learn
```

## Primary Success Metric

**Improvement over the creator's historical distribution baseline.**

---

# 18. What We Should NOT Build in V1

Avoid scope creep.

Do not build:

- Instagram support;
- TikTok support;
- Facebook support;
- LinkedIn support;
- YouTube support;
- full social media scheduling;
- a creator marketplace;
- a new social network;
- payments;
- fan communities;
- a generic AI writing assistant;
- a complete social media management suite.

Those may become future opportunities.

They are not required to prove the core thesis.

---

# 19. Long-Term Moat

The open-source X algorithm is **not itself our moat**.

Anyone can read it.

The moat should become the dataset and learning system produced by:

```text
public recommendation-system knowledge
+
creator historical performance
+
content understanding
+
audience modeling
+
prediction history
+
real post outcomes
+
recommendation experiments
+
continuous calibration
```

Over time this creates proprietary knowledge about:

> **Which types of creator content are likely to distribute successfully to which X audiences, under which conditions.**

That dataset becomes significantly more valuable than generic prompt-based advice.

---

# 20. Current Technical Reference Priority

When implementation and research begin, use the references in approximately this order:

### Priority 1 — Current architecture

1. xAI X Algorithm  
   https://github.com/xai-org/x-algorithm

2. Phoenix recommendation model  
   https://github.com/xai-org/x-algorithm/tree/main/phoenix

3. Phoenix README  
   https://github.com/xai-org/x-algorithm/blob/main/phoenix/README.md

### Priority 2 — Historical architecture and concepts

4. Twitter / X The Algorithm  
   https://github.com/twitter/the-algorithm

5. Historical Home Mixer  
   https://github.com/twitter/the-algorithm/tree/main/home-mixer

6. Home Mixer README  
   https://github.com/twitter/the-algorithm/blob/main/home-mixer/README.md

7. Historical ML models  
   https://github.com/twitter/the-algorithm-ml

---

# 21. Technical Caution

Open source does **not** mean:

> "We know exactly how every post will perform."

It means:

> "We have unusually strong visibility into the architecture and mechanics of the recommendation system, which gives us a better foundation for our own predictive system."

Our product must combine that public architectural knowledge with our own observational data.

The product should therefore be designed as an **independent predictive and measurement system**, not a clone of X's internal recommender.

---

# 22. Working Product Statement

A strong working statement for the project is:

> **An X distribution intelligence system for creators that predicts how a post is likely to distribute, explains what can improve its audience fit, and learns from the real outcome after publishing.**

A sharper external version:

> **We help creators increase the probability that the right people on X discover their work — and we measure whether our recommendations actually worked.**

---

# 23. Why This Fits the African Creator Economy Brief

The original brief asks teams to solve **one part** of the creator economy well rather than build another platform or super-app.

This product fits the **Discovery & Distribution** track because it focuses specifically on:

> **Helping creators get found by the right audience.**

Starting with X makes the scope narrow enough to:

- research deeply;
- build accurately;
- validate experimentally;
- measure results;
- improve from real creator data.

The African creator focus can then be expressed through the initial creator cohort and training/validation data instead of through superficial branding.

For example, early testing could deliberately focus on Nigerian and African creators whose audience behavior, content categories, languages, timing, communities, and network structures are underrepresented in generic creator-growth tooling.

---

# 24. Immediate Research Questions Before Implementation

Before building the production MVP, answer these questions:

1. Which parts of `xai-org/x-algorithm` reflect the current production system?
2. Which signals exposed in the repository can creators or third-party applications realistically observe?
3. What X API data is currently accessible for creator-authorized accounts?
4. Which metrics require paid X API access?
5. Which signals cannot be observed directly and must therefore be estimated?
6. What creator historical data do we need for a useful baseline?
7. How many historical posts are needed before personalization becomes meaningful?
8. How should cold-start creators be handled?
9. Which engagement outcomes should V1 predict?
10. How should confidence and prediction intervals be calibrated?
11. What constitutes "qualified reach" in V1?12. How should A/B or controlled recommendation experiments be run without misleading creators?
13. How will we distinguish correlation from actual recommendation lift?
14. Which parts of the historical Twitter algorithm remain conceptually useful but are no longer production-representative?
15. What rate limits, pricing, and API restrictions could affect post-performance monitoring?

These questions should be resolved through technical research before finalizing the implementation architecture.

---

# Summary

The first version should deliberately choose **depth over breadth**.

We are not building a generic social media optimization platform.

We are building:

> **A highly focused, measurable X distribution intelligence system for creators.**

The open-source X recommendation architecture gives us an unusually strong technical starting point.

But the real product will come from the feedback loop:

> **predict → recommend → publish → observe → compare → learn**

If that loop becomes accurate enough to consistently improve creator distribution relative to their historical baseline, the product becomes genuinely valuable.


---

# 25. X Archive Import as an Optional Historical Data Source

X allows users to download an archive of their account data from X settings.

For this product, that archive is potentially very valuable because it can provide **deeper historical context than the normal API timeline alone**.

X Help Center reference:

https://help.x.com/en/managing-your-account/accessing-your-x-data

The archive can contain machine-readable account information such as:

- historical posts;
- profile/account information;
- followers;
- following;
- media;
- Lists;
- inferred interests;
- ad interactions;
- other account-associated information.

The archive should be treated as a **historical-context source**, not as a replacement for the X API.

## 25.1 Why the Archive Matters

The normal X timeline API is useful for recent creator history, but the archive can extend much further back and may include posts from the creator's earliest account history.

Example:

```text
API-accessible recent history:
~3,200 posts

Archive history:
2014 → 2026
18,000+ posts
```

That additional history can improve:

- creator topic profiling;
- content clustering;
- posting-frequency analysis;
- long-term format analysis;
- language-use analysis;
- creator-content eras;
- historical audience relationships;
- matched-post retrieval;
- cold-start personalization.

The archive is therefore most valuable for understanding:

> **Who this creator has historically been on X.**

# 26. Recommended Dual Onboarding Model

The product should support two complementary onboarding paths.

## Option A — Connect X

Primary onboarding path:

```text
Sign in with X
↓
retrieve current account data
↓
retrieve recent creator history
↓
build initial baseline
↓
monitor future posts automatically
```

This path is best for:

- current metrics;
- live analytics;
- ongoing synchronization;
- follower updates;
- post-publish monitoring;
- creator-authorized non-public metrics.

## Option B — Import X Archive

Optional deeper-personalization path:

```text
Download X archive
↓
upload archive ZIP
↓
parse approved machine-readable files
↓
reconstruct long-term creator history
↓
merge with current API data
```

This creates a combined model:

```text
X ARCHIVE
long-term historical context

+

X API
current and live behavior
```

The product should use both sources where available.

# 27. Archive Import Helps With Cold Start

One of the biggest product problems is personalization for a newly connected creator.

Without historical data, the product may initially know very little and may require future observations before recommendations become strongly creator-specific.

An archive import can accelerate that process.

Example:

```text
Historical creator-topic profile

Software engineering     38%
AI                       24%
Startups                  17%
Personal journey           9%
Other                     12%
```

Then:

```text
Historically strongest content areas

AI + engineering
Founder/building posts
Technical explanations
```

This enables the product to build a meaningful creator profile immediately.

# 28. Archive Is a Snapshot, Not a Live Feed

The archive is not a replacement for ongoing API access. It represents account information available when the archive was generated.

Therefore the architecture should be:

```text
          X ARCHIVE
              │
              │ historical context
              ▼
       Creator Data Store
              ▲
              │ current/live data
              │
            X API
```

The archive provides depth. The API provides freshness.

# 29. Data Minimization for Archive Imports

An X archive may contain information that is completely unnecessary for distribution intelligence.

The importer should **not blindly ingest the entire archive**. Instead, use a strict allowlist.

Recommended example:

```text
IMPORT

✓ Posts
✓ Account/profile metadata
✓ Followers
✓ Following
✓ Lists
✓ Public media metadata
✓ Relevant interest/topic information

IGNORE

✗ Direct Messages
✗ Address-book data
✗ Email history
✗ Phone numbers
✗ Login/IP history
✗ private device information
✗ unnecessary advertising identifiers
```

Principle:

> **Only ingest information that materially contributes to creator distribution intelligence.**

# 30. Treat Archive Data and API Metrics Differently

Do not assume that the X archive contains all historical analytics required by the product.

The working architectural assumption should be:

```text
ARCHIVE
=
content + behavioral + account history
```

and:

```text
API
=
performance metrics + live analytics + ongoing synchronization
```

until a real current archive schema is inspected and verified.

# 31. Creator Identity Representation

Archive history can make pre-publish intelligence substantially more creator-specific.

A creator's historical posts can be semantically clustered.

Example:

```text
Cluster 1
Backend / NestJS / distributed systems

Cluster 2
AI / OpenAI / Codex

Cluster 3
Startup / building in public

Cluster 4
Personal developer journey

Cluster 5
Hackathons
```

When the creator writes a new draft, the system can compare it against those historical clusters.

The pre-publish question becomes:

> **How does this draft fit this creator's established content graph?**

rather than:

> "Is this a globally good X post?"

# 32. Archive Data Improves Comparable-Post Matching

The matched-baseline system becomes stronger when more historical posts are available.

However, old posts must not be weighted equally with recent posts because follower count, audience composition, creator niche, platform behavior, and recommendation architecture can change substantially over time.

Comparable-post matching should therefore apply time-aware weighting.

Conceptually:

```text
Historical similarity
×
recency weight
×
audience-era weight
×
format similarity
×
topic similarity
```

The archive should **expand historical context without allowing stale history to dominate predictions**.

# 33. Revised Creator Data Architecture

```text
                 ONBOARDING
                     │
           ┌─────────┴─────────┐
           │                   │
        X OAuth          Archive Import
           │                   │
           ▼                   ▼
       Current API       Historical Data
           │                   │
           └─────────┬─────────┘
                     ▼
             Creator History
                  Engine
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
      Topics       Formats     Behavior
        │            │            │
        └────────────┼────────────┘
                     ▼
             Creator Baseline
                     │
                     ▼
           Distribution Outlook
```

After onboarding, X API synchronization continues to feed new creator and post-performance data into the system.

# 34. Archive Import as an Accuracy Upgrade

Archive import does not necessarily need to be mandatory in the first hackathon build.

It creates extra onboarding friction because the creator must request, download, and upload their X archive.

Instead, it can be presented as an optional accuracy upgrade:

> **Want more personalized recommendations? Import your X archive.**

Example creator-facing output:

```text
We've analyzed:

8 years of X history
11,482 historical posts
5 major content clusters
```

This can support much more personalized findings than generic social-media advice.

# 35. Do Not Make Archive Import Mandatory for V1

For the initial product, **X OAuth should remain the primary onboarding path**.

Reasons:

- lower friction;
- immediate access;
- live metrics;
- automatic updates;
- easier demo flow.

Archive import should be designed into the data model but can remain optional or post-onboarding.

# 36. Additional Archive Research Required

Before finalizing archive support, inspect a **real current X archive schema**.

Research should identify:

1. Exact archive file names.
2. Which files contain posts.
3. Whether posts are JSON, JavaScript-wrapped JSON, or another structure.
4. Exact post fields.
5. Whether deleted or historical records appear.
6. How followers and following are represented.
7. Whether Likes are included and how complete they are.
8. How media references are represented.
9. What interest/inference files are included.
10. Whether useful historical analytics metrics exist.
11. Whether engagement counts are preserved with historical posts.
12. How large archives should be streamed and parsed safely.
13. Which archive files should be explicitly ignored.
14. What retention/deletion controls should apply after import.
15. How archive data should be merged with live API records without duplication.

Until that schema is verified:

> **Treat the archive as a historical content/context source, not as a guaranteed historical analytics source.**

# 37. Updated Working Product Data Model

The product now has three major information layers.

## Layer 1 — Long-Term Creator History

Primarily sourced from:

- X archive;
- historical API-accessible posts.

Used for:

- creator identity;
- topic clusters;
- content eras;
- language patterns;
- format preferences;
- long-term comparable-post retrieval.

## Layer 2 — Current Creator State

Primarily sourced from:

- X API;
- current profile;
- current followers/following;
- recent posts;
- recent topic context.

Used for:

- current audience state;
- recent baselines;
- current creator niche;
- current posting behavior.

## Layer 3 — Live Performance

Primarily sourced from:

- creator-authorized X metrics;
- post-publish metric polling;
- search/topic context.

Used for:

- distribution velocity;
- matched-baseline comparisons;
- live trajectory;
- postmortem analysis;
- future calibration.

Combined:

```text
Long-Term History
        +
Current Creator State
        +
Live Performance
        ↓
Creator Distribution Intelligence
```

# 38. Updated Final Product Principle

The product should not attempt to be a universal X algorithm oracle.

Its strongest advantage should be:

> **Deep creator-specific historical understanding combined with current X data and real post outcomes.**

The X archive improves the historical-understanding side.

The X API improves the real-time side.

Together, they enable a stronger personalization loop:

```text
historical creator context
+
current account state
+
new draft
+
live X environment
+
actual post outcome
↓
creator-specific distribution intelligence
```

This is more defensible, more privacy-conscious, and more likely to produce genuinely useful recommendations than a generic "AI X growth score."

# COD-375 Official X Niche Search Feasibility (verified 9 Nov 2026)

This dated review supplements the older research above; it supersedes its earlier assumptions about X search access and prices where they conflict. It is a documentation review only: **no live or billable X request was made**. On 9 Nov 2026, a read-only authenticated console review confirmed an active BipME app on a Pay Per Use project, a USD 0 balance/free-credit balance/current spend, a USD 5 billing-cycle cap, and auto-recharge unavailable. The auth form displayed Read-only OAuth 1.0a permission, email requests off, Web App/confidential client, and the local callback. A console notice states expanded resources become billable from 22 Nov 2026. The project-specific search request quotas are visible in the console and recorded below, but they do not verify endpoint entitlement, returned fields, OAuth 2.0 scopes/handshake, actual per-resource prices, saved-state persistence of the auth form, or processing rights. See the current rights gates in [Security](../security.md) and the proposed COD-376 boundary in [Architecture](../architecture.md).

## Search, fields and signal availability

| Need | Officially documented capability (verified 9 Nov 2026) | BipMe boundary |
| --- | --- | --- |
| Current niche Posts | `GET /2/tweets/search/recent`, last 7 days, described as available to all developers. Query supports operators, language filter, `start_time`/`end_time`, relevance/recency sort, and pagination. | Public documentation is not account-specific entitlement or rights approval. Recent search is sufficient for a current report; do not require full archive. |
| Historical niche context | `GET /2/tweets/search/all`, archive back to 2006; documented for pay-per-use and Enterprise customers. | Not required for the initial report. No account entitlement is confirmed. |
| Recent request bounds | 10 default, 10–100 Posts per page, 512-character query limit. Rate table: 450 requests/15 min per app and 300/15 min per user. | COD-376 must impose much smaller product caps and count every attempted page against the request ceiling. |
| Full-archive bounds | 10 default, 10–500 Posts per page, 1,024-character query limit; rate table lists one request/second and 300/15 min per app, one/second per user. | No full-archive use proposed. App-specific limits can differ; console values govern. |
| Post fields | Search references expose `id`, `text`, `author_id`, `created_at`, `lang`, `conversation_id`, `entities`, `attachments`, `referenced_posts`, `public_metrics`, and other optional fields. Author expansion and `user.fields=public_metrics` can add follower-count context. | Request only fields justified by the use case, only after rights approval. Returned text, author/profile data, and expansions each remain X Content. |
| Public outcomes | X's metrics reference classifies `public_metrics` impressions, likes, replies, reposts, quotes, and bookmarks as public; video `view_count` is also public. | A field's existence is not proof it is populated for every result or comparable. Preserve missing values and observation time; use impressions as a denominator only when present, correctly defined, and window-compatible. |
| Owner-authorized outcomes | `non_public_metrics`, `organic_metrics`, and `promoted_metrics` require user-context auth and are documented only for Posts created within 30 days; examples include clicks, engagement, and video playback percentages. | These are not third-party search metrics. They cannot fill missing denominators for niche posts. |
| Viewer-level ranking evidence | No regular search field grants access to individual viewers' dwell, completion/read-through, candidate scores, Phoenix predicted probabilities/actions, or the reason a post was recommended. | Treat those signals as unavailable. The [older Twitter algorithm repository](https://github.com/twitter/the-algorithm) and [newer X algorithm repository](https://github.com/xai-org/x-algorithm) are public engineering research context only; neither is a complete/live ranking oracle or a source of BipMe observations or weights. |

The public search reference shows an OAuth 2.0 Bearer token. X describes app-only Bearer authentication as app-scoped and typically suitable for read-only public data; no user scopes are implied by that method. If a separate creator-authorized operation is needed, X documents `tweet.read` and `users.read`; `offline.access` is needed only to receive a refresh token. Do not request creator scopes just to search public niche posts. The endpoint documentation does not establish BipMe's actual app entitlement or account-specific allowlist. Confirm the exact configured auth mode and endpoint result in the developer console before enabling anything.

### BipMe developer-console observations — 9 Nov 2026

In an authenticated, read-only console review, the BipME by CodedDevs app was shown as **active** and linked to **Default Project (Pay Per Use)**. The dashboard listed the app under **Development**; the app description was the generic “This app was created to use the X API.” The app details editor exposed only app name, icon, and description fields; no approved-use-case record was visible there. This does not prove that no approval exists elsewhere. The Credits page displayed **USD 0.00 remaining balance**, **USD 0.00 free credits**, a **USD 5.00 billing-cycle cap**, **USD 0.00 current spend**, and auto-recharge unavailable because no payment method is configured. The displayed cycle was **6 Nov–6 Dec 2026**. The auth settings form displayed OAuth 1.0a **Read** permission, email request off, **Web App (confidential client)**, callback `http://127.0.0.1:8000/api/auth/x/callback`, and the BipMe GitHub website URL. No settings were changed. Since the form did not show a saved-state confirmation, persistence is not independently proven; OAuth 2.0 requested scopes and a successful OAuth handshake are unverified.

Usage analytics showed **0 billable events** and **USD 0.00 total cost** for 10 Oct–9 Nov 2026, with no request rows.

The project's **Rate limits** page listed 232 endpoints. Filtering for `/2/tweets/search` showed `GET /2/tweets/search/all` at **5 requests/second and 300 requests/15 minutes per app or user matching auth**; `GET /2/tweets/search/recent` showed **450 requests/15 minutes per app with app auth or 300 per user with user auth**. These are project-specific request-quota entries; they do not prove endpoint entitlement or which auth mode BipMe will use. The active Pay Per Use project is consistent with X's public description of Full-Archive Search availability, but the console view did not establish endpoint-level entitlement. **No X API request was made**, so actual returned fields and account-specific per-resource prices remain unverified. The inspected console pages did not expose account-specific billing prices; use published prices only for estimates and check account-specific prices before any later authorized call. The immutable numeric account ID, written X approval for BipMe's niche-analysis purpose, retention/display terms, local pretrained-embedding permission, Groq transfer permission, and the Groq organization Data Controls/ZDR state also remain unverified. The zero balance is not approval to purchase credits or make a call. Do not infer rights or entitlement from app configuration or project plan.

Owner-provided 7 Nov screenshots recorded the same displayed USD 5 cap, zero balance/spend and unavailable auto-recharge, and these auth settings; the current 9 Nov review supersedes them for the values visible in the console at review time. COD-344 remains the owner of the unresolved access, account-ID, pricing and processing-rights gate.

Current search syntax includes exact phrases, keywords, `OR`, hashtags, mentions, `from:`, `to:`, `retweets_of:`, media/link operators, `lang:`, and filters such as `-is:retweet` and `-is:reply`. Recent search supports `sort_order=recency|relevancy`; `lang:en` and the bounded time window can narrow retrieval. Do not default to `is:verified` or author/engagement popularity filters: they would systematically skew who is visible. If conversation quality is the goal, exclude retweets but keep replies as a separately tagged stratum rather than removing all discussion.

## Lightweight discovery and sampling plan

1. Start only from the creator's versioned declared niche, intended audience, goal, and preferred language. Produce at most three short, reviewable query variants by combining declared terms with a small human-reviewed synonym list and phrase/OR syntax. Never infer audience demographics from followers, mine more query terms from retrieved Posts, or let an LLM autonomously search.
2. Store query-plan version, normalized query or its controlled internal representation, declared source terms, operators/language, endpoint, requested time range, `sort_order`, request time, page tokens/counts, requested fields, returned counts, exclusions, and budget reservation/reconciliation IDs. These describe collection provenance; they are not permission to retain the returned Post text.
3. Use a seven-day window for the initial report. For each query, take one page ordered by relevance and, only if coverage and budget permit, at most one continuation page. A recency-ordered query may expose freshness gaps, but counts toward the same three-query maximum and report budget. Deduplicate by Post ID after conservative cost reservation. Stop on cap, stale window, rights/consent loss, untrusted pagination, or exhausted/unknown budget.
4. Exclude retweets from original-content comparisons. Keep replies, threads, media formats, and languages separate or explicitly matched. Exclude a result as unrelated only using versioned declared-topic rules plus inspectable reason codes; preserve counts for returned, excluded, duplicated, missing-text, and unknown-language items. Do not treat a search query match as proof of niche relevance.
5. Build strong/typical/weak evidence only within compatible age, language, format/thread-role, and author-size bands. If valid impression denominators and compatible observation windows exist, use a clearly stated within-sample outcome measure and retain its exact definition. If not, label strata only as high/median/low observed public counters or content examples—not strong/weak performance. Do not equate a larger account's raw likes with superior performance.
6. Select a few examples per stratum from each query/time/format coverage cell rather than taking only the first most-relevant or highest-engagement posts. Record selection rule, candidate count, selected count, known/unknown metric coverage, and time/size/format exclusions. Because the API's retrieval and rank order are not a probability sampling frame, this is a **balanced evidence sample, not statistically representative**. Small or empty cells produce explicit insufficient/partial evidence.

Freshness expires with the searched date window and collection time; do not display stale niche findings as current. Results can overrepresent popular, frequently discussed, keyword-literal, verified, English-language, and algorithmically ranked content; they underrepresent private/removed posts, quiet creators, niche vocabulary variants, impressions with missing counters, and groups filtered by query design. `public_metrics` are cumulative snapshots observed at retrieval, not post-age-normalized rates. Without reliable impression denominators, creator-size bands, exact windows, and format compatibility, comparisons are descriptive only. Search presence and early counts do not reveal private attention or cause of distribution.

## Published cost examples and fail-closed caps

The current X pricing page (verified 9 Nov 2026) says read operations are charged per returned resource, not per read request: **Post $0.005/resource; User $0.010/resource**. Search itself has no additional per-query read price shown; each returned Post is billable. If `author_id` is expanded and User objects are returned, budget those user resources too. The authenticated console also displayed an X notice dated 26 Oct: **starting 22 Nov 2026, resources returned through expansions (Posts, Users, media, polls and places) will be billed at the standard Pay Per Use rate for that resource**. The expanded-result estimates below are conservative at those rates and apply from that effective date; the current account-specific rate schedule and any transitional billing behavior must be confirmed in the console before a future request. Post Counts are separately listed as **$0.005/request** for recent and **$0.010/request** for full archive, so V1 should not use Counts unless a measured need justifies that separate charge. Pay-per-use credits are purchased up front and usage appears in the developer console; X advertises a first-purchase/auto-recharge credit incentive that is currently rolling out and eligibility varies. Treat any incentive as $0 in the budget, do not add a payment card or enable auto-recharge for this research, and verify the actual credit balance. The published pay-per-use plan also states a 3-million Post-read monthly cap. Same-UTC-day resource deduplication is expressly a soft guarantee and is excluded from all estimates below.

| Illustrative case | Bound and estimate at published standard prices | Interpretation |
| --- | --- | --- |
| One initial report, one page/query | 3 queries × 1 page × 10 posts = at most 30 Posts. If each has a distinct expanded author: 30 × $0.005 + 30 × $0.010 = **$0.45** from 22 Nov. Without User expansion the Post-only ceiling is **$0.15**. | Conservative post-22-Nov ceiling, not an expected or observed charge. |
| One capped refresh | Same limits, with every resource assumed new: **up to $0.45** expanded from 22 Nov or **$0.15** Post-only. | Do not subtract the same-day deduplication soft guarantee. |
| Two pages/query stress case | 3 queries × 2 pages × 10 posts = at most 60 Posts and, at most, 60 distinct expanded Users: **$0.90** expanded from 22 Nov or **$0.30** Post-only. | Six search requests and 60 returned Posts is a product cap, far below endpoint rate limits. |
| Initial + one refresh/day | At the stress cap, up to **$1.80/day from 22 Nov**; 30 consecutive days would be **$54** absent a total cycle cap. At one page/query, **$0.90/day from 22 Nov** and **$27/30 days**. | All resources assumed unique; excludes identity reads, retries and other endpoints. The cycle cap must stop requests first. |

Proposed COD-376 budget envelope for discussion: **$0.90/report from 22 Nov onward**, **$1.80/day** for one initial report plus one full refresh, and a **$5.00 cycle ceiling**, consistent with the cap currently displayed in the authenticated console on 9 Nov 2026. At $0.90/report, a $5 cycle cap permits at most five full-cap reports before the next worst-case reservation must be denied; do not spend the remaining amount if it cannot cover a complete reservation. At the current $0 credit balance, even this estimate does not authorize a call; purchasing credits or changing payment settings is outside this research. A configured external spend cap and COD-347's implemented application reservation are complementary, not interchangeable.

For every request, reserve the worst-case post and expanded-user resources before the call; use `max_results=10`, a maximum of three query plans, and at most two pages/query. COD-376 may request only the `author_id` expansion; reject media, poll, place, and any other expansion before making a request. Reserve up to one User resource per returned Post at the current documented User rate whenever `author_id` is requested, in addition to the Post resources. Do not retry an uncertain/ambiguous billable response automatically. Fail closed on missing price, unknown account credits, absent/disabled limits, stale pricing, exhausted cap, 401/403, or an authorization/rights gate change. Reconcile returned resource counts and charges against the usage endpoint/console before allowing later reports. Pagination requests count toward API rate limits even though read billing is per returned resource. A failed or empty request's exact account billing remains a console check.

## Rights decision and recommendation

The [Developer Agreement](https://docs.x.com/developer-terms/agreement) says X Content may be used to conduct analysis only as explicitly approved by X, prohibits foundation/frontier-model training/fine-tuning, and restricts redistribution. The [Developer Policy](https://docs.x.com/developer-terms/policy) requires an approved, disclosed use case, current content for display, and prompt removal/update when content is changed/deleted (as soon as reasonably possible and within 24 hours after a request). It also limits distribution of X Content and IDs. X's [Restricted Uses](https://docs.x.com/developer-terms/restricted-use-cases) page permits aggregate X-content analysis that stores no personal data, including user IDs, usernames, and other identifiers, provided it also complies with law and the Agreement/Policy. This is conditional and does not resolve BipMe's proposed inspectable post-level evidence, retention/display, or app-specific approval. Do not treat an aggregate label as a blanket license to keep, embed, analyze, display, or cross-share public Posts. The full permission/storage/AI matrix is in [Security](../security.md).

Local pretrained embeddings do not train a model, but the Agreement's separate rule that X analysis be explicitly approved leaves embedding inference unresolved. GroqCloud's current [data handling guide](https://console.groq.com/docs/your-data) says ordinary inference inputs/outputs are not retained by default, while temporary reliability/abuse logs may persist up to 30 days; Zero Data Retention is an account control and must be confirmed. Groq's handling terms do not establish that X permits external processing. No X-derived text may be sent to E5 or Groq until both X's source-processing permission and the external-provider transfer/privacy review pass.

**Recommendation: Conditional Go for mocked interface/design only; No-Go for live niche discovery, real text/embedding processing, cross-creator reuse, and external LLM transfer at this checkpoint.** No live Go is possible from public docs alone. Keep the personal-only partial report when discovery is unavailable, rights-blocked, stale, insufficient, or over budget. Once COD-344 verifies access, app use-case approval, explicit data processing rights, active prices/credits, and enforceable caps, the owner can revisit the conditional decision; COD-376 should remain blocked until then.

## Official sources checked 9 Nov 2026

- [Search Posts overview, endpoint access, operators, windows and page-size summary](https://docs.x.com/x-api/posts/search/introduction)
- [Recent Search endpoint reference](https://docs.x.com/x-api/posts/search-recent-posts)
- [Full-Archive Search endpoint reference](https://docs.x.com/x-api/posts/search-all-posts)
- [X API v2 endpoint rate limits](https://docs.x.com/x-api/fundamentals/rate-limits)
- [Pay-per-use prices, resource billing and deduplication](https://docs.x.com/x-api/getting-started/pricing)
- [OAuth 2.0 app-only and user-context overview](https://docs.x.com/fundamentals/authentication/oauth-2-0/overview)
- [OAuth 2.0 PKCE scopes and refresh-token requirements](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)
- [X API pay-per-use credit incentives (rolling out; not assumed)](https://docs.x.com/x-api/getting-started/free-credits)
- [Public and creator-authorized metrics](https://docs.x.com/x-api/fundamentals/metrics)
- [X Developer Agreement](https://docs.x.com/developer-terms/agreement)
- [X Developer Policy](https://docs.x.com/developer-terms/policy)
- [Restricted uses of the X API, including aggregate analysis without stored personal data](https://docs.x.com/developer-terms/restricted-use-cases)
- [GroqCloud data retention and Zero Data Retention controls](https://console.groq.com/docs/your-data)

Public docs were read on the verification date above. The console exposed project-specific request quotas, but endpoint entitlement, app terms/approved use case, auth-effective limits, account-specific per-resource prices, user identity allowlist, credits, billing cap, auto-recharge, and Groq organization retention settings remain account-owner checks under COD-344. Recheck this information before any live call because API rights, limits, and prices can change.
