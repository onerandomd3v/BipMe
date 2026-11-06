# X Distribution Intelligence V1 — Implementation Blueprint

**Status:** Implementation-ready blueprint  
**Scope:** X-only creator Discovery & Distribution intelligence  
**Verified against current X developer documentation:** 2026-09-05

---

# 1. Goal

Build a focused V1 that helps an X creator answer:

> **How is this draft likely to perform relative to my own comparable historical posts, why, and what actually happened after I published it?**

The V1 is **not** an “X algorithm cracker,” a generic AI writing assistant, a social scheduler, or a cross-platform dashboard.

The system should produce a creator-specific **Distribution Outlook** using:

```text
creator history
+
canonical Post Profiles
+
comparable-post retrieval
+
robust statistical baselines
+
current X topic context
+
post-publish metric snapshots
```

and then evaluate prediction quality against the real outcome.

---

# 2. V1 Product Promise

A creator should be able to:

```text
Connect X
↓
Import enough recent history to build a baseline
↓
Enter a new draft
↓
Receive a Distribution Outlook
↓
See the historical posts used as evidence
↓
Receive optional evidence-backed recommendations
↓
Publish manually on X
↓
Attach the published Post
↓
Watch its actual trajectory against matched baselines
↓
Receive a 24-hour postmortem
```

Recommended external positioning:

> **We use your real X history and measurable post outcomes to help you make better distribution decisions, then show whether the prediction was right.**

---

# 3. Hard Product Boundaries

## V1 IS

- X only;
- creator-specific;
- evidence-based;
- read-focused;
- statistical/deterministic first;
- auditable;
- centered on relative performance;
- designed around official X APIs;
- designed to improve as more creator history is monitored.

## V1 IS NOT

- Instagram/TikTok/Facebook/LinkedIn support;
- an automated posting bot;
- automatic engagement;
- “guaranteed virality”;
- a universal algorithm score;
- a custom ML model trained on X data;
- full follower graph intelligence;
- a generic social media manager;
- a creator marketplace;
- a community platform.

---

# 4. MVP Cut Line

## MUST HAVE — Ship for V1

1. X OAuth connection.
2. Creator profile ingestion.
3. Recent creator Post ingestion.
4. Canonical Post Profile generation.
5. Semantic representation.
6. Topic + intent + format classification.
7. Creator-era/current-state representation.
8. Historical metric normalization.
9. Comparable-post retrieval.
10. Persisted Comparable Sets.
11. Creator Baseline Engine.
12. Distribution Outlook.
13. Evidence Confidence.
14. Top comparable Posts shown to creator.
15. Optional evidence-backed recommendation.
16. Manual published-Post attachment.
17. Standardized metric snapshots.
18. Live percentile comparison.
19. 24-hour postmortem.
20. Prediction/backtesting audit records.
21. X API cost/usage instrumentation.
22. Privacy-conscious token and data handling.

## SHOULD HAVE — If time remains

- recent X topic-count context;
- lightweight Recent Search context;
- creator-era auto-segmentation;
- creator-selected primary goal:
  - reach;
  - conversation;
  - redistribution;
  - conversion;
- X Archive import;
- video retention outlook;
- creator feedback on bad comparable matches;
- backtesting dashboard.

## POST-V1

- follower graph analysis;
- complete audience segmentation;
- direct posting to X;
- automatic scheduling;
- X Activity/webhook subscriptions;
- advanced trajectory forecasting;
- custom learned ranking model;
- multi-platform support;
- recommendation A/B experimentation;
- automated creator-era detection at scale;
- real-time event-based contextual modeling.

---

# 5. Recommended Reference Stack

This blueprint is implementation-language independent, but the recommended reference stack is:

```text
Frontend
Next.js / React

Backend
NestJS modular monolith

Database
PostgreSQL

Vector search
pgvector

Background jobs
BullMQ + Redis

Object/archive storage
S3-compatible object storage

Observability
OpenTelemetry / Prometheus-compatible metrics
structured logs

Testing
Jest
integration test database
Playwright for core E2E flow
```

Why a **modular monolith** for V1:

- one product;
- one database;
- tightly related intelligence pipeline;
- easier iteration;
- simpler deployments;
- easier transactions and debugging;
- clean module boundaries still allow future extraction.

Do **not** begin with microservices.

---

# 6. High-Level System Architecture

```text
                         ┌─────────────────────┐
                         │       Web App       │
                         └──────────┬──────────┘
                                    │
                                    ▼
                    ┌─────────────────────────────┐
                    │      NestJS Application     │
                    │       Modular Monolith      │
                    └─────────────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       │                            │                            │
       ▼                            ▼                            ▼
┌─────────────┐            ┌────────────────┐          ┌────────────────┐
│ X Adapter   │            │ Intelligence   │          │ Job Scheduler  │
│ / OAuth     │            │ Pipeline       │          │ / Workers      │
└──────┬──────┘            └───────┬────────┘          └───────┬────────┘
       │                            │                            │
       ▼                            ▼                            ▼
┌─────────────┐          ┌────────────────────┐         ┌───────────────┐
│ Official X  │          │ PostgreSQL +       │         │ Redis/BullMQ  │
│ API         │          │ pgvector           │         └───────────────┘
└─────────────┘          └────────────────────┘
```

---

# 7. Backend Modules

Recommended NestJS module boundaries:

```text
AuthModule
XIntegrationModule
CreatorModule
CreatorHistoryModule
PostModule
PostProfileModule
SemanticModule
TopicClusterModule
CreatorEraModule
ComparableRetrievalModule
BaselineModule
PredictionModule
RecommendationModule
MonitoringModule
PostmortemModule
ContextModule
ArchiveImportModule        // SHOULD HAVE
UsageCostModule
PolicyPrivacyModule
BacktestModule
ObservabilityModule
```

Each module should own a clear domain boundary rather than becoming a generic “AI service.”

---

# 8. X Authentication Contract

Use:

> **OAuth 2.0 Authorization Code Flow with PKCE**

X documents OAuth 2.0 fine-grained scopes and refresh-token support.

Core V1 requested scopes should follow least privilege:

```text
tweet.read
users.read
offline.access
```

Add only if corresponding V1 functionality ships:

```text
follows.read
```

Do **not** request in core V1:

```text
tweet.write
like.write
follows.write
dm.read
dm.write
```

No automatic publishing or engagement is needed.

`offline.access` is required for refresh tokens and long-running monitoring.

Official reference:

https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code

---

# 9. X Token Storage

Persist:

```text
x_connections
- id
- creator_id
- x_user_id
- access_token_encrypted
- refresh_token_encrypted
- access_token_expires_at
- scopes
- connected_at
- revoked_at
```

Requirements:

- encrypt tokens at rest;
- never log raw access/refresh tokens;
- refresh before expiration;
- mark connection unhealthy after repeated refresh failure;
- allow explicit disconnect;
- revoke/delete locally stored secrets on disconnect;
- separate X connection identity from internal Creator identity.

---

# 10. X API Integration Map

## 10.1 Creator Post History

Primary endpoint:

```text
GET /2/users/{id}/tweets
```

Current X docs state this timeline supports up to **3,200 most recent Posts** and pagination.

Reference:

https://docs.x.com/x-api/posts/timelines/introduction

Important fields to request where available:

```text
post.fields=
attachments,
community_id,
context_annotations,
conversation_id,
created_at,
display_text_range,
edit_controls,
entities,
lang,
media_metadata,
non_public_metrics,
note_post,
organic_metrics,
paid_partnership,
possibly_sensitive,
promoted_metrics,
public_metrics,
reply_settings,
text
```

Relevant expansions:

```text
attachments.media_keys
attachments.poll_ids
author_id
edit_history_post_ids
in_reply_to_user_id
referenced_posts
```

Relevant media fields:

```text
alt_text
duration_ms
height
media_key
non_public_metrics
organic_metrics
promoted_metrics
public_metrics
type
width
```

Relevant creator fields:

```text
created_at
description
location
protected
public_metrics
username
verified
verified_type
```

Adapter requirement:

> The X response shape must be mapped into the internal canonical Post model. Never make the X response itself the database schema.

---

# 11. Current X Metric Contract

X currently documents:

## Public Post metrics

```text
public_metrics.retweet_count
public_metrics.quote_count
public_metrics.like_count
public_metrics.reply_count
public_metrics.impression_count
public_metrics.bookmark_count
```

## Creator-owned non-public metrics

```text
non_public_metrics.url_link_clicks
non_public_metrics.user_profile_clicks
non_public_metrics.engagements
```

## Video metrics

```text
public_metrics.view_count

non_public_metrics.playback_0_count
non_public_metrics.playback_25_count
non_public_metrics.playback_50_count
non_public_metrics.playback_75_count
non_public_metrics.playback_100_count
```

X currently states that non-public, organic, and promoted metrics are only available for Posts created in the previous **30 days**.

Therefore:

> Snapshot creator-authorized private metrics while they are available.

Official reference:

https://docs.x.com/x-api/fundamentals/metrics

---

# 12. Topic Context Endpoints

## Recent Search

```text
GET /2/tweets/search/recent
```

Use sparingly for contextual evidence around current topics.

Reference:

https://docs.x.com/x-api/posts/search/quickstart/recent-search

## Recent Post Counts

```text
GET /2/tweets/counts/recent
```

Current docs describe this as counting Posts from the previous seven days.

Reference:

https://docs.x.com/x-api/posts/counts/introduction

V1 preference:

> Use Post Counts before pulling large Recent Search result sets when only topic activity/momentum is required.

This is cheaper, simpler, and more aligned with the actual feature.

---

# 13. Follower Endpoints

X exposes:

```text
GET /2/users/{id}/followers
```

Reference:

https://docs.x.com/x-api/users/get-followers

However, **do not ingest full follower graphs in core V1**.

Reasons:

- expensive;
- large;
- unnecessary for matched historical baseline prediction;
- increases privacy surface;
- increases implementation complexity.

V1 uses:

- creator public follower count;
- creator state snapshots;
- current/era account-scale information.

Detailed audience graph analysis belongs post-V1.

---

# 14. Repost Audience

X exposes:

```text
GET /2/tweets/{id}/retweeted_by
```

Reference:

https://docs.x.com/x-api/posts/get-reposted-by

Do not require this endpoint for core V1.

Use it only if a later audience-analysis feature needs individual reposter identities.

Core V1 only needs aggregate repost counts.

---

# 15. X API Cost Awareness

X currently uses pay-per-use pricing.

As of 2026-09-05, official docs list examples including:

```text
Post read:              $0.005 / resource
User read:              $0.010 / resource
Follower/following:     $0.010 / resource
Like read:              $0.001 / resource
Recent Counts request:  $0.005 / request
```

The docs also currently state a **3 million Post-read monthly cap** for pay-per-use before Enterprise.

Prices can change.

Always treat the Developer Console as authoritative.

Reference:

https://docs.x.com/x-api/getting-started/pricing

---

# 16. Cost-Aware History Ingestion

Blindly importing 3,200 Posts for every new user is expensive.

At current standard Post-read pricing:

```text
3,200 × $0.005
≈ $16 in Post resources
```

before other reads.

Therefore use **progressive history ingestion**.

Recommended V1:

```text
Initial sync:
200–500 most recent Posts

Evaluate eligible history:
↓
If evidence is sufficient:
stop

If weak:
fetch next page(s)

Maximum API-only history:
configurable, up to endpoint limit
```

Suggested default:

```text
INITIAL_HISTORY_TARGET = 300
HISTORY_EXPANSION_STEP = 200
MAX_API_HISTORY = 1000       // V1 default, configurable
```

Do not automatically fetch all 3,200 unless needed.

X Archive import can later provide deeper user-supplied historical context without requiring the same API-read pattern.

---

# 17. API Usage Deduplication

Current X pricing docs state that resources are generally deduplicated for billing within the same 24-hour UTC day window.

That makes repeated polling of the same published Post within one UTC day more cost-manageable, although rate limits and pricing rules still apply.

Do not rely on billing deduplication as a correctness primitive.

Track actual API usage and estimated cost internally.

---

# 18. V1 Database Schema

Recommended core tables:

```text
users
creators
x_connections

creator_eras
creator_state_snapshots

posts
post_profiles
post_entities
post_media
post_metric_snapshots

topic_clusters

drafts

comparable_sets
comparable_set_posts

distribution_predictions
recommendations

conversation_context_snapshots

sync_runs
monitoring_runs
backtest_runs

api_usage_events
```

---

# 19. `creators`

```text
id UUID PK
user_id UUID FK

x_user_id VARCHAR UNIQUE NULL
username VARCHAR NULL

timezone VARCHAR NOT NULL
current_era_id UUID NULL

created_at
updated_at
```

---

# 20. `creator_state_snapshots`

```text
id UUID PK
creator_id UUID FK

observed_at TIMESTAMPTZ

followers_count BIGINT NULL
following_count BIGINT NULL
post_count BIGINT NULL
listed_count BIGINT NULL

verified BOOLEAN NULL
verified_type VARCHAR NULL

state_source ENUM(
  observed,
  archive,
  estimated,
  era_proxy
)

state_confidence NUMERIC

created_at
```

Index:

```text
(creator_id, observed_at DESC)
```

---

# 21. `creator_eras`

```text
id UUID PK
creator_id UUID FK

starts_at TIMESTAMPTZ
ends_at TIMESTAMPTZ NULL

label VARCHAR

follower_scale_min BIGINT NULL
follower_scale_max BIGINT NULL

is_current BOOLEAN

era_confidence NUMERIC

created_at
updated_at
```

V1 may begin with:

- one “current era” automatically;
- optional manual/heuristic earlier eras.

Full automatic era segmentation is SHOULD HAVE.

---

# 22. `posts`

Canonical identity/source layer:

```text
id UUID PK
creator_id UUID FK

x_post_id VARCHAR NULL
origin_draft_id UUID NULL

source ENUM(
  x_api,
  x_archive,
  draft
)

status ENUM(
  draft,
  published,
  deleted,
  unknown
)

source_record_id VARCHAR NULL

raw_text TEXT
effective_text TEXT

x_created_at TIMESTAMPTZ NULL

content_hash VARCHAR

distribution_type ENUM(
  organic,
  promoted,
  mixed,
  unknown
)

created_at
updated_at
```

Unique partial index:

```text
UNIQUE (creator_id, x_post_id)
WHERE x_post_id IS NOT NULL
```

---

# 23. `post_profiles`

Derived/descriptive profile:

```text
id UUID PK
post_id UUID UNIQUE FK

normalized_text TEXT

x_detected_language VARCHAR NULL
effective_language VARCHAR NULL

primary_topic_cluster_id UUID NULL

primary_intent VARCHAR NULL
intent_vector JSONB

topology_type VARCHAR
format JSONB
structure JSONB

creator_era_id UUID NULL
creator_state_snapshot_id UUID NULL
conversation_context_snapshot_id UUID NULL

embedding VECTOR(<chosen_dimension>)

baseline_eligible BOOLEAN
exclusion_reasons JSONB

data_completeness_score NUMERIC
semantic_quality_score NUMERIC
outcome_quality_score NUMERIC

profile_schema_version VARCHAR
feature_pipeline_version VARCHAR
embedding_model VARCHAR
embedding_version VARCHAR
topic_classifier_version VARCHAR
intent_classifier_version VARCHAR

features_as_of TIMESTAMPTZ

created_at
updated_at
```

Indexes:

```text
(post_id)
(primary_topic_cluster_id)
(creator_era_id)
(topology_type)
(baseline_eligible)
```

Vector index scoped by creator retrieval strategy.

---

# 24. `post_metric_snapshots`

```text
id UUID PK
post_id UUID FK

observed_at TIMESTAMPTZ
post_age_seconds BIGINT

impressions BIGINT NULL
likes BIGINT NULL
replies BIGINT NULL
reposts BIGINT NULL
quotes BIGINT NULL
bookmarks BIGINT NULL

profile_clicks BIGINT NULL
url_clicks BIGINT NULL
engagements BIGINT NULL

organic_impressions BIGINT NULL
promoted_impressions BIGINT NULL
video_views BIGINT NULL
playback_25 BIGINT NULL
playback_50 BIGINT NULL
playback_75 BIGINT NULL
playback_100 BIGINT NULL

metric_source VARCHAR

created_at
```

Unique/index:

```text
(post_id, observed_at)
(post_id, post_age_seconds)
```

---

# 25. `drafts`

```text
id UUID PK
creator_id UUID FK

current_post_id UUID FK     // source=draft

status ENUM(
  editing,
  analyzed,
  published,
  abandoned
)

proposed_publish_at TIMESTAMPTZ NULL

created_at
updated_at
```

Do not overwrite previous prediction history when a draft changes.

Use a new analysis/prediction record for each analysis version.

---

# 26. `comparable_sets`

```text
id UUID PK
draft_id UUID FK

generated_at TIMESTAMPTZ

retrieval_version VARCHAR
fallback_level INT

raw_candidate_count INT
comparable_count INT

mean_similarity NUMERIC
median_similarity NUMERIC
effective_sample_size NUMERIC

match_quality NUMERIC

created_at
```

---

# 27. `comparable_set_posts`

```text
id UUID PK
comparable_set_id UUID FK
historical_post_id UUID FK

rank INT

comparable_score NUMERIC
normalized_weight NUMERIC

semantic_similarity NUMERIC
topic_match NUMERIC
intent_match NUMERIC
format_match NUMERIC
era_match NUMERIC
recency_weight NUMERIC
timing_match NUMERIC
scale_match NUMERIC
context_match NUMERIC

created_at
```

Unique:

```text
(comparable_set_id, historical_post_id)
```

---

# 28. `distribution_predictions`

```text
id UUID PK
draft_id UUID FK
comparable_set_id UUID FK

generated_at TIMESTAMPTZ

horizon VARCHAR

reach_percentile_low NUMERIC
reach_percentile_mid NUMERIC
reach_percentile_high NUMERIC

expected_impressions_p25 BIGINT NULL
expected_impressions_p50 BIGINT NULL
expected_impressions_p75 BIGINT NULL

conversation_outlook JSONB
redistribution_outlook JSONB
conversion_outlook JSONB
retention_outlook JSONB

evidence_confidence_score NUMERIC
evidence_confidence_label VARCHAR

reasons JSONB

prediction_version VARCHAR

features_as_of TIMESTAMPTZ

created_at
```

---

# 29. `recommendations`

```text
id UUID PK
prediction_id UUID FK

type VARCHAR
description TEXT
evidence JSONB

creator_decision ENUM(
  applied,
  ignored,
  partially_applied,
  unknown
)

created_at
updated_at
```

Prediction and recommendation remain separate.

---

# 30. `conversation_context_snapshots`

```text
id UUID PK
creator_id UUID FK

observed_at TIMESTAMPTZ

query_terms JSONB

topic_volume BIGINT NULL
previous_window_volume BIGINT NULL
volume_change_ratio NUMERIC NULL

activity_level ENUM(
  low,
  normal,
  elevated,
  extreme
) NULL

momentum ENUM(
  declining,
  stable,
  increasing
) NULL

context_confidence NUMERIC NULL
source VARCHAR NULL

created_at
```

---

# 31. Raw Source Payload Handling

Do not rely on the raw X payload for business logic.

Optional:

```text
x_raw_ingest_records
```

can temporarily preserve:

- request source;
- response body;
- fetched_at;
- adapter version.

Retention should be short and configurable.

Canonical tables are authoritative for product logic.

---

# 32. Post Profile Pipeline

For every imported historical Post:

```text
Raw X Post
↓
Canonical normalization
↓
Language normalization
↓
Topology extraction
↓
Format extraction
↓
Structural feature extraction
↓
Semantic embedding inference
↓
Topic classification
↓
Intent classification
↓
Creator-era assignment
↓
Creator-state association
↓
Retrieval eligibility
↓
Persist Post Profile
```

Important policy boundary:

> Use pre-trained models for inference only. Do not train/fine-tune models on X-derived data without explicit policy clearance.

X currently prohibits using X data to train AI/ML models except specified X/Grok cases.

Reference:

https://docs.x.com/developer-guidelines

---

# 33. External Model/Data Processing Safety

If semantic inference uses an external AI provider:

- confirm vendor does not use submitted X content to train its models;
- configure zero/limited retention where available;
- document subprocessors;
- minimize submitted fields;
- never send unnecessary private account data;
- keep raw X tokens completely separate.

A local/self-hosted embedding model is operationally simpler for privacy if quality is sufficient.

---

# 34. Topic Clustering V1

Do not overbuild clustering.

V1 strategy:

```text
Post embedding
↓
nearest existing creator topic cluster
↓
if similarity >= threshold:
assign cluster
else:
create candidate cluster
```

Cluster fields:

```text
id
creator_id
label
centroid_embedding
post_count
created_at
updated_at
```

Cluster label can be generated from representative Posts.

Keep the raw centroid deterministic and label as presentation metadata.

---

# 35. Intent Classification V1

Use a fixed multi-label vocabulary:

```text
educational
personal_experience
announcement
opinion
news_commentary
question
story
tutorial
launch
achievement
conversation_starter
promotional
```

Persist probabilities + classifier version.

Do not make intent classification the final prediction.

It is a retrieval feature.

---

# 36. Comparable Retrieval — Stage 1

Input:

```text
Draft Post Profile
```

Retrieve candidate Posts constrained by:

```text
same creator
baseline_eligible = true
compatible topology
published before features_as_of
```

Primary retrieval:

```text
pgvector semantic nearest neighbors
```

Target:

```text
CANDIDATE_POOL_SIZE = 100
```

Configurable range:

```text
50–200
```

---

# 37. Comparable Retrieval — Hard Filters

Reject or strongly exclude:

```text
wrong topology
pure repost
corrupt import
missing usable text
insufficient outcome data
promoted without organic separation
future data relative to backtest time
known anomalous record
```

Replies should not dominate standalone comparisons.

Thread roots should primarily compare with thread roots.

---

# 38. Comparable Fine-Ranking V1

Initial deterministic formula:

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

These are **provisional V1 defaults**, not scientifically established values.

Every weight must live in configuration and be backtest-tunable.

Never bury weights as magic constants throughout code.

---

# 39. Comparable Weighting Defaults

Starting configuration:

```yaml
baseline:
  weightExponentGamma: 2.0
  maxSinglePostNormalizedWeight: 0.12

evidence:
  strongNeff: 20
  moderateNeff: 8
  weakNeff: 3

shrinkage:
  tau: 8

rateSmoothing:
  k: 200
```

These values are **initial engineering defaults only**.

They must be validated with walk-forward backtesting.

---

# 40. Effective Sample Size

Given normalized comparable weights:

```text
N_eff =
1 / Σ(wᵢ²)
```

Use `N_eff` for evidence quality rather than only raw comparable count.

Initial evidence labels:

```text
N_eff >= 20:
HIGH

8 <= N_eff < 20:
MODERATE

3 <= N_eff < 8:
LOW

N_eff < 3:
INSUFFICIENT
```

---

# 41. Hierarchical Backoff

When evidence is weak:

```text
Level 1:
same subtopic + intent + format + current era

Level 2:
same topic cluster + intent + format + current era

Level 3:
same topic cluster + compatible format + current era

Level 4:
same topic cluster + compatible recent Posts

Level 5:
general recent creator baseline
```

Persist the fallback level used.

Do not hide fallback from the Evidence Confidence calculation.

---

# 42. Shrinkage

Initial V1 shrinkage:

```text
λ =
N_eff / (N_eff + τ)
```

Then combine:

```text
specific_baseline_weight = λ
broader_baseline_weight = 1 - λ
```

Do not overcomplicate this in V1.

The purpose is stability when the exact comparable sample is small.

---

# 43. Robust Baseline Statistics

For each outcome metric:

```text
Weighted P10
Weighted P25
Weighted P50
Weighted P75
Weighted P90
```

Primary expected interval:

```text
P25 → P75
```

Do not use arithmetic mean as the primary creator baseline.

Robust metrics should remain stable under viral outliers.

---

# 44. Supported Outlook Dimensions

## Reach

Primary:

```text
impressions
```

Supporting normalization:

```text
impressions / followers_at_publish
```

only where follower-at-publication evidence is reliable.

## Conversation

```text
reply count
smoothed reply rate
```

## Redistribution

```text
repost count
repost rate
quote count
quote rate
```

## Conversion

When creator-owned private metrics are available:

```text
profile clicks
profile click rate
URL clicks
URL click rate
```

## Retention

For video:

```text
25%
50%
75%
100%
completion checkpoints
```

---

# 45. Rate Smoothing

Initial V1:

```text
smoothed_rate =
(events + k × broader_baseline_rate)
/
(impressions + k)
```

`k` is configurable.

Purpose:

- prevent tiny denominators from producing absurd rates;
- stabilize early-window metrics.

Do not describe this output as a literal probability.

---

# 46. Percentile Prediction

For pre-publish Reach Outlook:

1. Calculate weighted comparable P25/P50/P75.
2. Map each value into the creator's broader current-era distribution.
3. Convert percentile interval into creator-friendly “Top X–Y%” language.

Example:

```text
Comparable P25:
7,000 impressions
→ 60th current-era percentile

Comparable P50:
9,100
→ 68th percentile

Comparable P75:
12,500
→ 76th percentile
```

Display:

```text
Expected Reach:
Top 24–40%
```

Do not add arbitrary “good timing +12 points” bonuses afterward.

---

# 47. No Double Counting

Core rule:

> **Similarity features determine evidence weight. Historical outcomes determine the prediction.**

Do not use the same features once to select strong historical evidence and then again as manual score bonuses.

Creator–Topic Fit, Format Fit, Timing Fit, etc. are **explanations of evidence**, not arbitrary additions.

---

# 48. Evidence Confidence V1

Do not initially display confidence as a calibrated probability.

Preferred:

```text
Evidence Confidence:
High
```

Optionally internal/UI secondary:

```text
Evidence Score:
81/100
```

Inputs:

```text
effective sample size
median comparable similarity
current-era share
outcome completeness
fallback level
historical IQR/MAD
metric-window coverage
context volatility
```

Exact Evidence Score formula can remain configurable.

The user-facing label is more important than false precision.

---

# 49. Draft Analysis API Flow

```text
POST /drafts
↓
POST /drafts/{id}/analyze
↓
build Draft Post Profile
↓
capture conversation context
↓
retrieve candidates
↓
persist Comparable Set
↓
build Creator Baseline
↓
persist Distribution Prediction
↓
generate explanations
↓
generate optional recommendation
```

Analysis must be idempotent per exact draft version where possible.

A changed draft produces a new analysis version.

---

# 50. Suggested Product API Endpoints

## X connection

```text
GET  /integrations/x/connect
GET  /integrations/x/callback
GET  /integrations/x/status
POST /integrations/x/disconnect
```

## Creator history

```text
POST /creator/history/sync
GET  /creator/history/status
GET  /creator/baseline-summary
```

## Drafts

```text
POST /drafts
GET  /drafts/{id}
PATCH /drafts/{id}
POST /drafts/{id}/analyze
```

## Analysis

```text
GET /drafts/{id}/prediction
GET /drafts/{id}/comparables
GET /drafts/{id}/recommendations
```

## Published Post attachment

```text
POST /drafts/{id}/attach-published-post
```

Payload:

```json
{
  "xPostUrlOrId": "..."
}
```

## Monitoring

```text
GET /posts/{id}/trajectory
GET /posts/{id}/metrics
GET /posts/{id}/postmortem
```

## Archive — SHOULD HAVE

```text
POST /creator/x-archive
GET  /creator/x-archive/status
```

---

# 51. Publishing Workflow

Do not request `tweet.write` in V1.

Recommended experience:

```text
Draft analyzed
↓
Creator sees Outlook + recommendation
↓
Creator copies draft / opens X
↓
Creator publishes manually
↓
Creator pastes Post URL
OR
app finds the creator's latest matching Post
↓
Published Post attached to original Draft
↓
Monitoring begins
```

Advantages:

- lower OAuth privilege;
- simpler policy surface;
- explicit creator action;
- easier hackathon implementation;
- cleaner origin-draft relationship.

---

# 52. Published Post Matching

When user supplies an X Post URL:

1. parse X Post ID;
2. verify it belongs to connected creator;
3. retrieve the Post using official API;
4. canonicalize;
5. connect:

```text
draft.origin
→ published Post
```

If using “find my latest Post” fallback:

- fetch creator's newest Posts;
- match by normalized text/content hash;
- ask creator if ambiguous.

Never silently attach a low-confidence match.

---

# 53. Metric Monitoring Schedule

Standardized windows:

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

Worker strategy:

```text
attach published Post↓
enqueue scheduled snapshot jobs
↓
each job retrieves creator-authorized metrics
↓
persist immutable PostMetricSnapshot
↓
compute same-window percentile
```

A failed window should retry with exponential backoff.

If a window is missed:

- store the actual observation time;
- do not falsify the timestamp;
- nearest-window analytics may be shown with lower evidence quality.

---

# 54. Background Jobs

Recommended queues:

```text
x-sync
post-profile
semantic-inference
baseline-build
context-snapshot
metric-snapshot
postmortem
token-refresh
archive-import
backtest
usage-cost
```

Job properties:

- idempotent;
- retriable;
- observable;
- deduplicated by logical job key;
- no duplicate metric snapshot for same scheduled observation.

---

# 55. Monitoring Job Keys

Examples:

```text
x-sync:{creatorId}:{cursor}
profile:{postId}:{pipelineVersion}
snapshot:{postId}:{window}
postmortem:{postId}:24h
prediction:{draftId}:{contentHash}:{predictionVersion}
```

This prevents duplicate work after worker retries.

---

# 56. Post-Publish Live Status

At every available window:

```text
actual metric
↓
matched historical distribution at same Post age
↓
current percentile
```

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

Current percentile:
79th

Status:
Above expected
```

---

# 57. Percentile Interpretation

Initial V1 labels:

```text
Below P10:
Strong underperformance

P10–P25:
Below expected

P25–P75:
Expected range

P75–P90:
Above expected

Above P90:
Strong outperformance
```

Do not use one global `+20% = good` rule.

---

# 58. 24-Hour Postmortem

At/after 24 hours:

```text
Prediction:
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

Absolute percentile error:
14 points
```

Postmortem should contain:

- original prediction;
- Evidence Confidence;
- actual matched percentile;
- dimension-level result;
- prediction error;
- top explanation;
- whether recommendation was applied.

---

# 59. Backtesting Harness

Build this **before claiming accuracy**.

Walk-forward process:

```text
historical Posts sorted oldest → newest

for each target Post:
  only expose records available before target timestamp
  construct target Post Profile without outcome
  retrieve historical comparables
  create baseline
  predict
  reveal actual outcome
  store evaluation result
```

Absolutely prohibit:

- future Posts;
- future creator state;
- future topic context;
- future feature labels created from later information;
- outcome leakage.

---

# 60. Backtest Metrics

Track:

```text
direction_accuracy
interval_coverage
median_absolute_percentile_error
mean_absolute_percentile_error
overprediction_bias
underprediction_bias
```

Break down by:

```text
topic cluster
intent
format
topology
creator era
N_eff tier
fallback level
evidence label
```

The purpose is to learn where the V1 is reliable.

---

# 61. Acceptance Threshold Philosophy

Do not invent a marketing claim before validation.

V1 can launch internally/hackathon-ready when:

- the algorithm is deterministic and reproducible;
- predictions are auditable;
- backtesting runs without future leakage;
- evidence quality is visible;
- known weak-data cases produce LOW/INSUFFICIENT evidence rather than false confidence.

A later real-user accuracy claim requires measured results.

---

# 62. Recommendation Engine V1

Recommendation should be conservative.

Only produce recommendations supported by historical comparison.

Examples:

```text
Format recommendation:
Your similar technical Posts with images have a higher median repost rate.

Timing recommendation:
Comparable Posts in your proposed window historically outperform this cluster's median.

Structure recommendation:
Similar personal-build explanations perform better than generic commentary.
```

Do **not** generate advice merely because a language model thinks it sounds good.

---

# 63. Recommendation Evidence Contract

Every recommendation must have:

```text
type
claim
supporting comparable subset
supporting metric
sample size
effect direction
evidence confidence
```

If evidence is weak:

```text
No recommendation
```

is a valid outcome.

---

# 64. No Outcome Leakage in Recommendations

Recommendations must be generated from valid historical evidence.

Do not:

```text
find only successful historical Posts
→ infer their surface patterns
→ tell creator to copy those patterns
```

without a matched control/comparison.

For V1, recommendations should be simple and conservative.

---

# 65. X Archive Import — SHOULD HAVE

Architecture support should exist, but archive import should not block core V1.

Flow:

```text
creator uploads ZIP
↓
validate type + size
↓
extract in isolated temporary workspace
↓
allowlist recognized files only
↓
ignore DMs/contact/private irrelevant files
↓
map historical Posts into canonical Post model
↓
deduplicate against API Post IDs
↓
generate Post Profiles
↓
delete raw extracted sensitive leftovers
```

Data minimization:

Import only what materially supports distribution intelligence.

---

# 66. X Archive Parser Contract

Do not hardcode assumptions until a **real current X archive** has been inspected.

Parser should be adapter/version based:

```text
XArchiveAdapterV1
XArchiveAdapterV2
...
```

Unknown files:

```text
ignore by default
```

Never “import everything.”

---

# 67. Privacy Requirements

Core principles:

```text
least privilege
data minimization
explicit creator authorization
clear disconnect/delete path
no sensitive trait inference
no unnecessary follower profiling
no DMs
no address book
no scraping
```

X currently explicitly prohibits sensitive-data derivation and non-API scraping/automation.

Reference:

https://docs.x.com/developer-guidelines

---

# 68. X Policy Guardrails

Hard implementation rules:

1. Official X API only for X platform automation/data retrieval.
2. Do not train/fine-tune ML models on X data without permitted authorization.
3. Do not build auto-like/follow/reply engagement manipulation.
4. Do not infer sensitive attributes.
5. Do not claim access to internal Phoenix ranking scores.
6. Do not claim exact For You impression attribution.
7. Do not market guaranteed virality.
8. Recheck X Developer Policy before public launch.

Policy reference:

https://docs.x.com/developer-guidelines

---

# 69. Cost & Usage Instrumentation

Every X API request should record:

```text
endpoint_family
creator_id
request_time
resources_returned
estimated_cost
http_status
rate_limit_headers
retry_count
```

Create a Usage dashboard/admin view:

```text
today's Post reads
today's User reads
estimated spend
cost per creator
cost per analysis
cost per monitored Post
```

This is not optional for production.

---

# 70. Cost Guards

Configurable protections:

```text
MAX_INITIAL_POST_READS
MAX_HISTORY_POST_READS_PER_CREATOR
MAX_TOPIC_SEARCH_RESULTS
MAX_FOLLOWER_READS
MAX_X_SPEND_PER_DAY
MAX_X_SPEND_PER_CREATOR
```

If budget threshold is reached:

- degrade optional context first;
- never silently accumulate uncontrolled API cost.

---

# 71. V1 UX Flow

## Screen 1 — Connect X

```text
Connect your X account
```

Explain requested read permissions plainly.

## Screen 2 — Building Your Baseline

Show progress:

```text
Imported 300 Posts
Eligible: 247
Topic clusters: 6
Current-era evidence: Moderate
```

## Screen 3 — Creator Baseline Summary

Show:

- strongest topic clusters;
- typical reach distribution;
- format distribution;
- evidence quality;
- current monitored-history depth.

## Screen 4 — Analyze Draft

Creator writes/pastes draft.

Optional:

- proposed publish time;
- goal.

## Screen 5 — Distribution Outlook

Example:

```text
Expected Reach:
Top 24–39%

Evidence:
High

Comparable Posts:
42
Effective N:
27.8
```

Then:

```text
Reach:
Above normal

Conversation:
Strong

Redistribution:
Around normal

Profile discovery:
Above normal
```

## Screen 6 — Why

Top evidence:

```text
same topic cluster
same technical-story intent
same current creator era
similar format
strong timing evidence
```

Show top 3–5 historical comparables.

## Screen 7 — Optional Recommendation

Evidence-backed only.

## Screen 8 — Publish

Creator publishes manually and attaches Post.

## Screen 9 — Live Trajectory

5m / 15m / 30m / 1h / etc.

## Screen 10 — 24h Postmortem

Prediction vs actual.

---

# 72. Frontend Data States

Every intelligence UI must support:

```text
LOADING
SUFFICIENT_EVIDENCE
MODERATE_EVIDENCE
LOW_EVIDENCE
INSUFFICIENT_EVIDENCE
X_CONNECTION_EXPIRED
API_RATE_LIMITED
METRIC_UNAVAILABLE
POST_NOT_FOUND
```

Do not turn missing evidence into fake predictions.

---

# 73. Analysis Response Shape

Illustrative API response:

```json
{
  "predictionId": "...",
  "horizon": "24h",
  "reach": {
    "expectedTopPercentLow": 24,
    "expectedTopPercentHigh": 39,
    "expectedImpressions": {
      "p25": 7200,
      "p50": 9400,
      "p75": 13800
    }
  },
  "evidence": {
    "label": "HIGH",
    "score": 81,
    "rawComparableCount": 42,
    "effectiveSampleSize": 27.8,
    "fallbackLevel": 1
  },
  "outlooks": {
    "conversation": "STRONG",
    "redistribution": "NORMAL",
    "conversion": "ABOVE_NORMAL",
    "retention": null
  },
  "reasons": [
    "...",
    "...",
    "..."
  ]
}
```

---

# 74. Comparable Response Shape

```json
{
  "comparableSetId": "...",
  "items": [
    {
      "postId": "...",
      "xPostId": "...",
      "rank": 1,
      "score": 0.91,
      "reasons": [
        "same topic cluster",
        "same intent",
        "current creator era",
        "same topology"
      ]
    }
  ]
}
```

Do not expose internal embedding vectors.

---

# 75. Observability

Track application metrics:

```text
x_api_requests_total
x_api_errors_total
x_api_estimated_cost_total

history_sync_duration_seconds
post_profile_duration_seconds

comparable_retrieval_duration_seconds
comparable_effective_sample_size

prediction_generation_duration_seconds

metric_snapshot_success_total
metric_snapshot_failure_total

postmortem_generated_total

backtest_predictions_total
backtest_interval_coverage
backtest_percentile_error
```

Logs should include:

```text
creator_id
draft_id
post_id
prediction_id
comparable_set_id
job_id
```

Never include tokens.

---

# 76. Security

Requirements:

- encrypted X tokens;
- CSRF-safe OAuth state;
- PKCE verifier handling;
- strict redirect URI configuration;
- authenticated ownership checks on every Creator/Post/Draft route;
- signed upload URLs for archive import;
- ZIP bomb/path traversal defenses;
- file-size limits;
- no arbitrary archive execution;
- rate limiting;
- secrets outside repository;
- production database encryption/backups.

---

# 77. Core Algorithm Unit Tests

Test:

```text
ComparableScore calculation
weight normalization
single-post cap
effective sample size
weighted quantiles
shrinkage
rate smoothing
percentile mapping
evidence tier classification
fallback behavior
outlier classification
same-window comparison
```

Every numerical routine should have deterministic fixtures.

---

# 78. Retrieval Tests

Fixtures should verify:

- semantic match beats timing-only match;
- same intent beats unrelated intent;
- reply does not dominate standalone baseline;
- current-era match receives expected advantage;
- future Post cannot appear in backtest comparables;
- ineligible promoted Post excluded;
- comparable order reproducible.

---

# 79. X Adapter Integration Tests

Mock official X responses for:

```text
timeline pagination
refresh token
expired token
429 rate limit
partial metric availability
30-day private metric expiry
missing media
long-form/note Post
edited Post
deleted Post
```

Canonical mapping must remain stable if X omits optional fields.

---

# 80. Job Tests

Verify:

- snapshot jobs are idempotent;
- retry does not duplicate records;
- 24h postmortem waits for appropriate metrics;
- failed token refresh pauses X-dependent jobs;
- duplicate sync does not duplicate Posts;
- missed metric window records real observed time.

---

# 81. Backtest Tests

Hard requirements:

- target Post outcome is hidden before prediction;
- only earlier Posts are queryable;
- future creator state inaccessible;
- future context inaccessible;
- prediction persisted before actual result is revealed;
- rerun with same versions/config is reproducible.

---

# 82. E2E Hackathon Demo Test

A single creator should be able to:

1. connect X;
2. sync historical Posts;
3. see baseline built;
4. submit draft;
5. receive Outlook;
6. inspect comparables;
7. see recommendation;
8. attach published Post;
9. see current matched percentile;
10. open postmortem for a previously monitored/demo Post.

For live hackathon timing, seed a previously monitored Post so the 24h postmortem can be demonstrated immediately.

---

# 83. Acceptance Criteria — Core

V1 is functionally complete when:

- [ ] OAuth connects and refreshes reliably.
- [ ] At least 200 recent Posts can be progressively ingested.
- [ ] Post Profiles are generated and versioned.
- [ ] At least one creator topic-cluster representation exists.
- [ ] Draft analysis persists a Comparable Set.
- [ ] Comparable retrieval never uses historical outcomes as similarity inputs.
- [ ] `N_eff` is calculated.
- [ ] Baseline engine produces weighted P25/P50/P75.
- [ ] Distribution Outlook returns a relative percentile interval.
- [ ] Evidence Confidence falls for weak/volatile history.
- [ ] Creator can inspect top comparable Posts.
- [ ] Recommendation is optional and evidence-backed.
- [ ] Published Post can be attached to Draft.
- [ ] Metric snapshots are persisted by age window.
- [ ] Same-window historical percentile is calculated.
- [ ] 24h postmortem compares prediction vs actual.
- [ ] Walk-forward backtest runs without future leakage.
- [ ] X API usage/cost is recorded.
- [ ] No `tweet.write` permission is required.
- [ ] No ML training on X data is implemented.

---

# 84. Acceptance Criteria — Scientific Honesty

The UI and API must never claim:

```text
"X will rank this 82/100"
"X's algorithm score is..."
"Guaranteed viral"
"X pushed 67% of these impressions through For You"
```

unless X explicitly provides such data.

Allowed framing:

```text
"Our model expects..."
"Relative to your historical comparable Posts..."
"Evidence Confidence..."
"Current matched percentile..."
```

---

# 85. Implementation Phases

## Phase 0 — Project Foundation

- application scaffold;
- PostgreSQL;
- pgvector;
- Redis/BullMQ;
- auth/users;
- migrations;
- observability;
- config system.

## Phase 1 — X Connection

- OAuth 2.0 PKCE;
- encrypted token storage;
- refresh;
- creator lookup;
- connection status.

## Phase 2 — History Ingestion

- timeline pagination;
- cost-aware progressive sync;
- canonical X adapter;
- Post/media/entity persistence;
- creator-state snapshots.

## Phase 3 — Post Profiles

- normalized text;
- semantic inference;
- topic representation;
- intent;
- topology;
- format;
- creator era;
- eligibility;
- feature versions.
## Phase 4 — Comparable Retrieval

- vector candidate search;
- hard filters;
- deterministic fine rank;
- fallback;
- Comparable Set persistence;
- effective sample size.

## Phase 5 — Baseline Engine

- weighted robust quantiles;
- hierarchical shrinkage;
- outcome dimensions;
- percentile mapping;
- Evidence Confidence.

## Phase 6 — Draft Analysis

- draft API/UI;
- Post Profile;
- context snapshot;
- prediction;
- explanations;
- recommendation.

## Phase 7 — Published Post Monitoring

- attach Post;
- metric jobs;
- same-window comparisons;
- live trajectory UI.

## Phase 8 — Postmortem

- 24h evaluation;
- error calculation;
- dimension-level evaluation;
- prediction audit.

## Phase 9 — Backtesting

- walk-forward runner;
- evaluation metrics;
- config experimentation;
- report.

## Phase 10 — Polish

- cost guardrails;
- failure states;
- security review;
- E2E;
- hackathon demo fixtures.

---

# 86. Recommended Build Order

Do **not** begin by designing a sophisticated dashboard.

Build the intelligence spine first:

```text
X Adapter
↓
Canonical Posts
↓
Post Profiles
↓
Comparable Retrieval
↓
Baseline Engine
↓
Prediction
```

Then build UX around real outputs.

This prevents a polished UI from hiding an unvalidated core.

---

# 87. Configuration Contract

Create a versioned config object:

```ts
interface IntelligenceConfig {
  retrieval: {
    candidatePoolSize: number;
    finalComparableTarget: number;

    weights: {
      semantic: number;
      topic: number;
      intent: number;
      format: number;
      era: number;
      recency: number;
      timing: number;
      scale: number;
      context: number;
    };
  };

  baseline: {
    weightExponentGamma: number;
    maxSinglePostNormalizedWeight: number;
    shrinkageTau: number;
    rateSmoothingK: number;
  };

  evidence: {
    strongNeff: number;
    moderateNeff: number;
    weakNeff: number;
  };

  monitoring: {
    windowsSeconds: number[];
  };
}
```

Every prediction stores the config/prediction version used.

---

# 88. Versioning

Version:

```text
canonical schema
feature pipeline
embedding model
topic classifier
intent classifier
retrieval algorithm
baseline algorithm
prediction output
```

A prediction should always be reproducible from:

```text
input snapshot
+
feature versions
+
Comparable Set
+
IntelligenceConfig version
```

---

# 89. Backtest-Driven Tuning

Do not tune parameters against the same Posts used to report final accuracy.

Eventually split historical evaluation:

```text
development/tuning period
validation period
held-out evaluation period
```

For creator-specific small data, prefer walk-forward validation.

The V1 priority is not theoretical sophistication.

It is:

> **prevent leakage, expose uncertainty, and measure error honestly.**

---

# 90. Performance Targets

Initial engineering targets, not contractual SLAs:

```text
Draft semantic/profile generation:
< 3s typical after model warmup

Comparable retrieval:
< 500ms database/re-ranking target

Full Distribution Outlook:
< 5s typical

History sync:
async with progress

Metric polling:
background only
```

Never block onboarding UI until every possible historical page is fetched.

Provide useful progress incrementally.

---

# 91. Graceful Degradation

If topic-count context fails:

```text
run prediction without context
lower context confidence
```

If non-public metrics unavailable:

```text
show Reach/Conversation/Redistribution
mark Conversion unavailable
```

If few comparables:

```text
back off
widen interval
lower Evidence Confidence
```

If X temporarily rate-limits:

```text
queue retry
show stale timestamp
do not fabricate updated metrics
```

---

# 92. Data Retention

Define retention explicitly.

Suggested V1:

- canonical creator/Post analytics: retained while account connected or according to user agreement;
- access/refresh tokens: until disconnect/revoke;
- raw X API responses: short-lived/debug only;
- uploaded X archive ZIP: delete after successful parsing unless user explicitly asks to retain;
- extracted archive files: temporary only;
- irrelevant private archive data: never persisted;
- job logs: no raw sensitive payloads.

---

# 93. Disconnect/Delete Flow

On creator disconnect:

1. mark X connection revoked;
2. delete encrypted tokens;
3. stop scheduled metric jobs;
4. explain which analytics data remains;
5. offer deletion of imported/stored creator-derived data;
6. respect applicable X policy/compliance requirements.

---

# 94. Key Risks

## Risk: X API cost

Mitigation:

- progressive history;
- no follower graph in core;
- counts before search;
- usage instrumentation;
- hard spend limits.

## Risk: X API/policy changes

Mitigation:

- adapter layer;
- config-based fields/endpoints;
- policy recheck before launch;
- never couple canonical DB to X payload.

## Risk: false accuracy

Mitigation:

- percentile ranges;
- Evidence Confidence;
- no exact X score claim;
- walk-forward backtesting;
- postmortem error tracking.

## Risk: sparse creator history

Mitigation:

- hierarchical backoff;
- broad current-era baseline;
- low-confidence state;
- optional archive import later.

## Risk: viral outliers

Mitigation:

- weighted robust quantiles;
- P25/P50/P75;
- outlier tags;
- no mean-first prediction.

## Risk: leakage

Mitigation:

- descriptive/outcome separation;
- `featuresAsOf`;
- persisted Comparable Sets;
- time-aware backtesting.

---

# 95. What We Intentionally Do Not Need Before Coding

We do **not** need:

- perfect statistical constants;
- every possible creator category;
- trained proprietary model;
- follower-level audience graph;
- X Archive parser finalized;
- multi-platform abstraction;
- automatic posting;
- real causal-lift claims.

Those can come after the core loop works.

---

# 96. Definition of V1 Success

The technical V1 succeeds if it can truthfully do this:

```text
Creator connects X
↓
System builds creator-specific history
↓
Creator enters draft
↓
System finds auditable historical comparables
↓
System calculates robust baseline
↓
System predicts a relative Reach range
↓
System explains evidence strength
↓
Creator publishes
↓
System measures actual trajectory
↓
System tells creator whether the prediction was right
```

If that works reliably, we have a real **Distribution Intelligence V1**.

---

# 97. Handoff to Coding Agent

The implementation agent should treat the documents as layered specifications:

1. `X_DISCOVERY_DISTRIBUTION_MVP.md`  
   Product thesis and X-only scope.

2. `X_DISTRIBUTION_INTELLIGENCE_RESEARCH_FINDINGS.md`  
   X data/recommendation-system/API research and limitations.

3. `X_DISTRIBUTION_OUTLOOK_V1_DESIGN.md`  
   Comparable retrieval, Post Profile, Creator Baseline Engine, prediction methodology.

4. `X_DISTRIBUTION_INTELLIGENCE_V1_IMPLEMENTATION_BLUEPRINT.md`  
   Concrete implementation contract and execution phases.

The agent must not silently broaden scope beyond the V1 cut line.

---

# 98. Official References

## X Recommendation Architecture

https://github.com/xai-org/x-algorithm

https://github.com/xai-org/x-algorithm/tree/main/phoenix

https://github.com/xai-org/x-algorithm/blob/main/phoenix/README.md

## X OAuth 2.0 PKCE

https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code

## X User Post Timelines

https://docs.x.com/x-api/posts/timelines/introduction

## X Metrics

https://docs.x.com/x-api/fundamentals/metrics

## X Recent Search

https://docs.x.com/x-api/posts/search/quickstart/recent-search

## X Post Counts

https://docs.x.com/x-api/posts/counts/introduction

## X Followers

https://docs.x.com/x-api/users/get-followers

## X Reposted By

https://docs.x.com/x-api/posts/get-reposted-by

## X API Pricing

https://docs.x.com/x-api/getting-started/pricing

## X Developer Guidelines

https://docs.x.com/developer-guidelines

---

# Final Implementation Principle

The implementation should preserve one chain of evidence:

```text
X/source data
→ canonical Post
→ descriptive Post Profile
→ comparable historical Posts
→ explicit similarity weights
→ robust historical outcomes
→ percentile prediction
→ Evidence Confidence
→ actual monitored result
→ postmortem error
```

Every prediction should be explainable through that chain.

That auditability—not a flashy opaque “AI score”—is what gives V1 a credible foundation.