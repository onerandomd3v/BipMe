# X Distribution Intelligence — Research Findings & MVP Implications

## Purpose

This document captures the research findings for an **X-only creator Discovery & Distribution intelligence product**, with a specific focus on:

- what X exposes publicly and through creator-authorized API access;
- what can be inferred responsibly;
- what cannot be known externally;
- how X's current open-source recommendation architecture should inform the product;
- what the MVP should measure and predict;
- key technical, API, policy, and licensing constraints;
- how the findings change the recommended V1 architecture.

The main conclusion is:

> **A useful X distribution-intelligence product is feasible, but it should not attempt to reproduce X's recommender or claim to know X's exact ranking decisions.**

The strongest V1 should be:

> **Creator-specific distribution intelligence built from data X actually exposes, informed by X's open-source recommendation architecture, and continuously evaluated against real post outcomes.**

---

# 1. Three Types of Information

The product should distinguish clearly between three categories:

## Observable

Data X provides directly through public or authenticated API access.

Examples:

- post text;
- creation time;
- public engagement metrics;
- impressions;
- replies;
- reposts;
- quotes;
- bookmarks;
- creator-authorized private metrics;
- followers and following;
- context annotations;
- recent search data.

## Inferable

Information we can estimate from observable data.

Examples:

- historical creator baselines;
- expected relative performance;
- topic-specific performance;
- timing fit;
- content-type fit;
- reply/repost tendencies;
- distribution velocity;
- matched-baseline performance;
- likely audience categories based on public non-sensitive signals.

## Externally unknowable

Information X uses internally but does not expose.

Examples:

- the exact Phoenix score for every potential viewer;
- the exact final ranking score of a post;
- every impression's exact source;
- which internal candidate generator selected a specific impression;
- the full production user graph;
- all production model weights/checkpoints;
- every live feature and experiment;
- complete negative-feedback counts;
- the full set of recommendation-eligibility decisions.

This distinction should shape every product claim.

---

# 2. Current X Recommendation Architecture

The current open-source X recommendation repository is:

https://github.com/xai-org/x-algorithm

This should be treated as the primary technical reference for the current MVP.

The repository describes important parts of the current **For You** feed architecture.

At a high level, recommendation involves:

- candidate sourcing;
- in-network content;
- out-of-network content;
- retrieval;
- content understanding;
- hydration;
- filtering;
- ranking;
- post-selection processing;
- diversity;
- visibility/safety constraints.

Important components include:

- **Thunder**
- **Phoenix**
- **Home Mixer**
- candidate pipelines
- content-understanding components

---

# 3. In-Network vs Out-of-Network Recommendations

The current architecture separates different candidate sources.

## In-Network

Content from accounts the user already follows.

A major relevant component is **Thunder**.

## Out-of-Network

Content from accounts the user does not follow.

Relevant systems include:

- **Phoenix retrieval**
- **SimClusters**
- other recommendation candidate sources

This teaches us an important product principle:

> Distribution is not simply about whether a post is "good."

A better question is:

> **For which audience is this post likely to be a strong candidate?**

That means our product should evolve toward **audience-fit intelligence**, not a universal content score.

---

# 4. Phoenix and Multi-Action Ranking

Phoenix is one of the most relevant parts of the current architecture.

Repository:

https://github.com/xai-org/x-algorithm/tree/main/phoenix

Phoenix README:

https://github.com/xai-org/x-algorithm/blob/main/phoenix/README.md

Quickstart:

https://github.com/xai-org/x-algorithm/blob/main/phoenix/QUICKSTART.md

Phoenix uses a two-stage recommendation pattern:

1. **Retrieval** — reduce a very large set of possible candidates to a smaller candidate pool.
2. **Ranking** — score those candidates for a specific viewer.

The ranking logic predicts multiple possible user actions, rather than one generic engagement score.

Relevant actions described in the open-source architecture include probabilities of:

- favorite / like;
- reply;
- repost;
- quote;
- share;
- DM share;
- copy-link share;
- post click;
- profile click;
- link click;
- photo expansion;
- video opening;
- dwell;
- dwell time;
- active seconds;
- follow author;
- "not interested";
- mute;
- block;
- report.

This means there is no single universal:

> "Post quality score"

A post may be highly valuable for one viewer and irrelevant to another.

Therefore the product should **not** claim:

> "Your X algorithm score is 84/100."

A better framing is:

> **Our model estimates that this post is above your normal distribution baseline, with high reply potential and moderate repost potential.**

---

# 5. Ranking Is Not the Same as Visibility

X separates ranking from visibility and safety controls.

Even a post with strong ranking potential may receive limited distribution because of:

- account-level labels;
- post-level labels;
- spam classifications;
- adult-content classifications;
- recommendation eligibility;
- blocked or muted relationships;
- safety policies;
- other visibility restrictions.

The current open-source repository contains substantial visibility infrastructure.

Repository:

https://github.com/xai-org/x-algorithm

This creates an important product opportunity.

Instead of only building:

> **Distribution Prediction**

the product may eventually provide:

> **Distribution Diagnosis**

That means helping a creator understand whether poor performance appears related to:

- weak audience fit;
- low engagement velocity;
- content format;
- timing;
- creator baseline;
- visibility/safety factors;
- topic saturation.

Diagnosis may be more defensible than pretending we know X's internal ranking result.

---

# 6. Historical Creator Data Available Through X

X allows applications to retrieve a creator's recent timeline.

X timeline documentation:

https://docs.x.com/x-api/posts/timelines/introduction

A user timeline can provide up to the creator's **3,200 most recent posts**, depending on endpoint behavior and access.

This gives an established creator a potentially useful historical dataset.

Relevant fields can include:

- post text;
- creation timestamp;
- language;
- conversation ID;
- reply/reference relationships;
- media;
- entities;
- context annotations;
- public engagement metrics.

This is enough to create personalized creator baselines.

---

# 7. Public Post Metrics

X exposes public metrics for posts.

Metrics documentation:

https://docs.x.com/x-api/fundamentals/metrics

Relevant metrics include:

- impressions;
- likes;
- replies;
- reposts;
- quotes;
- bookmarks.

Important caveat:

> **Impressions are not unique viewers.**

A single person may contribute multiple impressions if the post is shown multiple times.

From these metrics, the product can calculate:

- like rate;
- reply rate;
- repost rate;
- quote rate;
- bookmark rate;
- engagement ratios;
- impression velocity;
- engagement velocity;
- post-performance percentiles.

These are strong enough to build meaningful creator-specific analytics.

---

# 8. Creator-Authorized Private Metrics

When the creator authenticates their own X account, richer metrics can be available for their own posts.

Metrics documentation:

https://docs.x.com/x-api/fundamentals/metrics

Examples include:

- URL clicks;
- profile clicks;
- total engagements;
- organic metrics;
- promoted metrics where relevant.

Example:

```text
Impressions:    18,500
Profile clicks:    790
URL clicks:        240
Engagements:     2,460
```

This allows the product to distinguish:

> **raw reach**

from:

> **reach that generated creator value**

That is strategically important.

---

# 9. The 30-Day Private-Metric Limitation

X's documentation currently indicates that certain non-public, organic, and promoted metrics are only available for posts created within approximately the previous **30 days**.

Reference:

https://docs.x.com/x-api/fundamentals/metrics

This means onboarding should treat historical data in two layers.

## Older History

Potentially available:

- text;
- timestamp;
- public impressions;
- likes;
- replies;
- reposts;
- quotes;
- bookmarks.

## Recent History

Potentially available:

- profile clicks;
- URL clicks;
- richer engagements;
- organic/promoted breakdowns;
- video performance.

This creates an important product requirement:

> **Once a creator connects, we should begin continuously storing permitted creator-authorized metrics so our own historical baseline becomes richer over time.**

---

# 10. Video Performance Data

For creator-owned video posts, X exposes video playback metrics.

Reference:

https://docs.x.com/x-api/fundamentals/metrics

Relevant playback stages can include:

- playback start;
- 25%;
- 50%;
- 75%;
- 100%.

Example:

```text
Views / starts:       30,000
25% completion:       22,400
50% completion:       15,100
75% completion:        9,800
100% completion:       6,100
```

This gives the product a genuine retention curve rather than only surface-level view counts.

That could support recommendations about:

- video hooks;
- retention quality;
- format;
- content length;
- likely audience attention quality.

---

# 11. Audience Data Available Through X

X exposes useful pieces of the audience graph.

## Followers

Documentation:

https://docs.x.com/x-api/users/get-followers

## Following

X API user/following endpoints are part of the broader Users API.

Documentation root:

https://docs.x.com/x-api/users/introduction

## Repost Users

Documentation:

https://docs.x.com/x-api/posts/get-reposted-by

## Liking Users

Documentation:

https://docs.x.com/x-api/posts/likes/introduction

A major limitation is that liking-user retrieval can be capped and should not be treated as a complete representation of all engaged users.

Therefore likes alone should **not** be used as a full audience graph.

Replies, reposts, quote posts, and creator followers may provide more useful audience signals.

---

# 12. Public User Information

The X User object exposes public profile information such as:

- username;
- bio;
- follower count;
- following count;
- post count;
- listed count;
- verification information;
- public location when voluntarily supplied.

Data dictionary:

https://docs.x.com/x-api/fundamentals/data-dictionary

This can support high-level, non-sensitive audience classification.

For example:

```text
Approximate public audience categories:

Software / AI accounts       43%
Startup / founder accounts   18%
Students                      12%
Design / product accounts      9%
Other                         18%
```

However, this should remain limited to legitimate, non-sensitive public categories.

---

# 13. Sensitive Data Must Not Be Inferred

X's Developer Guidelines impose restrictions around sensitive data and prohibited uses.

Developer Guidelines:

https://docs.x.com/developer-guidelines

The product should avoid inferring sensitive user attributes such as:

- health status;
- religion;
- political affiliation;
- other protected or sensitive personal characteristics.

Audience intelligence should remain focused on:

- public professional categories;
- content interests;
- topical behavior;
- creator-audience relationships;
- public engagement patterns.

---

# 14. X Context Annotations

X provides **Context Annotations** for some posts.

Documentation:

https://docs.x.com/x-api/fundamentals/post-annotations

These annotations can classify posts into semantic domains and entities.

Examples may include:

- Technology;
- Sports;
- Entertainment;
- Products;
- Brands;
- Events;
- People;
- Places.

This is strategically useful.

Instead of always relying on our own model to classify a published post, we can sometimes use X's own semantic classification as an additional signal.

However, coverage can vary by language.

That matters for African creators.

---

# 15. African-Language and Nigerian-Language Coverage

Because the product is intended for African creators, we should specifically evaluate how well X's own context/classification systems handle:

- Nigerian Pidgin;
- Yoruba;
- Igbo;
- Hausa;
- mixed English/Pidgin;
- African slang;
- regional cultural references.

We should **not** assume that semantic annotation coverage is equally strong across all languages.

This may become an important differentiation opportunity.

Our product could eventually improve creator-facing semantic understanding where generic platform tooling has weak local-language coverage.

---

# 16. Search and Conversation Context

X exposes search and streaming tools that may provide useful contextual signals.

## Recent Search

Documentation:

https://docs.x.com/x-api/posts/search/quickstart/recent-search

Recent Search covers recent posts within the supported time window.

## Search Introduction

Documentation:

https://docs.x.com/x-api/posts/search/introduction

## Filtered Stream

Documentation:

https://docs.x.com/x-api/posts/filtered-stream/introduction

Filtered Stream can provide near-real-time posts matching:

- keywords;
- users;
- hashtags;
- topics;
- rules.

## Post Counts

Documentation:

https://docs.x.com/x-api/posts/counts/introduction

Post counts can help estimate conversation volume over:

- minutes;
- hours;
- days.

This enables an additional contextual layer.

Example:

```text
Topic:
OpenAI model release

Conversation volume:
+340% over the previous six hours

Current environment:
Very high competition

Creator historical AI-post performance:
1.7× account baseline
```

This is far stronger than generic advice such as:

> "7 PM is a good time to post."

---

# 17. What We Cannot Observe

The product must be explicit about what X does **not** expose.

## We Cannot Know Every Viewer

Impressions provide counts.

They do **not** provide a complete list of every person who saw the post.

Therefore we cannot reconstruct the full exposed audience.

---

# 18. We Cannot Reliably Know Impression Source

The API does not publicly expose a complete breakdown like:

```text
For You       67%
Following     16%
Search         8%
Profile        5%
Reposts        4%
```

Therefore we should not tell creators:

> "X pushed exactly 17,421 impressions through For You."

unless X explicitly exposes such data in the future.

---

# 19. We Cannot See Phoenix Scores

X may internally calculate probabilities such as:

```text
P(reply | viewer, post)
P(repost | viewer, post)
P(dwell | viewer, post)
P(follow | viewer, post)
```

Our application does not have access to those internal per-viewer scores.

---

# 20. We Cannot See the Final Internal Ranking Score

X does not expose an API value such as:

```text
ranking_score = 0.87321
```

Therefore a creator-facing score must belong to **our own analytics methodology**, not be represented as X's internal score.

---

# 21. We Cannot Know the Exact Candidate Source for Every Impression

We cannot reliably determine whether a given impression came through:

- Thunder;
- Phoenix;
- SimClusters;
- another internal path.

This limits how precisely we can reverse-engineer the exact recommendation route.

---

# 22. We Cannot See the Full Negative-Signal Picture

X's recommender internally considers negative actions including:

- "not interested";
- mute;
- block;
- report;
- lack of dwell.

Repository:

https://github.com/xai-org/x-algorithm

However, normal creator analytics do not provide a full public breakdown of those signals.

This creates a real blind spot.

A post may receive strong raw attention while simultaneously producing negative recommendation signals.

Therefore raw engagement should not be treated as a perfect measure of distribution quality.

---

# 23. Open-Source Phoenix Is Not Production X

Phoenix's public repository and quickstart do **not** include X's complete production environment.

Quickstart:

https://github.com/xai-org/x-algorithm/blob/main/phoenix/QUICKSTART.md

The public code does not provide:

- X's production data;
- production checkpoints;
- production-scale orchestration;
- the entire live user graph;
- every experiment;
- all real-time feature state.

Synthetic data demonstrates the architecture and execution flow.

It does **not** reproduce X's production recommendation quality.

Therefore:

> **Running open-source Phoenix ≠ running X.**

This should be a hard product principle.

---

# 24. Change to the Original Prediction Idea

An early idea was to predict something like:

```text
Expected impressions:
7,000–12,000
```

That is likely too ambitious for the first version.

X's recommender depends heavily on the histories and preferences of potential viewers, and our application does not have the complete internal state for those viewers.

A more defensible V1 prediction is:

> **Expected performance relative to the creator's own comparable historical posts.**

Example:

```text
Distribution Outlook:
HIGHER THAN NORMAL

Expected range:
Top 20–35% of comparable posts

Confidence:
78%

Comparable sample:
47 previous engineering posts

Strongest predicted outcome:
Replies

Secondary outcome:
Profile visits
```

This is far more measurable and honest.

---

# 25. Recommended Creator-Facing Score

Avoid:

> **X Algorithm Score: 81/100**

Use something like:

## Distribution Outlook

```text
Audience Fit           Strong
Conversation Fit       Very strong
Repost Potential       Medium
Profile Conversion     Strong
Timing Fit              Above average

Overall:
Above historical baseline

Confidence:
81%
```

This score represents **our system's estimate**.

It should never be presented as X's internal ranking score.

---

# 26. Post-Publish Intelligence Is the Strongest V1 Opportunity

Once a creator publishes, we can observe actual results.

That makes post-publish intelligence much more defensible than pure pre-publish prediction.

The application can store metric snapshots at intervals such as:

```text
5 minutes
15 minutes
30 minutes
1 hour
2 hours
6 hours
12 hours
24 hours
```

Each snapshot can include:

- impressions;
- likes;
- replies;
- reposts;
- quotes;
- bookmarks;
- profile clicks;
- URL clicks;
- total engagements;
- video-retention metrics.

Because metrics are cumulative, the product can calculate deltas.

---

# 27. Useful Derived Metrics

Examples:

```text
Impression velocity
= change in impressions / minute
```

```textReply velocity
= change in replies / minute
```

```text
Profile conversion
= profile clicks / impressions
```

```text
Repost efficiency
= reposts / impressions
```

```text
Reply efficiency
= replies / impressions
```

```text
Bookmark efficiency
= bookmarks / impressions
```

These create a real distribution trajectory.

---

# 28. Example Live Distribution Analysis

Example:

```text
INITIAL DISTRIBUTION

20 minutes after publishing

Impressions:
2,840

Expected at 20m:
1,700–2,200

Performance:
+39% above comparable baseline

Replies:
2.1× expected

Reposts:
0.8× expected

Profile visits:
1.6× expected
```

Interpretation:

> This post is behaving more like conversation-driven content than redistribution-driven content.

This is genuine creator intelligence because it is based on observed behavior.

---

# 29. Creator-Specific Baselines

A global benchmark is often misleading.

Example:

Creator A:

```text
Typical impressions:
1,500
```

Creator B:

```text
Typical impressions:
120,000
```

The system should establish a personalized baseline.

Example:

```text
Creator A — engineering posts
Median impressions:
1,420

Engineering posts with images:
2,310

Sunday posts:
940

Weekday posts between 6–8 PM:
2,020
```

Recommendations should be built from creator-specific context.

---

# 30. Matched Baselines

Do not compare every post against every historical post.

A stronger baseline compares similar posts.

Potential matching dimensions:

```text
same creator
+
same content class
+
same media format
+
similar follower-count period
+
similar day/time
+
similar post type
+
similar topic environment
```

Then the system can say:

```text
Expected:
4.2k–6.1k impressions

Actual:
7.4k

Result:
Above expected range
```

Matched baselines should improve both accuracy and interpretability.

---

# 31. Major Developer-Policy Constraint

X's Developer Guidelines impose restrictions on developer use of X data.

Developer Guidelines:

https://docs.x.com/developer-guidelines

Developer Policy:

https://docs.x.com/developer-terms/policy

A major concern for our long-term architecture is the use of X data to train machine-learning models.

We should **not assume** that we can freely:

```text
collect large quantities of X data
+
engagement outcomes
+
train proprietary recommendation models
```

without checking current X developer terms, intended-use disclosures, and permission requirements.

This should be treated as a **product and legal constraint**, not merely a technical issue.

---

# 32. V1 Does Not Require Custom Model Training

The good news is that a useful first version does **not** require us to train a large proprietary model on X data.

V1 can be built using:

- deterministic analytics;
- creator-specific statistical baselines;
- historical percentiles;
- rolling averages;
- matched cohorts;
- confidence intervals;
- engagement ratios;
- content classification;
- topic-volume analysis;
- timing distributions;
- early-distribution velocity;
- semantic analysis of the creator's draft.

This is sufficient to build a legitimate MVP.

If proprietary model training becomes desirable later, we should explicitly validate the permitted use of API-derived X data before proceeding.

---

# 33. Open-Source Licensing

## Current xAI / X Algorithm Repository

Repository:

https://github.com/xai-org/x-algorithm

License:

**Apache License 2.0**

This is relatively permissive for code reuse, subject to Apache 2.0 obligations.

## Historical Twitter Algorithm Repository

Repository:

https://github.com/twitter/the-algorithm

License:

**AGPL-3.0**

This has substantially different obligations.

For the MVP:

> **Prioritize the new `xai-org/x-algorithm` repository for implementation reference.**

Use the older repository primarily for architecture/history unless we intentionally accept AGPL obligations.

## Historical ML Repository

https://github.com/twitter/the-algorithm-ml

Use primarily as historical/architectural reference.

---

# 34. X API Pricing

X currently uses pay-per-use API pricing.

Pricing documentation:

https://docs.x.com/x-api/getting-started/pricing

Pricing and endpoint credit costs can change and should always be checked against the current X Developer Console before implementation.

The product should be designed to avoid unnecessary metric polling.

A practical monitoring strategy could be:

```text
0–2 hours:
higher-frequency observation

2–12 hours:
reduced frequency

12–24 hours:
occasional snapshots

24h+:
final / low-frequency snapshot
```

This reduces API cost while preserving the most useful early-distribution signals.

---

# 35. Recommended V1 Architecture

The findings suggest four primary engines.

---

## A. Creator Baseline Engine

Flow:

```text
Connect X
↓
Retrieve creator profile
↓
Retrieve historical posts
↓
Retrieve available metrics
↓
Classify historical posts
↓
Build creator baselines
```

Potential outputs:

- topic baselines;
- timing baselines;
- format baselines;
- reply baselines;
- repost baselines;
- engagement baselines;
- profile-conversion baselines;
- URL-click baselines;
- early-velocity baselines.

---

## B. Pre-Publish Intelligence Engine

Input:

- creator draft;
- creator historical performance;
- topic;
- format;
- recent posting behavior;
- current topic/conversation environment.

Possible output:

```text
Distribution Outlook

Expected:
Above baseline

Strongest likely behavior:
Replies

Secondary behavior:
Profile visits

Confidence:
72%

Why:
- similar posts historically perform well
- timing is above creator median
- topic currently has strong conversation volume
- opening is aligned with high-reply historical posts
```

This should remain an estimate, not a claim about X's internal ranking.

---

## C. Live Distribution Monitor

After publishing:

```text
metric snapshots
↓
velocity calculations
↓
matched-baseline comparison
↓
trajectory detection
```

Example:

```text
Your post is currently outperforming
similar historical posts by 37%.
```

This is likely to become one of the strongest parts of the MVP.

---

## D. Postmortem Engine

After the main distribution window:

```text
Predicted outcome
vs
Actual outcome
```

Example:

```text
Prediction:
Top 30% of comparable posts

Actual:
Top 18%

Prediction quality:
Good
```

Then:

```text
Replies:
+83%

Profile clicks:
+41%

Reposts:
-12%

Main behavior:
Conversation + profile discovery
```

This improves the creator's understanding of what actually happened.

---

# 36. Recommended Product Claims

Avoid claims such as:

> "We cracked the X algorithm."

Avoid:

> "We know exactly how X will rank your post."

Avoid:

> "Guaranteed virality."

A credible product statement is:

> **We use your real X performance history, live platform signals, and X's publicly documented recommendation architecture to help you make better distribution decisions — then measure whether those decisions actually worked.**

---

# 37. Recommended Success Metrics

The primary technical metric for the first version should be:

> **Matched-baseline prediction accuracy**

The primary creator-facing metric should be:

> **Distribution performance relative to comparable historical posts**

Later, with controlled experiments, the product can measure:

> **Recommendation lift**

---

# 38. Correlation vs Causation

If:

```text
Historical baseline:
10,000 impressions

Post after recommendation:
14,000 impressions
```

we should **not immediately claim**:

> "Our recommendation caused a 40% lift."

The content itself may simply have been stronger.

Initially, the correct claim is:

> **This post outperformed its matched historical baseline by 40%.**

To claim actual recommendation lift, the product should eventually run controlled or carefully designed experiments.

This distinction is essential for credibility.

---

# 39. Why the X-Only Direction Still Makes Sense

The research strengthens the X-only MVP decision, but for a more precise reason.

It is **not**:

> "X is open source, therefore we can reproduce its algorithm."

The real advantage is the combination of:

- open recommendation-system architecture;
- creator-authorized metrics;
- historical post data;
- audience graph data;
- search data;
- topic-volume data;
- real-time stream access;
- semantic annotations;
- measurable post outcomes.

That combination gives us enough data to build a legitimate **distribution intelligence system** without pretending to be X itself.

---

# 40. Immediate Next Step

The next product-design task should be to define the exact V1 data model and scoring methodology.

Specifically:

1. What data is collected when a creator connects their X account?
2. Which API fields are essential vs optional?
3. What historical sample size is required?
4. How is a creator baseline calculated?
5. What constitutes a "comparable post"?
6. How is the Distribution Outlook calculated?
7. What confidence methodology should be used?
8. Which metrics should be monitored after publication?
9. At what intervals should snapshots be captured?
10. How should the system distinguish early acceleration from normal variance?
11. How should postmortems compare prediction and actual outcome?
12. Which metrics should become the MVP's north-star indicators?
13. What API costs will each creator generate?
14. Which calculations can remain deterministic/statistical in V1?
15. Which future ML ideas require explicit policy review before implementation?

---

# Reference Links

## Current X Recommendation System

- X / xAI Algorithm Repository  
  https://github.com/xai-org/x-algorithm

- Phoenix  
  https://github.com/xai-org/x-algorithm/tree/main/phoenix

- Phoenix README  
  https://github.com/xai-org/x-algorithm/blob/main/phoenix/README.md

- Phoenix Quickstart  
  https://github.com/xai-org/x-algorithm/blob/main/phoenix/QUICKSTART.md

## Historical Recommendation Architecture

- Twitter / X The Algorithm  
  https://github.com/twitter/the-algorithm

- Historical ML Models  
  https://github.com/twitter/the-algorithm-ml

## X API Documentation

- X API Overview  
  https://docs.x.com/x-api/introduction

- Post Timelines  
  https://docs.x.com/x-api/posts/timelines/introduction

- Metrics  
  https://docs.x.com/x-api/fundamentals/metrics

- Data Dictionary  
  https://docs.x.com/x-api/fundamentals/data-dictionary

- Context Annotations  
  https://docs.x.com/x-api/fundamentals/post-annotations

- Followers  
  https://docs.x.com/x-api/users/get-followers

- Users API  
  https://docs.x.com/x-api/users/introduction

- Reposted By  
  https://docs.x.com/x-api/posts/get-reposted-by

- Likes  
  https://docs.x.com/x-api/posts/likes/introduction

- Recent Search  
  https://docs.x.com/x-api/posts/search/quickstart/recent-search

- Search Introduction  
  https://docs.x.com/x-api/posts/search/introduction

- Filtered Stream  
  https://docs.x.com/x-api/posts/filtered-stream/introduction

- Post Counts  
  https://docs.x.com/x-api/posts/counts/introduction

- API Pricing  
  https://docs.x.com/x-api/getting-started/pricing

## Developer Policy / Compliance

- Developer Guidelines  
  https://docs.x.com/developer-guidelines

- Developer Policy  
  https://docs.x.com/developer-terms/policy

---

# Final Conclusion

The strongest V1 is not an "X algorithm predictor."

It is:

> **A creator-specific X distribution intelligence system that compares drafts and published posts against the creator's real historical behavior, uses live X signals to understand context, monitors post-distribution trajectories, and measures how actual results compare with expectations.**

The open-source X recommendation architecture helps us understand the system.

The X API provides enough observable data to establish personalized creator baselines.

The product's credibility comes from being explicit about uncertainty, avoiding false claims about X's private ranking state, and measuring real outcomes against statistically defensible creator-specific baselines.