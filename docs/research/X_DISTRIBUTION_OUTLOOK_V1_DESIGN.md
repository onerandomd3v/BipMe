# X Distribution Outlook — V1 Scoring, Baselines, Confidence, and Calibration

## Purpose

This document defines the current product direction for the **V1 Distribution Outlook** of the X-only creator discovery and distribution intelligence product.

The central principle is:

> **Do not build an opaque universal score. Build a creator-specific matched-baseline prediction system.**

The product should estimate how a draft is likely to perform **relative to the creator's own comparable historical posts**, explain the main factors behind that estimate, distinguish prediction from recommendation, and then compare the prediction against real post-publish outcomes.

The system should be designed around:

- creator-specific baselines;
- comparable-post retrieval;
- content understanding;
- timing and format fit;
- live X context;
- explainable confidence;
- post-publish trajectory monitoring;
- prediction-vs-outcome calibration;
- creator-era weighting.

---

# 1. Core V1 Prediction Flow

The V1 should follow this conceptual flow:

```text
New Draft
   ↓
Understand the post
   ↓
Find historically comparable posts
   ↓
Measure how those posts performed
   ↓
Adjust for current conditions
   ↓
Estimate expected relative performance
   ↓
Explain what is helping or hurting the draft
```

The system should avoid asking:

> "Is this a good X post?"

Instead, it should ask:

> **"How does this draft compare with what historically works for this specific creator?"**

That makes the product much more defensible and personalized.

---

# 2. Example Draft Analysis

Suppose a creator writes:

> "We finally fixed a nasty Redis thundering-herd problem in production. Here's what caused it and how we solved it..."

The system might identify:

```text
Topic:
Backend / distributed systems

Format:
Technical explanation

Intent:
Educational + personal experience

Creator familiarity:
High

Closest historical cluster:
Engineering / building posts

Comparable historical posts:
42
```

The system should then evaluate this post against those historical comparables rather than against all posts on X.

---

# 3. Distribution Outlook Components

The V1 Distribution Outlook should be composed of multiple interpretable components rather than one unexplained score.

The recommended first set is:

1. Creator–Topic Fit
2. Format Fit
3. Timing Fit
4. Current Conversation Fit
5. Historical Outcome Fit

Each component should have:

- a result;
- supporting evidence;
- a confidence contribution;
- an explanation.

---

# 4. Creator–Topic Fit

## Question

> **Does this creator historically perform well when posting about this subject?**

This is important because creators are not equally established across all topics.

A creator's audience may strongly associate them with:

- backend engineering;
- AI;
- startups;
- fashion;
- design;
- music;
- football;
- creator education;
- other niches.

A post on an unfamiliar topic may perform differently even if the writing itself is strong.

Example:

```text
Creator–Topic Fit:
Strong

Reason:
Your backend and engineering posts historically rank
in the top 28% of your content.
```

This captures:

- creator authority;
- audience expectation;
- creator-topic history;
- historical audience response.

The system should not assume that a universally popular topic is automatically a strong fit for a given creator.

---

# 5. Why Creator–Topic Fit Matters

Consider two creators posting about Kubernetes.

Creator A:

```text
Historical niche:
Backend engineering

Comparable technical posts:
86

Audience engagement:
Consistently strong
```

Creator B:

```text
Historical niche:
Fashion and lifestyle

Comparable technical posts:
2

Audience engagement:
Unknown
```

The same Kubernetes draft should not receive the same distribution outlook for both creators.

The creator's historical relationship with the topic is part of the prediction.

---

# 6. Format Fit

## Question

> **How does this content format historically perform for this creator and this type of topic?**

Possible formats include:

- plain text;
- image;
- video;
- link post;
- thread;
- quote post;
- reply;
- poll, if relevant;
- mixed media.

Example:

```text
Format Fit:
Medium

Your technical posts with diagrams historically receive:

+34% bookmarks
+21% reposts

compared with text-only technical posts.
```

This enables creator-specific recommendations.

Instead of generic advice such as:

> "Images increase engagement."

the product can say:

> **"Your own technical posts with diagrams historically receive more bookmarks and reposts than your text-only technical posts."**

That is significantly more useful.

---

# 7. Format Recommendations Must Be Evidence-Based

A format recommendation should be tied to creator history.

Example:

```text
Prediction:
Above baseline

Current format:
Text only

Recommendation:
Add a visual explanation.

Reason:
Comparable technical posts with diagrams historically receive
higher repost and bookmark rates for your account.
```

The recommendation should not exist merely because an AI can generate one.

It should come from observed creator-specific evidence where possible.

---

# 8. Timing Fit

## Question

> **How does this proposed posting time compare with the creator's own historical performance for similar content?**

Avoid universal advice such as:

> "The best time to post on X is 7 PM."

Instead:

```text
Timing Fit:
Strong

For comparable engineering posts:

18:00–20:00 WAT
Median relative performance:
+19%

12:00–15:00 WAT
Median relative performance:
-8%
```

This is creator-specific and topic-aware.

Timing analysis should eventually consider:

- day of week;
- hour;
- creator timezone;
- content type;
- topic cluster;
- audience-era;
- historical sample size;
- variance.

---

# 9. Current Conversation Fit

## Question

> **What is happening around this topic on X right now?**

The system may inspect recent X conversation activity around relevant terms.

For a Redis post, that could include:

```text
Redis
caching
distributed systems
NestJS
```

Then estimate:

```text
Topic activity:
Moderately elevated

Competition:
Normal

Momentum:
Increasing
```

This should only act as a contextual signal.

The product should not assume:

> "Topic is trending → post will succeed."

Instead, live conversation context should slightly adjust an already creator-specific prediction.

---

# 10. Historical Outcome Fit

## Question

> **How do genuinely comparable historical posts normally perform for this creator?**

This is the core statistical foundation of the V1.

Example:

```text
Comparable posts:
42

Median impressions:
8,420

25th percentile:
5,100

75th percentile:
13,900

Median reply rate:
1.8%

Median repost rate:
0.9%

Median profile conversion:
3.2%
```

These historical outcomes create a creator-specific distribution prior.

The system can then estimate whether the new draft appears likely to perform:

- below normal;
- around baseline;
- above normal;
- within a historical percentile band.

---

# 11. Recommended Distribution Outlook Presentation

Avoid this:

```text
X Algorithm Score:
87/100
```

The product does not know X's internal ranking score.

Instead, use:

```text
DISTRIBUTION OUTLOOK

Expected performance:
Above your normal baseline

Confidence:
76%

Matched historical posts:
42

Expected percentile:
Top 25–40% of comparable posts

Likely strongest behavior:
Replies

Secondary behavior:
Profile visits

Creator–Topic Fit:
Strong

Format Fit:
Medium

Timing Fit:
Strong

Conversation Fit:
Moderate
```

This is more honest and more interpretable.

---

# 12. Explain Why

Every outlook should have a concise explanation.

Example:

```text
WHY

↑ Your audience historically responds strongly
  to posts about systems you've personally built.

↑ Current posting window performs well for
  technical content.

↑ The topic matches one of your strongest
  historical creator clusters.

↓ Text-only technical explanations historically
  receive fewer reposts than ones with visual context.
```

The goal is not only to produce a prediction.

It is to help the creator understand the reasoning behind it.

---

# 13. Prediction and Recommendation Must Be Separate

This distinction should be explicit in the product.

## Prediction

> **How is this draft likely to perform?**

Example:

```text
Prediction:
Above baseline
```

## Recommendation

> **What change may improve the expected outcome?**

Example:

```text
Recommendation:
Add a visual explanation.

Expected reason:
Historically improves redistribution for
your technical content.
```

The creator should always be free to:

- keep the draft unchanged;
- apply the recommendation;
- ignore the recommendation;
- compare outcomes later.

This separation is essential for learning whether recommendations are actually useful.

---

# 14. Why the Separation Matters

If the system rewrites every draft automatically, then it becomes difficult to know whether:

- the original draft was already strong;
- the recommendation helped;
- the recommendation hurt;
- another factor caused the result.

By separating prediction from recommendation, we preserve a clearer experimental record.

Conceptually:

```text
Original draft
↓
Prediction
↓
Optional recommendation
↓
Creator decision
↓
Published post
↓
Observed outcome
```

This becomes useful later for measuring recommendation effectiveness.

---

# 15. Post-Publish Prediction vs Reality

Once the creator publishes, the system should compare the original prediction against the actual outcome.

Example prediction:

```text
Expected percentile:
Top 25–40%
```

Actual result after the observation window:

```text
Actual:
Top 18%
```

Record:

```text
Prediction:
Above baseline

Actual:
Above baseline

Direction:
Correct

Expected percentile midpoint:
32.5%

Actual percentile:
18%

Calibration error:
14.5 percentile points
```

This creates a measurable prediction record.

---

# 16. Prediction Misses Must Also Be Recorded

Example:

```text
Predicted:
Top 20%

Actual:
Bottom 45%
```

That is a bad miss.

The system should record it rather than hiding it.

Over time, these records allow the product to understand:

- where predictions are strong;
- where predictions are weak;
- which topics are hard to predict;
- which formats have high variance;
- whether confidence scores are calibrated.

---

# 17. Calibration

The system should continuously measure whether its confidence and expected ranges are realistic.

For example:

If the system repeatedly says:

```text
Confidence:
80%
```

then outcomes in that category should be correct roughly at the expected rate.

Confidence should not be decorative UI.

It should come from measurable data quality and historical predictability.

---

# 18. Confidence Should Come From Evidence

A high-confidence prediction might have:

```text
Comparable posts:
83

Recent comparable examples:
31

Topic similarity:
High

Format similarity:
High

Historical variance:
Low
```

A low-confidence prediction might have:

```text
Comparable posts:
6

Creator rarely discusses this topic

No similar recent format

Historical variance:
High
```

Then:

```text
Confidence:
41%
```

means something real.

---

# 19. Possible Confidence Inputs

Confidence can eventually incorporate:

- number of comparable posts;
- number of recent comparable posts;
- semantic similarity;
- topic-cluster similarity;
- format similarity;
- timing similarity;
- creator-era relevance;
- historical outcome variance;
- completeness of metrics;
- age of historical data;
- current topic volatility;
- availability of creator-authorized private metrics.

The exact formula can be defined later.

For V1, it should remain transparent and deterministic where possible.

---

# 20. Creator Eras

The archive discussion introduces an important requirement:

> **A creator's entire account history should not be treated as one homogeneous statistical population.**

A creator may change significantly over time.

Example:

```text
Era 1 — 2018–2020
Student / learning programming

Era 2 — 2021–2023
Software engineering

Era 3 — 2024–2026
Engineering + startup founder
```

Their:

- audience;
- follower count;
- niche;
- content quality;
- network;
- posting style;
- platform environment

may all change.

Therefore old posts should remain useful but receive lower predictive weight where appropriate.

---

# 21. Creator-Era Weighting

Comparable-post retrieval should consider whether an old post belongs to the creator's current era.

Conceptually:

```text
Comparable score
=
semantic similarity
× format similarity
× timing similarity
× recency weight
× creator-era relevance
```

Recent posts from the current creator era should generally receive greater predictive weight than very old posts.

Historical archive data provides context.

Recent API data should normally provide stronger predictive relevance.

---

# 22. Why Older Data Still Matters

Older posts should not simply be discarded.

They can help with:

- detecting long-term topic authority;
- understanding creator evolution;
- identifying recurring content themes;
- building semantic clusters;
- expanding comparable-post samples where recent data is sparse.

The system should use old data as context, not allow it to dominate current prediction.

---

# 23. V1 Intelligence Stack

The current architecture can be summarized as:

```text
                Creator Data
          ┌──────────┴──────────┐
          │                     │
      X Archive              X API
          │                     │
          └──────────┬──────────┘
                     ▼
              Creator History
                     │
              Content Clusters
                     │
               Creator Eras
                     │
           Statistical Baselines
                     │
                     ▼
New Draft ──→ Comparable Post Retrieval
                     │
             ┌───────┼────────┐
             ▼       ▼        ▼
           Topic   Format   Timing
             │       │        │
             └───────┼────────┘
                     +
                Live X Context
                     │
                     ▼
           Distribution Outlook
                     │
               Recommendation
                     │
                  Publish
                     │
                     ▼
            Live Performance
                     │
                     ▼
               Postmortem
                     │
                     ▼
              Calibration
```

This should be treated as the current conceptual V1 intelligence architecture.

---

# 24. What Makes This Different From Generic AI Social-Media Tools

The product should not operate primarily from generic advice such as:

- use a strong hook;
- add an image;
- post at 7 PM;
- ask a question;
- use hashtags.

Instead, recommendations should increasingly be grounded in:

- this creator's history;
- this creator's audience behavior;
- this creator's topic clusters;
- this creator's successful formats;
- this creator's recent era;
- current X topic conditions;
- comparable-post outcomes.

The product should be able to say:

> **Your own technical posts that explain something you personally built historically outperform pure industry commentary.**

That is creator-specific intelligence.

---

# 25. Recommended V1 Output Model

For each draft, the product should eventually produce structured output similar to:

```text
DISTRIBUTION OUTLOOK

Overall:
Above baseline

Expected percentile:
Top 25–40%

Confidence:
76%

Comparable posts:
42

Creator–Topic Fit:
Strong

Format Fit:
Medium

Timing Fit:
Strong

Current Conversation Fit:
Moderate

Likely strongest behavior:
Replies

Secondary behavior:
Profile visits
```

Then:

```text
WHY
+ Strong match with one of your highest-performing topic clusters
+ Similar posts historically generate strong replies
+ Proposed timing performs above median for this content type
- Text-only format historically underperforms visual technical posts
```

Then, separately:

```text
OPTIONAL RECOMMENDATION

Add a visual explanation.

Reason:
Your comparable technical posts with diagrams historically receive
more reposts and bookmarks.
```

This keeps prediction, explanation, and recommendation logically separate.

---

# 26. Postmortem Output Model

After the main observation window:

```text
POSTMORTEM

Prediction:
Top 25–40%

Actual:
Top 18%

Direction:
Correct

Prediction accuracy:
Good

Impressions:
+36% vs matched baseline

Replies:
+83%

Profile clicks:
+41%

Reposts:
-12%

Main observed behavior:
Conversation + profile discovery
```

The postmortem should explain:

- what the system predicted;
- what actually happened;
- whether the direction was correct;
- where the prediction missed;
- what the creator can learn from the outcome.

---

# 27. Current Primary Technical Metric

The V1 technical focus should be:

> **Matched-baseline prediction accuracy**

This measures whether the system can correctly estimate relative performance against comparable creator history.

Important submetrics may include:

- direction accuracy;
- percentile error;
- confidence calibration;
- expected-range coverage;
- per-topic error;
- per-format error;
- per-creator-era error.

---

# 28. Current Primary User Metric

The creator-facing metric should remain:

> **Distribution performance relative to comparable historical posts.**

This is more honest than claiming causal lift in the early product.

Example:

> "This post outperformed your matched historical baseline by 37%."

That is measurable without overstating causality.

---

# 29. Recommendation Lift Comes Later

Eventually, the product may measure:

> **Recommendation lift**

But that requires stronger experimentation.

If:

```text
Historical baseline:
10,000 impressions

Recommended post:
14,000 impressions
```

we cannot immediately conclude:

> "Our recommendation caused +40%."

The post itself may have been stronger.

The correct early statement is:

> **This post outperformed its matched historical baseline by 40%.**

Causal claims require controlled experiments or stronger evaluation design.

---

# 30. Key Design Principle

The V1 should avoid becoming an AI content coach with arbitrary confidence values.

It should behave more like a **creator-specific distribution analytics and prediction system**.

Every major output should ideally be traceable to:

- comparable historical data;
- statistical baseline;
- semantic similarity;
- timing context;
- format context;
- current platform context;
- measured uncertainty.

That is what creates trust.

---

# 31. Immediate Next Design Problem

The next major design problem is:

> **What exactly constitutes a "comparable post"?**

This is likely to be one of the most important determinants of prediction accuracy.

If the system chooses poor historical comparables, then:

- baselines will be misleading;
- percentile estimates will be wrong;
- timing insights will be noisy;
- format recommendations may be invalid;
- confidence may be overstated.

Comparable-post retrieval therefore deserves its own explicit design.

The next work should define:

1. Which attributes make two posts comparable?
2. How should semantic topic similarity be measured?
3. How should post format affect similarity?
4. How should creator era affect similarity?
5. How much should recency matter?
6. How should posting time/day affect matching?
7. How should replies, threads, quote posts, and standalone posts be separated?
8. How should follower-count changes be normalized?
9. How should current topic conditions affect matching?
10. How many comparable posts are required?
11. What happens when the creator has too few comparable posts?
12. How should similarity scores be weighted?
13. How should outliers be handled?
14. How should the system prevent stale historical posts from dominating?
15. How should comparable-post quality affect confidence?

This matched-post retrieval layer should be designed before the V1 scoring formula is finalized.

---

# Final Principle

The strongest V1 is:

> **A creator-specific, matched-baseline distribution outlook system that explains its evidence, exposes uncertainty, separates predictions from recommendations, and learns from real post outcomes.**

The next step is to define the comparable-post retrieval system that powers those baselines.

---

# 32. Comparable-Post Retrieval — Core Definition

Comparable-post retrieval is one of the most important determinants of prediction quality.

The system should **not** define a comparable post as merely:

> another historical post by the same creator that contains similar words.

A stronger definition is:

> **A historical post that was published under sufficiently similar content, structural, creator-state, and distribution conditions that its performance is useful for estimating the new draft's likely performance.**

Every historical post should therefore be represented as a structured **Post Profile**.

Conceptually:

```text
Post
│
├── Semantic content
├── Topic cluster
├── Intent
├── Format
├── Structural features
├── Creator era
├── Account state
├── Timing
├── Conversation context
└── Observed outcome
```

A new draft receives the same representation except, naturally, it has no observed outcome yet.

---

# 33. Semantic Similarity Should Be the Strongest Retrieval Signal

The system must understand meaning, not just keyword overlap.

Example draft:

> "We finally fixed a Redis thundering-herd problem in production."

Potential historical comparables include posts about:

- Redis;
- cache invalidation;
- backend scaling;
- distributed systems;
- production incidents;
- database overload.

Posts about:

- hackathons;
- founder updates;
- career reflections;
- unrelated AI news

should rank much lower.

Two posts may be semantically similar even if their exact vocabulary differs.

Example:

```text
"We stopped 2,000 concurrent requests from hammering Postgres
after Redis went down."
```

and:

```text
"Here's how we prevented a cache miss from becoming a database
thundering herd."
```

These should be treated as highly similar.

A semantic similarity value can be represented conceptually as:

```text
semantic_similarity ∈ [0,1]
```

This should be one of the highest-weighted features in comparable-post scoring.

---

# 34. Topic Clusters Should Complement Semantic Similarity

Semantic similarity alone can sometimes over-match content that discusses similar concepts but serves a different creator purpose.

Maintain creator-specific topic clusters such as:

```text
Backend Engineering
AI / LLMs
Startup / Building in Public
Hackathons
Developer Journey
Career / Learning
```

A new Redis post may land inside:

```text
Backend Engineering
```

Historical posts inside that cluster receive an additional boost.

A useful hierarchy is:

```text
same exact subtopic       → strongest
same creator cluster      → strong
adjacent creator cluster  → moderate
unrelated cluster         → weak
```

This also improves explainability:

> "We compared this draft against 38 posts from your Backend Engineering cluster."

---

# 35. Intent Is a Major Similarity Dimension

Two posts about the same topic may behave very differently depending on their purpose.

Example:

```text
A:
"What is Redis and why would you use it?"

B:
"Redis went down in production. Here's how we recovered."

C:
"Redis 9 was released today."
```

These represent different intents:

```text
A → educational
B → personal experience / technical story
C → news / commentary
```

The system should classify intent using categories such as:

- educational;
- personal experience;
- announcement;
- opinion;
- news commentary;
- question;
- story;
- tutorial;
- launch;
- achievement;
- conversation starter;
- promotional.

A new technical story should primarily compare with previous technical stories, not every technical post.

---

# 36. Format and Post Topology Should Constrain Matching

Different X post forms have different distribution behavior.

At minimum, the system should represent:

| Dimension | Examples |
|---|---|
| Post topology | standalone, reply, quote, thread root |
| Media | none, image, video, GIF |
| Link | no external link, external link |
| Length class | short, medium, long |
| Thread structure | single post, multi-post thread |
| Interaction mechanism | question, poll, etc. where available |

Important default rule:

> **Standalone posts should primarily compare with standalone posts. Replies should primarily compare with replies. Thread roots should primarily compare with thread roots.**

The system may relax this only when the comparable pool is too small.

---

# 37. Creator Era Should Strongly Affect Similarity

The same raw performance means different things at different stages of a creator's account.

Example:

```text
2021:
1,000 followers

2024:
14,000 followers

2026:
85,000 followers
```

A 3,000-impression post in 2021 is not directly comparable to a 3,000-impression post in 2026.

Every historical post should therefore belong to a **creator era**.

An era represents a period where the creator's:

- audience size;
- niche;
- posting behavior;
- engagement baseline;
- public identity

were reasonably stable.

Current-era posts should receive the strongest predictive weight.

Older-era posts remain useful but should be discounted.

---

# 38. Account Scale Should Be Normalized

Raw impressions should not be compared without considering creator size.

Example:

```text
Post A
Followers at publication: 12,000
Impressions: 24,000

Post B
Followers at publication: 60,000
Impressions: 40,000
```

Raw reach suggests Post B performed better.

Relative distribution may suggest Post A was stronger.

A useful supporting metric is:

```text
impression_to_follower_ratio
=
impressions / followers_at_publish
```

This should **not** be the sole normalization factor because X can distribute posts far beyond followers.

Instead, follower count should be one contextual variable in a broader normalization model.

Where exact historical follower counts are unavailable, the system may need era-level or approximate scale buckets rather than fabricated precision.

---

# 39. Timing Should Affect Similarity Without Dominating It

Two otherwise similar posts published at very different times may perform differently.

Relevant timing dimensions include:

```text
day of week
hour of day
creator timezone
weekday vs weekend
```

However, timing should generally have a lower retrieval weight than:

- topic;
- semantic similarity;
- intent;
- format;
- creator era.

The system should avoid matching unrelated posts simply because they were published at the same hour.

---

# 40. Conversation Environment Should Be Represented

Historical comparisons can be distorted when one post was published during a major live event and another during a quiet period.

Example:

A normal OpenAI post during a quiet week is not necessarily comparable to an OpenAI post published during a major model launch.

Where possible, represent topic conditions such as:

```text
Low topic activity
Normal topic activity
Elevated topic activity
Extreme event / breaking news
```

This can be estimated from available X search/count data.

In V1 this can remain coarse.

Even a rough classification can help distinguish:

> evergreen content

from:

> event-driven content.

---

# 41. Recency Should Be Separate From Creator Era

Even within the same era, newer posts usually provide stronger predictive evidence than older ones.

Reasons include:

- audience composition changes;
- creator quality changes;
- platform behavior changes;
- topic interest changes.

Use a recency decay.

Conceptually:

```text
recency_weight = decay(age)
```

An illustrative piecewise policy could be:

```text
0–30 days       very high
31–90 days      high
3–6 months      medium-high
6–12 months     medium
1–2 years       low
2+ years        context only
```

These boundaries are placeholders and should later be validated empirically.

---

# 42. Initial Comparable Score

V1 does not need a trained ML ranker.

A deterministic weighted scoring system is sufficient to start.

Illustrative formula:

```text
ComparableScore =
    0.30 × SemanticSimilarity
  + 0.18 × TopicClusterMatch
  + 0.15 × IntentMatch
  + 0.12 × FormatMatch
  + 0.10 × CreatorEraMatch
  + 0.06 × RecencyWeight
  + 0.04 × TimingMatch
  + 0.03 × AudienceScaleMatch
  + 0.02 × ConversationContextMatch
```

These weights are **illustrative**, not final.

The more important principle is the relative priority:

```text
CONTENT
   >
INTENT
   >
FORMAT
   >
CREATOR STATE
   >
TIME
```

We want semantically and behaviorally similar posts before posts that merely share a posting hour.

---

# 43. Use Two-Stage Retrieval

Comparable-post retrieval should use two stages.

## Stage 1 — Candidate Retrieval

Retrieve a broader historical candidate set, perhaps:

```text
50–200 posts
```

using broad constraints such as:

```text
same creator
similar semantic content
compatible topology
reasonable creator era
```

## Stage 2 — Fine Ranking

Rank the candidate set using the full comparable score:

```text
semantic similarity
topic
intent
format
creator era
recency
timing
account scale
conversation context
```

Then select the final matched set:

```text
Top 20–50 comparable posts
```

depending on data quality and sample size.

This is more efficient and more controllable than evaluating every historical post equally for every draft.

---

# 44. Hard Filters vs Soft Weights

Some dimensions should be treated as hard or near-hard constraints.

Potential hard-filter conditions:

```text
wrong creator
incompatible post topology
corrupt or incomplete historical record
insufficient outcome metrics
deleted/unusable record
invalid creator-era classification
```

Potential soft-weight dimensions:

```text
semantic similarity
topic similarity
intent
format details
recency
timing
audience scale
conversation context
```

Hard filters prevent obviously misleading historical matches.

Soft weights allow controlled flexibility.

---

# 45. Minimum Comparable-Post Thresholds

The system must not pretend to have strong personalized evidence when the creator lacks enough comparable history.

A possible V1 evidence ladder:

```text
20+ strong comparables
→ Personalized baseline

8–19 strong comparables
→ Limited personalized baseline

3–7 strong comparables
→ Weak creator evidence

<3 strong comparables
→ Cold-topic mode
```

In cold-topic mode, the UI should say something like:

```text
Historical evidence:
Insufficient

You rarely publish about this topic.

Confidence:
Low
```

rather than fabricating a strong percentile prediction.

---

# 46. Progressive Fallback

When the initial matching level produces too few comparables, broaden gradually.

Example:

```text
Level 1
same subtopic + intent + format + current era

↓ insufficient

Level 2
same topic cluster + intent + format + current era

↓ insufficient

Level 3
same topic cluster + compatible format + current era

↓ insufficient

Level 4
same topic cluster + compatible recent posts

↓ insufficient

Level 5
general recent creator baseline
```

The system should record and expose which fallback level was required.

Example:

```text
Comparable quality:
Moderate

Reason:
Only 7 closely matched technical-story posts were available,
so 12 broader engineering posts were also included.
```

This gives the creator visibility into evidence quality.

---

# 47. Robust Statistics Should Power the Baseline

Creator performance is usually heavy-tailed.

Example:

```text
5k
7k
6k
8k
9k
7k
320k
6k
```

A simple average is badly distorted by the viral outlier.

Use robust statistics such as:

- median;
- percentiles;
- interquartile range;
- median absolute deviation;
- trimmed means.

Example:

```text
Median:
7,000

P25:
5,800

P75:
9,200
```

is much more representative than:

```text
Average:
46,000
```

when one post went viral.

---

# 48. Viral Outliers Should Be Preserved but Separated

Viral posts are important data.

They simply should not redefine the normal baseline.

Possible labels:

```text
Normal distribution
Strong outperformance
Extreme outlier
```

Extreme outliers can later be analyzed separately:

> "Why did this post escape your normal distribution range?"

That may become a powerful future diagnostic feature.

---

# 49. Negative Outliers Need Similar Treatment

Extremely poor historical outcomes may also be abnormal.

Example:

```text
Normal:
5k–10k impressions

One post:
300 impressions
```

Potential causes include:

- posting error;
- visibility restriction;
- deletion;
- platform anomaly;
- unusual external conditions;
- data-quality problems.

The baseline builder should identify pathological negative outliers instead of blindly treating them as normal evidence.

---

# 50. Outcome Vectors Should Remain Multi-Dimensional

Comparable posts should not be evaluated only by impressions.

Preserve outcome vectors such as:

```text
impressions
likes
replies
reposts
quotes
bookmarks
profile clicks
URL clicks
follows where observable
video completion
```

This enables separate predictions for:

```text
Reach outlook
Conversation outlook
Redistribution outlook
Conversion outlook
```

rather than collapsing every creator objective into a single engagement number.
---

# 51. Creator Goal Can Later Affect Outcome Weighting

A creator may care about different outcomes.

Example goals:

```text
"I want discussion."
"I want distribution."
"I want people to visit my product."
```

Then the same comparable set can be evaluated differently.

For discussion:

```text
replies
conversation depth
```

For distribution:

```text
reposts
quotes
impressions
```

For conversion:

```text
profile clicks
URL clicks
follows
```

This does not need to become a full V1 user-facing workflow immediately, but the data model should support it.

---

# 52. Comparable Retrieval Architecture

The comparable-post layer can now be represented as:

```text
                   NEW DRAFT
                       │
                       ▼
              Post Understanding
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
    Semantic         Intent          Format
   Embedding       Classification   Classification
       │               │               │
       └───────────────┼───────────────┘
                       ▼
              Candidate Retrieval
                       │
             Historical Creator DB
                       │
                       ▼
                  ~100 posts
                       │
                       ▼
                Hard Filtering
                       │
      topology / metrics / creator era
                       │
                       ▼
                Fine Similarity
                       │
       semantic + topic + intent + format
       + era + recency + timing + context
                       │
                       ▼
                 Ranked Matches
                       │
                    Top 20–50
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
    Robust Baseline           Match Quality
 median / P25 / P75       sample / similarity /
  outcome vectors              variance
          │                         │
          └────────────┬────────────┘
                       ▼
                Confidence Model
                       │
                       ▼
              Distribution Outlook
```

This is now the core matched-baseline architecture.

---

# 53. Show the Creator Why Posts Were Selected

The creator should be able to inspect a small number of top comparables.

Example:

```text
MOST COMPARABLE POSTS

1. "How we prevented PostgreSQL overload..."
   Similarity: Very high
   Same topic cluster
   Same technical-story format
   3 months ago

2. "What Redis failure taught us..."
   Similarity: High
   Same topic cluster
   Same creator era
   Same text format
```

This provides two benefits:

1. The creator understands the prediction.
2. The creator can detect obviously wrong matches.

A future version may allow feedback such as:

> "This post is not actually comparable."

That feedback could later improve retrieval quality.

---

# 54. Comparable Quality Should Feed Confidence

Prediction confidence should depend partly on the strength of the comparable set.

Relevant inputs include:

```text
number of strong comparables
average similarity score
semantic similarity
intent agreement
format agreement
creator-era consistency
recency
historical variance
fallback level used
metric completeness
```

Example:

```text
Comparable quality:
High

Strong matches:
31

Median semantic similarity:
0.86

Current-era matches:
27

Historical variance:
Low
```

This should produce higher confidence than:

```text
Comparable quality:
Weak

Strong matches:
4

Fallback level:
4

Historical variance:
High
```

---

# 55. Refined Definition of Comparable

The system should not ask:

> **"Which old posts look like this draft?"**

It should ask:

> **"Which historical posts occurred under the closest combination of content, intent, format, creator state, and distribution conditions?"**

That is the working definition of a **comparable post**.

---

# 56. Next Design Task — Post Profile / Feature Schema

The next logical design task is to define the actual **Post Profile schema**.

We need to specify exactly what fields are stored for:

- every historical X post;
- every newly published post;
- every pre-publish draft.

That schema must give the comparable-post engine everything it needs for:

- semantic retrieval;
- topic clustering;
- intent matching;
- format matching;
- creator-era filtering;
- account-scale normalization;
- timing comparison;
- conversation-context comparison;
- outcome-vector storage;
- confidence calculation.

The next design document should therefore answer:

1. Which raw X fields should be stored?
2. Which normalized fields should be derived?
3. Which semantic features should be generated?
4. How should topic clusters be represented?
5. How should intent be represented?
6. How should format/topology be encoded?
7. How should creator era be stored?
8. How should follower/account scale at publication be represented?
9. How should timing features be normalized?
10. How should live conversation context be stored?
11. Which performance metrics belong in the outcome vector?
12. Which fields are unavailable for drafts and should remain nullable?
13. How should X archive records and live API records be deduplicated?
14. Which fields should be versioned when our classifiers change?
15. Which fields are required for retrieval vs analytics only?

The comparable-post engine should not be finalized before this schema is defined.

---

# 57. Post Profile / Feature Schema — Canonical Representation

The **Post Profile** is the canonical representation used by the intelligence system.

It should power:

- comparable-post retrieval;
- creator baselines;
- Distribution Outlook;
- confidence;
- post-publish monitoring;
- postmortems;
- archive import;
- future experimentation.

The Post Profile must **not** simply mirror an X API payload.

Instead, the architecture should separate source data from the normalized and derived features used by the product.

Conceptually:

```text
Raw / Source Data
        ↓
Normalized Post
        ↓
Derived Post Profile
        ↓
Comparable Retrieval
```

The raw layer preserves what X or the archive actually returned.

The **Post Profile** contains the normalized representation our intelligence system needs.

---

# 58. Unified Representation for Drafts and Published Posts

Drafts and historical posts should use essentially the same feature representation.

Conceptually:

```text
PostProfile
├── identity
├── provenance
├── content
├── semantics
├── topology
├── media
├── structure
├── timing
├── creatorState
├── creatorEra
├── conversationContext
├── retrievalMetadata
└── outcome        // null for drafts
```

This means comparable retrieval becomes:

```text
Draft PostProfile
        ↕
Historical PostProfiles
```

rather than maintaining separate incompatible representations.

---

# 59. Identity and Provenance

Every profile should record where the data came from.

Illustrative schema:

```ts
{
  id: UUID,

  creatorId: UUID,

  xPostId: string | null,

  source:
    | "x_api"
    | "x_archive"
    | "draft",

  sourceRecordId: string | null,

  status:
    | "draft"
    | "published"
    | "deleted"
    | "unknown",

  importedAt: Date | null,

  createdAt: Date | null,

  updatedAt: Date,

  profileSchemaVersion: string,

  contentHash: string
}
```

## Why `source` matters

An archive post and API post may represent the same X post.

The preferred deduplication key should therefore be:

```text
x_post_id
```

where available.

`contentHash` can act as a supporting key for older archive records or imperfect identifiers.

---

# 60. Preserve Raw Content Correctly

The system should preserve the creator's actual content before preprocessing.

Illustrative schema:

```ts
content: {
  rawText: string,

  normalizedText: string,

  xDetectedLanguage: string | null,

  effectiveLanguage: string | null,

  displayTextStart: number | null,
  displayTextEnd: number | null,

  isLongForm: boolean,

  xNoteTweetText: string | null,

  editHistoryPostIds: string[]
}
```

Where long-form post text exists, the intelligence layer should analyze the effective full text rather than accidentally relying on a truncated representation.

Conceptually:

```text
effectiveText =
xNoteTweetText ?? rawText
```

---

# 61. Entities

Store normalized post entities separately.

Illustrative representation:

```ts
entities: {
  hashtags: string[],
  cashtags: string[],

  mentions: Array<{
    username: string,
    userId?: string
  }>,

  urls: Array<{
    url: string,
    expandedUrl?: string,
    domain?: string
  }>,

  xAnnotations: Array<{
    type: string,
    normalizedText: string,
    probability?: number
  }>
}
```

This lets the retrieval and analytics systems use structural information without repeatedly reparsing the post.

---

# 62. X Context Annotations

Where available, preserve X's semantic context annotations.

Illustrative representation:

```ts
xContextAnnotations: Array<{
  domainId: string,
  domainName: string,

  entityId: string | null,
  entityName: string | null
}>
```

Example:

```json
[
  {
    "domainId": "131",
    "domainName": "Unified Twitter Taxonomy",
    "entityId": "...",
    "entityName": "Artificial intelligence"
  }
]
```

These annotations should be treated as **additional evidence**, not the sole source of semantic classification.

They may also be less reliable or complete for some African languages and regional language mixtures.

---

# 63. Our Semantic Representation

The product should generate its own semantic profile.

This is one of the most important feature groups for comparable retrieval.

Illustrative schema:

```ts
semantics: {
  embedding: vector,

  embeddingModel: string,
  embeddingVersion: string,

  primaryTopicClusterId: UUID | null,

  secondaryTopicClusterIds: UUID[],

  subtopics: string[],

  normalizedTopics: Array<{
    label: string,
    confidence: number
  }>,

  semanticEntities: Array<{
    label: string,
    type: string,
    confidence: number
  }>,

  semanticComputedAt: Date
}
```

Example:

```text
Primary cluster:
Backend Engineering

Subtopics:
Redis
Caching
Distributed Systems
PostgreSQL
Production Reliability
```

The embedding supports semantic retrieval.

The creator-specific cluster adds historical and audience context.

---

# 64. Intent Representation

Intent should be multi-label rather than a single categorical value.

A post may simultaneously be:

```text
technical explanation
+
personal experience
```

Illustrative representation:

```ts
intent: {
  primary: string,

  labels: {
    educational: number,
    personalExperience: number,
    announcement: number,
    opinion: number,
    newsCommentary: number,
    question: number,
    story: number,
    tutorial: number,
    launch: number,
    achievement: number,
    conversationStarter: number,
    promotional: number
  },

  classifierVersion: string
}
```

Example:

```text
educational            0.91
personalExperience     0.84
story                   0.62
announcement            0.08
promotional             0.03
```

This gives the retrieval system a much richer similarity signal than:

```text
intent = educational
```

---

# 65. Post Topology

Topology must be explicit because replies, quotes, threads, reposts, and standalone posts behave differently.

Illustrative schema:

```ts
topology: {
  type:
    | "standalone"
    | "reply"
    | "quote"
    | "thread_root"
    | "thread_member"
    | "repost",

  conversationId: string | null,

  inReplyToUserId: string | null,

  referencedPosts: Array<{
    xPostId: string,
    type:
      | "replied_to"
      | "quoted"
      | "retweeted"
  }>,

  threadId: string | null,

  threadPosition: number | null,

  threadLength: number | null,

  replySettings:
    | "everyone"
    | "mentioned_users"
    | "followers"
    | null,

  communityId: string | null
}
```

The comparable engine should primarily compare compatible topologies.

---

# 66. Format

Format should be represented separately from topology.

Illustrative schema:

```ts
format: {
  hasMedia: boolean,

  mediaTypes: Array<
    "image" |
    "video" |
    "gif"
  >,

  mediaCount: number,

  hasExternalLink: boolean,

  externalLinkCount: number,

  hasPoll: boolean,

  hasQuestion: boolean,

  lengthClass:
    | "short"
    | "medium"
    | "long",

  isThread: boolean,

  isPaidPartnership: boolean,

  possiblySensitive: boolean | null
}
```

This becomes an important retrieval and baseline feature.

---

# 67. Normalize Media Separately

Full media records should not be embedded into one giant post row.

Illustrative schema:

```ts
PostMedia {
  id: UUID,

  postId: UUID,

  xMediaKey: string | null,

  type:
    | "photo"
    | "video"
    | "animated_gif",

  width: number | null,
  height: number | null,

  durationMs: number | null,

  altText: string | null
}
```

For V1, media metadata is usually enough for distribution analysis.

The system should not automatically download and permanently retain every media asset unless visual-content understanding specifically requires it.

---

# 68. Structural Content Features

Some post characteristics should be calculated deterministically.

Illustrative representation:

```ts
structure: {
  characterCount: number,
  wordCount: number,
  sentenceCount: number,
  paragraphCount: number,
  lineCount: number,

  hashtagCount: number,
  mentionCount: number,
  urlCount: number,

  questionCount: number,

  hasQuestionMark: boolean,

  startsWithMention: boolean,

  containsNumber: boolean,

  containsCodeLikeText: boolean,

  containsListStructure: boolean,

  containsCTA: boolean | null
}
```

Avoid inventing arbitrary marketing-oriented scores such as:

```text
hookScore
viralityScore
emotionScore
```

unless they can eventually be validated.

Descriptive features should come first.

---

# 69. Timing Profile

Every historical post should have normalized timing features.

Illustrative schema:

```ts
timing: {
  publishedAtUtc: Date | null,

  creatorTimezone: string,

  publishedAtLocal: Date | null,

  localHour: number | null,

  localMinute: number | null,

  dayOfWeek: number | null,

  isWeekend: boolean | null,

  minutesSincePreviousPost: number | null,

  postsPrevious24Hours: number | null,

  postsPrevious7Days: number | null
}
```

For drafts:

```text
publishedAt = null
```

unless the creator has selected a proposed publication time.

A separate field can then store:

```ts
proposedPublishAt: Date | null
```

Timing should affect retrieval and outlook without dominating content similarity.

---

# 70. Creator State at Publication

Historical analysis must not rely only on the creator's **current** account state.

Each published post should reference a creator-state snapshot.

Illustrative representation:

```ts
creatorState: {
  followersCount: number | null,

  followingCount: number | null,

  postCount: number | null,

  listedCount: number | null,

  verified: boolean | null,

  verifiedType: string | null,

  accountAgeDays: number | null,

  stateSource:
    | "observed"
    | "archive"
    | "estimated"
    | "era_proxy",

  stateConfidence: number
}
```

If exact historical follower count is unknown, do not invent precision.

Use:

```text
followersCount = null
```

and perhaps an era-level account-scale bucket when legitimately inferable.

---

# 71. Creator Era

Every historical post should reference a creator era.

Illustrative post-level representation:

```ts
creatorEra: {
  eraId: UUID,

  eraIndex: number,

  isCurrentEra: boolean,

  eraSimilarityToCurrent: number,

  eraConfidence: number
}
```

The era itself should be stored separately.

Illustrative representation:

```ts
CreatorEra {
  id: UUID,
  creatorId: UUID,

  startsAt: Date,
  endsAt: Date | null,

  label: string,

  dominantTopicClusters: UUID[],
  followerScaleMin: number | null,
  followerScaleMax: number | null,

  creatorIdentityEmbedding: vector | null
}
```

Example:

```text
Era 3
2025–2026
Engineering + Founder / Building in Public
```

Comparable retrieval should favor the current era while preserving older eras as historical context.

---

# 72. Conversation Context

Topic conditions change over time.

A post about OpenAI during a major model release exists in a very different environment from one posted during a quiet week.

Store a contextual snapshot.

Illustrative representation:

```ts
conversationContext: {
  observedAt: Date | null,

  queryTerms: string[],

  topicVolume: number | null,

  previousWindowVolume: number | null,

  volumeChangeRatio: number | null,

  activityLevel:
    | "low"
    | "normal"
    | "elevated"
    | "extreme"
    | null,

  momentum:
    | "declining"
    | "stable"
    | "increasing"
    | null,

  contextConfidence: number | null,

  dataSource: string | null
}
```

Preserve both:

```text
raw measurements
```

and:

```text
our derived classification
```

so interpretation can change later without losing the original observation.

---

# 73. Outcomes Must Be Separate From Retrieval Features

This is a critical architectural boundary.

The comparable-post engine must **not** use a historical post's success as a reason to consider it similar.

Otherwise the system leaks outcomes into retrieval.

Bad pattern:

```text
new draft
↓
find historically high-performing posts
↓
predict high performance
```

Instead:

```text
DESCRIPTIVE PROFILE
```

must remain separate from:

```text
OBSERVED OUTCOME
```

Retrieval should use the descriptive profile.

Only after the comparable set is selected should the system inspect historical outcomes.

This prevents circular prediction.

---

# 74. Outcome Vector

For published posts, preserve a multi-dimensional outcome vector.

Illustrative representation:

```ts
outcome: {
  impressions: number | null,

  likes: number | null,
  replies: number | null,
  reposts: number | null,
  quotes: number | null,
  bookmarks: number | null,

  profileClicks: number | null,
  urlClicks: number | null,
  engagements: number | null,

  videoViews: number | null,

  videoPlayback25: number | null,
  videoPlayback50: number | null,
  videoPlayback75: number | null,
  videoPlayback100: number | null
}
```

This allows the product to distinguish:

```text
Reach
Conversation
Redistribution
Conversion
Retention
```

instead of collapsing everything into one engagement metric.

---

# 75. Outcomes Should Be Stored as Time-Series Metric Snapshots

Do not store only one final outcome for a post.

Performance at:

```text
1 hour
```

and:

```text
30 days
```

represent different distribution stages.

Use metric snapshots.

Illustrative schema:

```ts
PostMetricSnapshot {
  id: UUID,

  postId: UUID,

  observedAt: Date,

  postAgeSeconds: number,

  impressions: number | null,

  likes: number | null,
  replies: number | null,
  reposts: number | null,
  quotes: number | null,
  bookmarks: number | null,

  profileClicks: number | null,
  urlClicks: number | null,
  engagements: number | null,

  organicImpressions: number | null,

  promotedImpressions: number | null,

  videoViews: number | null,

  playback25: number | null,
  playback50: number | null,
  playback75: number | null,
  playback100: number | null
}
```

Standard observation windows may include:

```text
5m
15m
30m
1h
2h
6h
12h
24h
```

---

# 76. Always Compare Equivalent Observation Windows

Never compare:

```text
new post after 2 hours
```

against:

```text
historical post after 8 months
```

and call the results comparable.

A:

```text
24h outlook
```

should be evaluated against historical:

```text
24h outcomes
```

where available.

Old archive posts without historical snapshots should be marked accordingly.

Example:

```text
metricWindow = "terminal_or_unknown"
```

Such posts should not be used for early-velocity baselines.

---

# 77. Organic and Promoted Distribution Must Stay Separate

Paid promotion can contaminate a normal organic baseline.

Use an explicit distribution type:

```ts
distributionType:
  | "organic"
  | "promoted"
  | "mixed"
  | "unknown"
```

Promoted or mixed posts should generally not enter normal organic baselines unless organic metrics can be isolated.

This prevents paid reach from distorting creator expectations.

---

# 78. Derived Performance Features

Frequently used rates can be generated from raw metrics.

Illustrative representation:

```ts
derivedOutcome: {
  likeRate: number | null,
  replyRate: number | null,
  repostRate: number | null,
  quoteRate: number | null,
  bookmarkRate: number | null,

  profileClickRate: number | null,
  urlClickRate: number | null,

  impressionsPerFollower: number | null,

  video25Retention: number | null,
  video50Retention: number | null,
  video75Retention: number | null,
  videoCompletionRate: number | null,

  impressionVelocity: number | null,
  replyVelocity: number | null,
  repostVelocity: number | null
}
```

Always retain the underlying raw numerator and denominator.

Do not store only the derived rate.

---

# 79. Retrieval Eligibility Metadata

Every historical post should indicate whether it is valid baseline evidence.

Illustrative representation:

```ts
retrieval: {
  baselineEligible: boolean,

  exclusionReasons: string[],

  dataCompletenessScore: number,

  semanticQualityScore: number,

  outcomeQualityScore: number
}
```

Possible exclusion reasons include:

```text
PURE_REPOST
PROMOTED_WITHOUT_ORGANIC_BREAKDOWN
CORRUPT_IMPORT
MISSING_TEXT
INSUFFICIENT_METRICS
DELETED_BEFORE_OBSERVATION
ANOMALOUS_DATA
```

This keeps the retrieval engine clean and prevents large amounts of ad-hoc filtering logic.

---

# 80. Version Every Derived Feature Pipeline

Semantic and classification systems will improve over time.

The database should record which version produced each derived feature.

Illustrative representation:

```ts
featureVersions: {
  embeddingModel: string,
  embeddingVersion: string,

  topicClassifier: string,
  topicClassifierVersion: string,

  intentClassifier: string,
  intentClassifierVersion: string,

  languageClassifierVersion: string | null,

  structureExtractorVersion: string,

  featurePipelineVersion: string
}
```

This lets the system safely reprocess historical records later.

---

# 81. Preserve `featuresAsOf`

Every profile should include:

```ts
featuresAsOf: Date
```

This matters for reproducibility.

We eventually need to answer:

> **What did the system know when it made this prediction?**

not:

> **What do we know about this post today?**

This distinction is important for trustworthy model evaluation.

---

# 82. Draft-Specific Representation

Drafts have no X post ID and no outcome yet.

Illustrative representation:

```ts
DraftPostProfile {
  xPostId: null,

  source: "draft",

  content: {...},

  semantics: {...},

  intent: {...},

  topology: {...},

  format: {...},

  proposedTiming: {
    publishAt: Date | null
  },

  creatorState: {
    // current creator-state snapshot
  },

  creatorEra: {
    // current era
  },

  conversationContext: {
    // current topic context
  },

  outcome: null
}
```

When the draft becomes a published X post, preserve that relationship.

Use:

```ts
originDraftId: UUID | null
```

This becomes important when measuring whether recommendations were applied.

---

# 83. Predictions Must Be Separate From Post Profiles

Do not embed predictions directly into the Post Profile.

Use a separate entity.

Illustrative representation:

```ts
DistributionPrediction {
  id: UUID,
  draftId: UUID,

  generatedAt: Date,

  expectedPercentileLow: number,
  expectedPercentileHigh: number,

  confidence: number,

  comparableSetId: UUID,

  predictedStrongestOutcome: string,

  componentScores: {...},

  reasons: [...],

  predictionVersion: string
}
```

A creator may analyze the same draft multiple times after edits.

Each prediction should remain reproducible.

---

# 84. Recommendations Must Also Be Separate

Recommendations should have their own persisted record.

Illustrative representation:

```ts
Recommendation {
  id: UUID,

  predictionId: UUID,

  type: string,

  description: string,

  evidence: object,

  creatorDecision:
    | "applied"
    | "ignored"
    | "partially_applied"
    | null
}
```

This creates a clean evaluation chain:

```text
recommendation
↓
creator action
↓
actual post
↓
observed result
```

without contaminating the underlying Post Profile.

---

# 85. Complete Conceptual Data Model

The architecture now looks like:

```text
Creator
│
├── CreatorEra
│
├── CreatorStateSnapshot
│
│
├── Post
│   │
│   ├── PostProfile
│   │   ├── Content
│   │   ├── Semantics
│   │   ├── Intent
│   │   ├── Format
│   │   ├── Topology
│   │   ├── Timing
│   │   ├── CreatorStateRef
│   │   ├── CreatorEraRef
│   │   └── ConversationContext
│   │
│   ├── PostMedia
│   │
│   └── PostMetricSnapshot[]
│
├── Draft
│   └── PostProfile
│
├── ComparableSet
│   └── ComparablePost[]
│
├── DistributionPrediction
│
└── Recommendation[]
```

This separation should be preserved in implementation.

---

# 86. Persist Comparable Sets

When a prediction is generated, do not calculate comparable posts and discard them.

Persist the exact evidence set.

Illustrative representation:

```ts
ComparableSet {
  id: UUID,

  draftId: UUID,

  generatedAt: Date,

  retrievalVersion: string,

  fallbackLevel: number,

  comparableCount: number,

  meanSimilarity: number,

  medianSimilarity: number,

  matchQuality: number
}
```

Each member can store its individual score components:

```ts
ComparablePost {
  comparableSetId: UUID,

  historicalPostId: UUID,

  rank: number,

  comparableScore: number,

  semanticSimilarity: number,
  topicMatch: number,
  intentMatch: number,
  formatMatch: number,
  eraMatch: number,
  recencyWeight: number,
  timingMatch: number,
  scaleMatch: number,
  contextMatch: number
}
```

This gives the prediction system complete reproducibility.

---

# 87. Retrieval Feature Importance

Not every field should influence matching equally.

## High Importance

```text
semantic embedding
topic cluster
subtopic
intent
post topology
format
creator era
```

## Medium Importance

```text
recency
account scale
media
language
```

## Lower / Contextual Importance

```text
time of day
day of week
conversation environment
```

## Never Use Directly for Similarity Matching

```text
likes
impressions
reposts
profile clicks
actual percentile
viral/outlier status
```

Those are outcomes.

They belong downstream of retrieval.

---

# 88. Storage Strategy

A relational database such as PostgreSQL fits this architecture naturally.

Possible table structure:

```text
creators
creator_eras
creator_state_snapshots

posts
post_profiles
post_media

post_metric_snapshots

drafts

comparable_sets
comparable_set_posts

distribution_predictions
recommendations
```

Semantic vectors can live alongside the post profile using a vector-capable index such as `pgvector`.

Conceptually:

```sql
embedding vector(...)
```

Stage 1 retrieval can then use semantic nearest-neighbor search scoped by:

```text
creator_id
+
compatible topology
+
retrieval eligibility
```

followed by deterministic fine ranking.

---

# 89. Never Make the X API Payload the Database Schema

The product should not couple its database directly to the shape of one X API response.

Use an adapter layer:

```text
X payload
    ↓
adapter / parser
    ↓
canonical Post model
```

Then:

```text
X API
X Archive
Future imports
```

can all map into the same internal representation.

This keeps the product stable as APIs evolve.

---

# 90. Final Post Profile Shape

At the highest level:

```text
POST PROFILE

Identity
├── creator
├── X ID
└── source

Content
├── text
├── language
└── entities

Semantic
├── embedding
├── topic
├── subtopics
└── intent

Structure
├── topology
├── media
├── length
├── links
└── interaction structure

Creator Context
├── creator era
├── account scale
└── creator state

Temporal Context
├── timestamp
├── day/hour
├── posting frequency
└── recency

Platform Context
├── topic activity
├── momentum
└── conversation environment

Retrieval Metadata
├── eligibility
├── completeness
└── feature versions

─────────────────────

OUTCOME — SEPARATE

├── metric snapshots
├── reach
├── conversation
├── redistribution
├── conversion
└── retention
```

The separation between **descriptive profile** and **outcome** is one of the most important architectural decisions in the system.

It ensures the comparable engine answers:

> **Which historical posts were genuinely similar before we knew how they performed?**

and only then:

> **How did those similar posts perform?**

That prevents the system from selecting historical winners and falsely convincing itself that the new post is likely to win too.

---

# 91. Next Design Layer — Creator Baseline Engine

Now that the system has:

- a canonical Post Profile;
- comparable-post retrieval;
- persisted comparable sets;
- clean outcome vectors;
- standardized metric snapshots;

the next design layer is the **Creator Baseline Engine**.

This engine should define exactly how matched historical outcomes become:

- median baselines;
- P25 / P50 / P75 ranges;
- percentile predictions;
- Reach Outlook;
- Conversation Outlook;
- Redistribution Outlook;
- Conversion Outlook;
- Retention Outlook where relevant;
- confidence;
- and eventually the final Distribution Outlook.

The next design task should answer:

1. Which observation window should each baseline represent?
2. How should comparable posts be weighted inside the baseline?
3. Should weighted medians or unweighted robust statistics be used?
4. How should P25/P50/P75 be calculated with small sample sizes?
5. How should outcome rates be normalized?
6. How should account-scale differences affect baselines?
7. How should creator-era differences be weighted?
8. How should promoted posts be excluded or normalized?
9. How should reach, conversation, redistribution, conversion, and retention be defined mathematically?
10. How should the engine produce percentile predictions?
11. How should prediction ranges widen when uncertainty increases?
12. How should comparable-set quality feed confidence?
13. How should early post-publish metrics update the initial outlook?
14. How should the system distinguish ordinary variance from meaningful outperformance?
15. How should prediction accuracy and calibration be evaluated over time?

This is where the schema and comparable-post system become the first real **prediction methodology**.
---

# 92. Creator Baseline Engine — V1 Prediction Methodology

The **Creator Baseline Engine** is the layer that turns:

```text
Post Profile
+
Comparable Set
+
Historical Outcome Vectors
```

into an actual creator-specific prediction.

The V1 should remain **deterministic and statistical** rather than introducing an opaque custom ML predictor too early.

The core pipeline is:

```text
Draft Post Profile
        ↓
Comparable-Post Retrieval
        ↓
Persisted Comparable Set
        ↓
Historical Outcome Vectors
        ↓
Creator Baseline Engine
        ↓
┌───────────────────────────────┐
│ Reach Baseline                │
│ Conversation Baseline         │
│ Redistribution Baseline       │
│ Conversion Baseline           │
│ Retention Baseline            │
└───────────────────────────────┘
        ↓
Expected Ranges + Percentiles
        ↓
Evidence / Confidence
        ↓
Distribution Outlook
```

The most important principle is:

> **The baseline is a distribution, not an average.**

Do not summarize a creator's comparable history with only:

```text
Average impressions:
12,347
```

A single viral post can make that number misleading.

Instead, use robust ranges:

```text
Comparable posts:
42

P25:
5,200 impressions

P50:
8,600 impressions

P75:
13,900 impressions

P90:
31,000 impressions
```

This describes what the creator's performance distribution actually looks like.

---

# 93. Baselines Must Be Observation-Window Specific

A post's performance after:

```text
30 minutes
```

cannot be compared with another post's performance after:

```text
3 months
```

The baseline engine should therefore support explicit horizons.

Recommended standardized monitoring windows:

```text
5m
15m
30m
1h
2h
6h
12h
24h
```

Potential later windows:

```text
48h
7d
```

Every baseline should include its horizon.

Illustrative representation:

```ts
Baseline {
  metric: string,
  horizon: "24h",
  comparableSetId: UUID,
  ...
}
```

For V1, **24 hours** should be the primary mature Distribution Outlook horizon.

Early windows are primarily useful for trajectory analysis.

---

# 94. Two Classes of Historical Baseline

X archive and historical API data usually do not provide historical 30-minute, 1-hour, or 24-hour metric snapshots for old posts.

Therefore the system needs two baseline classes.

## A. Mature Historical Baseline

For old posts where only the current cumulative metrics are available:

```text
Historical post
Age:
8 months

Current impressions:
14,200
```

classify the outcome as:

```text
MATURE / TERMINAL OUTCOME
```

These posts remain useful for:

- historical relative performance;
- topic comparison;
- mature outcome percentiles;
- onboarding before our own monitoring history exists.

They must **not** be used for early-velocity baselines.

## B. Standardized Window Baseline

Once the product starts monitoring a creator, capture:

```text
15m
30m
1h
2h
6h
12h
24h
```

This creates proper time-aligned outcome history.

The product naturally improves with usage:

```text
DAY 1

Archive + historical API
↓
Good semantic history
Good mature baselines
Weak trajectory history
```

Then:

```text
AFTER 30 MONITORED POSTS

+
30m baselines
1h baselines
2h baselines
24h baselines
```

Then:

```text
AFTER 100 MONITORED POSTS

+
Much stronger trajectory prediction
+
Better calibration
```

This creates a natural learning loop without requiring custom model training.

---

# 95. Comparable Posts Should Be Weighted

The final comparable set should not contribute equally.

Example:

```text
Post A comparable score:
0.94

Post B comparable score:
0.91

Post C comparable score:
0.54
```

A and B should influence the baseline more strongly.

A simple starting point:

```text
baseline_weight_i
=
f(comparable_score_i)
× outcome_quality_i
```

Because the comparable score already includes:

- semantic similarity;
- topic;
- intent;
- format;
- creator era;
- recency;
- timing;
- account scale;
- context,

the baseline engine should avoid multiplying all those factors again and accidentally double-counting them.

A simple V1 transformation can be:

```text
weight_i =
comparable_score_i ^ γ
```

where:

```text
γ > 1
```

makes stronger matches more influential.

The exact value of `γ` should be validated empirically.

Then normalize:

```text
normalized_weight_i =
weight_i / Σ weight
```

---

# 96. Prevent a Single Historical Post From Dominating

Even a very strong match should not control the entire prediction.

Use a maximum normalized contribution cap.

Conceptually:

```text
max single-post weight:
10–15%
```

The exact cap should be tuned later.

The goal is to prevent one strange historical post from becoming the prediction.

---

# 97. Effective Sample Size Matters More Than Raw Count

Raw comparable count can be misleading.

Suppose:

```text
Raw comparable count:
42
```

but most of the statistical weight sits on five posts.

The real evidence strength is much lower.

Use **effective sample size**:

```text
N_eff =
1 / Σ(wᵢ²)
```

where normalized weights sum to 1.

Example:

```text
Raw comparable count:
42

Effective comparable count:
26.4
```

Another:

```text
Raw comparable count:
25

Effective comparable count:
6.8
```

The second case should produce materially lower confidence.

---

# 98. Evidence Tiers Should Use Effective Sample Size

Use `N_eff`, not only raw count, to classify evidence strength.

Illustrative V1 tiers:

```text
N_eff ≥ 20
→ Strong personalized evidence

N_eff 8–20
→ Moderate personalized evidence

N_eff 3–8
→ Weak personalized evidence

N_eff < 3
→ Cold-topic / insufficient evidence
```

Raw count can still be displayed.

But effective sample size should drive confidence and backoff behavior.

---

# 99. Small Samples Need Hierarchical Backoff

If the creator has only a few strong comparables, do not manufacture certainty.

Use hierarchical backoff:

```text
Exact comparables
       ↓
if weak
       +
Broader topic cluster
       ↓
if still weak
       +
Current creator-era baseline
       ↓
if still weak
       +
General recent creator baseline
```

The less specific the available evidence, the more the prediction should shrink toward the creator's broader normal baseline.

A simple shrinkage term can be:

```text
λ =
N_eff / (N_eff + τ)
```

where `τ` is tuned later.

If:

```text
N_eff = 30
```

the personalized comparable set dominates.

If:

```text
N_eff = 3
```

the broader creator baseline contributes substantially more.

This prevents tiny samples from creating unstable predictions.

---

# 100. Use Weighted Robust Quantiles

For every supported outcome metric, calculate weighted robust quantiles.

Examples:

```text
impressions
reply rate
repost rate
quote rate
bookmark rate
profile click rate
URL click rate
video retention
```

Recommended quantiles:

```text
Weighted P10
Weighted P25
Weighted P50
Weighted P75
Weighted P90
```

The core expected range is:

```text
P25 → P75
```

P50 is the central estimate.

P10/P90 represent wider tail behavior.

Example:

```text
24H REACH BASELINE

Comparable posts:
42

Effective N:
27.8

P10:
3,800

P25:
5,900

P50:
9,100

P75:
14,700

P90:
29,500
```

This is far more useful than a simple average.

---

# 101. Viral Posts Stay in the Data but Do Not Define Normal

Legitimate viral posts should not automatically be deleted from the dataset.

Quantiles already make the baseline robust.

A huge outlier has little influence on P50 compared with the mean.

Historical posts can be tagged:

```text
Core
Strong outperformance
Extreme outlier
```

P90+ can represent tail behavior.

Corrupt or invalid data should still be excluded.

---

# 102. Negative Outliers Need Similar Treatment

Extremely poor posts may also be abnormal.

Example:

```text
Normal:
5k–10k impressions

One post:
300 impressions
```

Potential causes include:

- posting error;
- visibility restriction;
- deletion;
- platform anomaly;
- unusual external event;
- broken data.

The system should identify pathological negative outliers before baseline construction.

---

# 103. Reach Outlook

For V1:

```text
Reach =
impressions
```

at the selected observation horizon.

Where historical account scale is known, preserve supporting normalization such as:

```text
impressions / followers_at_publish
```

But raw impressions should remain a primary visible metric because X distributes content beyond followers.

Example:

```text
24H REACH

P25:
5,900

P50:
9,100

P75:
14,700
```

---

# 104. Conversation Outlook

Conversation should primarily reflect replies.

Preserve both:

```text
reply_count
```

and:

```text
reply_rate =
replies / impressions
```

They answer different questions.

Example:

```text
Post A
20 replies
1,000 impressions
= 2%

Post B
100 replies
100,000 impressions
= 0.1%
```

Post B generated more total conversation.

Post A had much stronger conversational propensity.

Therefore:

```text
Conversation Outlook

Reply volume percentile
Reply-rate percentile
```

is better than a single arbitrary conversation score.

---

# 105. Redistribution Outlook

Redistribution should primarily capture:

```text
reposts
quotes
```

Preserve both counts and rates.

Example:

```text
Redistribution Outlook

Repost volume
Repost rate
Quote volume
Quote rate
```

A creator might see:

```text
Reach:
Normal

Conversation:
Strong

Redistribution:
Very strong
```

This is much more informative than one engagement score.

---

# 106. Conversion Outlook

Where creator-authorized metrics are available:

```text
profile clicks
URL clicks
```

calculate:

```text
profile_click_rate =
profile_clicks / impressions
```

and:

```text
url_click_rate =
url_clicks / impressions
```

Example:

```text
Conversion Outlook

Profile discovery:
Top 18%

External click-through:
Top 35%
```

If authenticated metrics are not available:

```text
Conversion Outlook:
Unavailable
```

Do not infer nonexistent data.

---

# 107. Retention Outlook

Retention is relevant primarily for video content.

Preserve:

```text
25%
50%
75%
100%
```

playback completion checkpoints.

Example:

```text
Video Retention

25% retention:
Top 30%

50% retention:
Top 24%

Completion:
Top 17%
```

Retention should remain separate from general reach/distribution because it is highly format-specific.

---

# 108. Do Not Collapse All Dimensions Into One Score

Avoid:

```text
Distribution Score:
83/100
```

created by averaging:

```text
Reach
Conversation
Redistribution
Conversion
Retention
```

That hides too much.

For this product, **Reach should remain the primary Distribution Outlook**.

The other dimensions explain how the post is likely to behave.

Example:

```text
DISTRIBUTION OUTLOOK

Expected Reach:
Top 25–40% of comparable posts

Confidence:
High

Likely strongest behavior:
Conversation

Secondary strength:
Profile discovery

Redistribution:
Around normal
```

This is more interpretable and closer to the actual product goal.

---

# 109. Deriving Expected Percentile Before Publishing

The engine already has a weighted comparable outcome distribution.

Suppose:

```text
Comparable-set weighted median:
9,100 impressions
```

Now place that value inside the creator's **broader current-era reach distribution**.

Suppose:

```text
9,100 impressions
```

corresponds to the:

```text
68th percentile
```

of current-era posts.

That implies an expected outcome around:

> **Top 32%**

Now take the comparable P25 and P75.

Example:

```text
Comparable P25:
7,000
→ current-era percentile:
60th

Comparable P75:
12,500
→ current-era percentile:
76th
```

Then:

```text
Expected percentile:
60th–76th percentile
```

can be displayed as:

```text
Expected:
Top 24–40%
```

This yields a creator-relative percentile interval without inventing a magic scoring equation.

---

# 110. Similarity Determines Evidence Weight; Outcomes Determine Prediction

This is a core methodological principle.

Comparable retrieval already uses:

```text
semantic similarity
topic
intent
format
creator era
recency
timing
account scale
conversation context
```

Therefore the baseline engine should not later add arbitrary bonuses such as:

```text
+12 points because timing is good
+17 points because topic is good```

That would risk double-counting.

Instead:

> **Feature similarity determines which historical evidence receives weight. Historical outcomes determine the prediction.**

This separation keeps the methodology clean.

---

# 111. Component Fits Become Explanations

Creator–Topic Fit, Format Fit, and Timing Fit should still be shown.

But they should be derived from evidence rather than manually added to a score.

Example:

```text
Same-format matched posts
Median reach:
12,400

Compatible alternate-format posts
Median reach:
8,100
```

Then:

```text
Format Fit:
Strong
```

can be explained as:

> Your current format historically performs strongly for this content type.

Timing can work similarly.

Example:

```text
Comparable posts in proposed timing window
Median:
10,900

Comparable posts outside window
Median:
8,400
```

Then:

```text
Timing Fit:
Above average
```

The explanation comes from the baseline rather than manually modifying it.

---

# 112. Rate Metrics Need Denominator Protection

Raw rates become unstable with tiny impression counts.

Example:

```text
1 reply
20 impressions
= 5% reply rate
```

That does not necessarily mean the post is exceptional.

For rate metrics, use either:

- minimum denominator requirements; or
- smoothing toward the creator's broader baseline rate.

A simple V1 smoothing formula:

```text
smoothed_rate =
(events + k × baseline_rate)
/
(impressions + k)
```

where `k` controls how strongly tiny samples shrink toward normal.

The value of `k` should be tuned empirically.

---

# 113. Live Post-Publish Monitoring

Once published:

```text
Pre-publish outlook
↓
Actual 5m
↓
15m
↓
30m
↓
1h
↓
2h
...
```

At every standardized observation window, compare the actual metric against the historical matched distribution for the same window.

Example:

```text
1 HOUR

Actual impressions:
3,420

Historical P25:
1,600

Historical P50:
2,300

Historical P75:
3,100

Actual percentile:
79th
```

Then the product can say:

> **Your post is currently distributing above its expected historical range.**

---

# 114. Meaningful Outperformance Should Use Percentiles

Avoid generic rules such as:

```text
+17% = good
```

without context.

Use creator-specific percentile bands.

Illustrative interpretation:

```text
Below P10
→ strong underperformance

P10–P25
→ below expected

P25–P75
→ normal expected range

P75–P90
→ above expected

Above P90
→ strong outperformance
```

This naturally adapts to creator volatility.

A volatile creator gets a wider expected range.

A consistent creator gets a narrower one.

---

# 115. Early-to-Late Trajectory Prediction

Once enough standardized monitoring history exists, the product can answer:

> **If this post is currently at the 82nd percentile after one hour, where do similar posts usually finish after 24 hours?**

Build historical transition distributions.

Example:

```text
Historical posts that were:
70th–90th percentile at 1h

24h outcomes:

P25:
71st percentile

P50:
83rd percentile

P75:
91st percentile
```

Then a live post currently at:

```text
82nd percentile after 1h
```

can receive:

```text
UPDATED 24H OUTLOOK

Expected:
Top 9–29%

Current trajectory:
Above initial prediction
```

This is more defensible than blindly extrapolating impression velocity.

---

# 116. Do Not Forecast Trajectory Until Enough History Exists

At launch, creator-specific:

```text
1h → 24h
```

transition history may be too sparse.

The system should degrade gracefully.

Initially:

```text
1H STATUS

You're currently in the 82nd percentile
of comparable posts at the same age.
```

No fake 24h projection.

Later, once enough monitored history exists:

```text
Enough trajectory history available
↓
Updated 24h forecast enabled
```

This is another way the product becomes more intelligent through repeated use.

---

# 117. Confidence Should Initially Be Evidence Confidence

Before the prediction system is empirically calibrated, avoid presenting confidence as if it were a literal probability.

Instead of:

```text
Confidence:
81%
```

initially prefer:

```text
Evidence Confidence:
81/100
```

or:

```text
Confidence:
High
```

This avoids pretending that 81 means an exact 81% probability.

---

# 118. Evidence Confidence Inputs

Potential inputs:

```text
Effective sample size
Comparable-set similarity
Current-era representation
Outcome completeness
Fallback level
Historical variance
Metric-window coverage
Context volatility
```

Example:

```text
CONFIDENCE

Effective comparable count:
27.8

Median match score:
0.84

Current-era coverage:
88%

Outcome completeness:
High

Fallback:
None

Historical variance:
Moderate

Confidence:
High
```

This is explainable and auditable.

---

# 119. Historical Variance Must Reduce Confidence

Two creators can have the same sample count and very different predictability.

Creator A:

```text
8k
9k
8.5k
10k
7.8k
9.1k
...
```

Creator B:

```text
1k
40k
3k
100k
2k
60k
...
```

Creator B is much harder to predict.

Therefore confidence must incorporate dispersion.

Prefer robust dispersion measures such as:

```text
IQR
MAD
```

rather than only standard deviation.

---

# 120. Prediction Intervals Should Widen With Uncertainty

High-quality evidence:

```text
Expected:
Top 24–32%
```

Weak or volatile evidence:

```text
Expected:
Top 20–58%
```

The interval itself communicates uncertainty.

The system should not use the same fixed-width range for every creator and post.

---

# 121. Postmortem Evaluation

At the final evaluation horizon:

```text
Prediction:
Top 24–40%

Actual:
Top 17%
```

record:

```text
Direction:
Correct

Interval:
Missed high

Percentile midpoint prediction:
68%

Actual percentile:
83%

Absolute percentile error:
15 points
```

Then evaluate each dimension:

```text
Reach:
Above expected

Conversation:
Strongly above expected

Redistribution:
Within expected

Conversion:
Above expected
```

---

# 122. Evaluate the Baseline Engine Itself

The prediction system needs product-level accuracy metrics.

## Direction Accuracy

How often was:

```text
below / normal / above
```

correctly predicted?

## Interval Coverage

If the system predicts:

```text
Top 25–40%
```

how often does reality land inside that interval?

## Absolute Percentile-Point Error

Example:

```text
Predicted midpoint:
70th percentile

Actual:
82nd percentile

Error:
12 percentile points
```

Track the median, not only the mean.

## Bias

Measure whether the engine systematically:

```text
overpredicts
```

or:

```text
underpredicts
```

## Error by Category

Break down error by:

```text
topic
format
intent
creator era
sample quality
```

This reveals where the system is strong or weak.

---

# 123. Backtesting Must Avoid Future-Data Leakage

Historical evaluation must simulate what the system would have known at the prediction time.

Suppose testing a post from:

```text
June 10
```

The engine may only use information available before June 10.

It must not use:

```text
July data
August data
future follower state
future creator era knowledge
future conversation context
```

Use **walk-forward backtesting**:

```text
Post 1
→ insufficient history

Post 2
→ predict using Post 1

Post 3
→ predict using Posts 1–2

...

Post 100
→ predict using Posts 1–99
```

Then evaluate each prediction against its actual outcome.

This gives a legitimate estimate of V1 prediction quality.

---

# 124. `featuresAsOf` Is Essential for Evaluation

The previously defined:

```text
featuresAsOf
```

field now becomes critical.

Every evaluation should answer:

> **What information existed when this prediction was generated?**

not:

> **What do we know today?**

This preserves causal ordering and prevents hidden future-data leakage.

---

# 125. Final V1 Prediction Methodology

The full pre-publish methodology is now:

```text
NEW DRAFT
   ↓
Post Profile
   ↓
Comparable Retrieval
   ↓
Weighted Comparable Set
   ↓
Calculate N_eff
   ↓
Hierarchical Backoff if needed
   ↓
Historical Outcome Distributions
   ↓
Weighted Robust Quantiles
   ↓
P25 / P50 / P75
   ↓
Map comparable outcome distribution
against broader current-era distribution
   ↓
Expected Percentile Range
   ↓
Dimension Outlooks
   │
   ├── Reach
   ├── Conversation
   ├── Redistribution
   ├── Conversion
   └── Retention
   ↓
Evidence Confidence
   ↓
Explanations
   ↓
DISTRIBUTION OUTLOOK
```

Example:

```text
DISTRIBUTION OUTLOOK

Expected Reach:
Top 24–39% of comparable/current-era performance

Evidence:
High

Comparable posts:
42

Effective comparable count:
27.8

Expected 24h range:
7,200–13,800 impressions


OUTCOME OUTLOOK

Reach:
Above normal

Conversation:
Strong

Redistribution:
Around normal

Profile discovery:
Above normal


WHY

↑ Strong match with your backend engineering history

↑ Posts explaining systems you've personally built
  historically outperform generic technical commentary

↑ Current format performs well for similar posts

↑ Proposed publishing window is above your historical median

↓ Repost performance for text-only technical explanations
  is historically less consistent
```

After publication:

```text
1 HOUR

Actual:
3,420 impressions

Matched baseline:
P50 2,300
P75 3,100

Current percentile:
79th

Status:
Above expected trajectory
```

After 24 hours:

```text
POSTMORTEM

Predicted:
Top 24–39%

Actual:
Top 17%

Reach:
Above prediction

Conversation:
Strongly above prediction

Redistribution:
Within prediction

Profile discovery:
Above prediction

Prediction error:
14 percentile points
```

This is a real, testable V1 prediction methodology rather than an AI-generated social-media score.

---

# 126. Auditability Is a Core Product Requirement

Every prediction should be traceable through:

```text
Post Profile
→ comparable posts
→ weights
→ historical outcomes
→ quantiles
→ percentile
→ prediction
→ actual result
```

If the system is wrong, we should be able to determine where it failed.

Possible failure points include:

- bad semantic representation;
- poor comparable retrieval;
- weak comparable quality;
- insufficient sample size;
- high historical variance;
- incorrect creator-era assignment;
- unusual current conversation conditions;
- unexpected distribution behavior.

This auditability is essential because **accuracy and real results are the product's main value proposition**.

---

# 127. Next Design Layer

Now that the product has:

- a canonical Post Profile;
- comparable-post retrieval;
- weighted comparable sets;
- robust creator baselines;
- percentile-based outlooks;
- evidence confidence;
- live trajectory comparison;
- postmortem evaluation;
- walk-forward backtesting;

the next design work can move into one of two closely related areas:

1. **The exact mathematical/statistical implementation contract** for the Creator Baseline Engine, including concrete formulas, data sufficiency rules, quantile computation, shrinkage, evidence scoring, and fallback behavior.

2. **The product workflow and UX contract** for how a creator connects X, imports history, submits a draft, receives a Distribution Outlook, publishes, and sees live/postmortem intelligence.

The statistical implementation should be finalized before production scoring code is written.