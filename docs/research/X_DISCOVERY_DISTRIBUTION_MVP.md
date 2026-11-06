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