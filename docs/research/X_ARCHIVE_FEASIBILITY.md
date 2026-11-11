# X creator archive feasibility — COD-369

**Reviewed:** 9 November 2026
**Decision:** **Conditional Go** for COD-370's isolated, synthetic-tested parser work. **No real archive ingestion, embedding inference, external-model transfer, or production retention is cleared by this research.**
**Sample status:** No current creator export was supplied or inspected. The utility and tests use synthetic data only.

## Finding

X's current Help Center documents a downloadable ZIP archive and says it contains machine-readable HTML and JSON with account information, posts, direct messages, media, contacts, follows, inferred interest/demographic information and other material. The archive is described as a snapshot of account information and post history starting with the first post. The public documentation does **not** specify the post-history file names, schema version, field types, timestamp encoding, topology keys, metric coverage, archive-generation timestamp, or whether per-post metrics are included in every export. It does not promise historical metric snapshots.

The previous COD-369 discussion of a JavaScript-assignment wrapper and `data/tweets.js` is a parser hypothesis to verify against an owner-provided export, not confirmation of this account's current layout. The local inspector deliberately recognizes only exact candidate paths (`data/tweets.js`, `data/tweets.json`) and a narrowly defined `window.YTD.tweets[.partN] = JSON;` wrapper. The only supported evidence so far is that synthetic fixture shape is parsed safely. Do not expand this allowlist or accept other wrappers until a sample is inspected and the mapping is reviewed.

## Field availability and missingness

| Data needed | X archive public documentation | Candidate archive mapping (unverified) | Archive feasibility today | Official API comparison |
| --- | --- | --- | --- | --- |
| Post ID | Says the archive includes posts; does not document an ID field or its encoding | `id`, `id_str`, `tweet_id` | **Unknown until sample** | User-post timeline returns Posts; canonical API objects have post IDs |
| Publication timestamp | Does not document the schema or timestamp field | `created_at`, `timestamp_ms`, `created_at_utc` | **Unknown until sample** | Timeline supports created-time fields and time filters |
| Post text | Says archive includes posts; field encoding not documented | `full_text`, `text` | Content likely exists, but exact field and completeness remain **unverified** | API post object includes text when requested/permitted |
| Reply topology | No schema commitment | `in_reply_to_status_id` variants | **Unknown until sample** | API can expose referenced-post relationships where available |
| Repost topology | No schema commitment | nested `retweeted_status` | **Unknown until sample** | API relationship fields distinguish repost references where returned |
| Quote topology | No schema commitment | `is_quote_status`, `quoted_status_id` or nested object | **Unknown until sample** | API reference fields can distinguish quote relationships where returned |
| Likes, replies, reposts, quotes, bookmarks | Archive overview does not enumerate counters | candidate legacy flat counters or nested `public_metrics` | **Unknown until sample**; any present counters are one snapshot unless another observed-at record exists | API metrics documentation lists public counter fields; a read observes values at retrieval time |
| Impressions | Archive help does not promise them | candidate `impression_count` | **Unknown; do not assume present** | Current API metrics docs list `public_metrics.impression_count`; this does not backfill old values or a trajectory |
| Early-age snapshots / time series | Not documented | No safe mapping assumed | **Not established**; a one-time archive is not evidence of first-hour/first-day metrics | Requires actual timestamped observations collected at those ages; later API reads do not recreate them |
| Media metadata | Help Center says archive includes media attached to posts, DMs and Moments; does not define per-post metadata | candidate `entities.media`, `extended_entities.media` | **Unknown until sample**; media files may be separate from post records | API exposes attachment/media fields; access and metric availability still depend on entitlement |
| Metric observation timestamp | Archive described as a snapshot, but export-time field is undocumented | No archive metric observation time assumed | **Missing unless verified**; import time must not be mistaken for the archive's measurement time | API retrieval time can be recorded as the observation time of the returned counters |
| Source provenance | The download itself is from the owner flow; no manifest schema documented | exact allowlisted entry, byte count, ZIP CRC in local inspector output | Tool records only local entry-level provenance, not owner identity or authenticity | API response can record endpoint, account, request/observation time and provider source |

The percentages and ratios BipMe might calculate depend on exact denominators, metric definitions and matching observation windows. A creator archive may support post-level descriptions and counters if the sample confirms them, but cannot be treated as an early-engagement dataset by default. Missing or incompatible counters must remain explicit gaps rather than zeros.

## COD-345 canonical contract handoff

If COD-370 later imports a verified sample, map into the existing Platform-owned contracts rather than storing provider payloads in business rows:

| Archive concept after verification | Existing canonical field/contract | Import rule |
| --- | --- | --- |
| X post identifier | `CanonicalPost(platform="x", external_post_id=...)` | Required, preserved as a string; deduplicate by platform ID |
| Publication timestamp | `CanonicalPost.published_at` | Require a timezone-aware value; do not substitute archive extraction time |
| Availability/deletion | `CanonicalPost.availability`, `deleted_at` | Preserve unavailable/deleted state; creator deletion must cascade through derived data |
| Reply/quote topology | `CanonicalPost.topology`, external parent/reference IDs | Set reply/quote only when exact relationship evidence is present. Assign `original` only when the verified schema establishes a non-reply/non-quote post. If a relationship signal exists but its reference is missing or unusable, exclude the record from comparable selection (or quarantine it); the current canonical contract has no unknown topology value, so do not coerce it to `original` or infer from text. |
| Repost topology | No `repost` value in current `CanonicalPost.topology` constraint (`original`, `reply`, `quote`) | **No direct mapping**; COD-370/Platform must explicitly exclude or extend its owned contract before importing reposts |
| Descriptive features | Versioned COD-350 `PostProfileRecord` | Process only after specific content-analysis rights are confirmed; unknown remains `None`, not guessed |
| Engagement counters | Append-only `OutcomeObservationRecord` | Require documented metric definition/unit, state, real observation time and justified `window_kind/window_key`; otherwise do not treat as a comparable outcome |
| Source evidence | `OutcomeObservationRecord.provenance` and importer metadata | Record archive source/version and per-field provenance without retaining unrelated raw payloads |

The current `OutcomeObservationRecord` requires `observed_at >= published_at` and an exact metric definition, unit and window. A local import timestamp is not proof of when X captured a counter. If the export does not identify a trustworthy metric capture/export time and semantics, the importer must not fabricate an age-aligned or mature outcome; preserve the field as unavailable for baseline use until a compatible source/window is available. `CanonicalPost` does not have a raw-text business column, so any derived profile or embedding still needs an authorized processing purpose and deletion path.

## Rights and data handling

This is a product/research reading of public terms, not legal advice or a ruling on BipMe's use case. X's general Terms say creators retain rights to their content and grant X a license; that grant is **to X**, not a blanket downstream AI-processing grant to BipMe. The same Terms direct developer-feature users to the Developer Agreement and Developer Policy.

| Activity | Current evidence | COD-369 disposition |
| --- | --- | --- |
| Creator requests/downloads their own archive | X Help Center documents the authenticated account-owner export flow | **Supported as an X product capability**; this alone does not authorize BipMe's processing |
| Local inspection of a voluntarily supplied copy | Archive content is creator content, but the export documentation does not define a third-party service license for this workflow | **Unresolved for BipMe**; obtain specific terms/legal review before real processing |
| Deterministic descriptive analysis of imported post text | Developer Agreement grants analysis of Licensed Material only as explicitly approved by X; whether archive-imported material and this use fall within that regime needs authoritative interpretation | **Unresolved; do not run on real text yet** |
| Pretrained local embedding inference | Agreement prohibits use of X API/X Content to train or fine-tune a foundation/frontier model; it does not clearly decide ordinary inference through a pretrained embedding model for this archive-first service | **Unresolved; local inference is not automatically exempt** |
| Model training/fine-tuning on X-derived content | Developer Agreement explicitly prohibits training/fine-tuning foundation or frontier models on X API or X Content | **Prohibited for this plan** |
| Transfer of post text to GroqCloud or another external model provider | Third-party processor transfer, retention, training and subprocessor terms are not resolved by archive possession or creator consent | **Unresolved; do not transfer real X-derived text** |
| Offline retention and deletion | Developer Policy requires stored X Content to be kept current and removed/modified after on-X changes; it sets a 24-hour response to an X/user request. Applicability to archive-imported copies and derived profiles/embeddings needs review | **Implement deletion capability before real data; exact retention and deletion scope unresolved** |
| DMs, contacts, credentials, private or unrelated account data | X export can contain these categories; no BipMe requirement needs them | **Exclude from processing**; the tool never opens non-allowlisted entry bodies |
| Cross-creator content reuse or niche corpus | Creator export concerns the owner's archive and does not authorize reuse of third-party posts | **Not authorized by this task** |

The Developer Agreement also restricts redistribution of X Content and says API/content analysis must be explicitly approved. If X confirms the creator-archive use is within developer terms, the app must still honor the Developer Policy's privacy, content-update and removal requirements. Counsel/X should answer in writing whether the precise archive-only workflow, derived feature storage, embedding inference and any processor transfer are allowed.

## Conditional Go criteria for COD-370

COD-370 may implement a narrowly scoped importer using synthetic fixtures and the existing canonical schema. Before enabling real data, require all of the following:

1. Written product/legal/X confirmation for owner-history parsing and local inspection before inspecting real archive contents; separately confirm descriptive analysis, local pretrained inference (if desired), storage, derived embeddings, deletion and any external transfer. Until resolved, use synthetic fixtures only and keep real-content inference and model transfer disabled.
2. After the required inspection permission is confirmed, inspect a voluntary, recent owner export locally; record archive date/version and exact post-history path, wrapper, fields and coverage counts only. Never commit or upload the archive.
3. An explicit allowlist and field mapping backed by the sample, plus importer tests for missing/changed fields. Preserve real `published_at`, an actually justified metric `observed_at`, exact metric definitions/windows and provenance.
4. Secure private BipMe session and owner match independent of X OAuth; encrypted/isolated temporary handling; no unrelated archive files; strict byte/entry/ratio/time limits; raw archive cleanup; revocation/deletion of canonical and derived data.
5. A report usability check against COD-378: count posts with usable IDs/timestamps, compatible topology, supported descriptive inputs and observed metrics; distinguish posts with counters from posts with impressions and from age-aligned observations. Do not claim early-window outcomes from final counters.

Until these checks pass, archive-first ingestion is not production-ready. The report-first API can still return explicit insufficient-evidence or partial states without fabricated observations.

## Safe local inspection utility

From `apps/api`, run `uv run python tools/inspect_x_archive.py /absolute/path/to/creator-export.zip` on a real archive only after written product/legal/X review confirms that local inspection is authorized; voluntary provision alone does not establish processing rights. Until then, use synthetic fixtures only. The path is required; the command does not upload, store, or print the supplied archive path. It inspects only exact `data/tweets.js` or `data/tweets.json` entries, rejects unsafe ZIP paths/symlinks/duplicates, enforces entry, total-size, selected-size and compression-ratio limits, parses a narrow JSON or assignment-wrapped JSON form without evaluating JavaScript, and emits aggregate availability counts only. Tests use synthetic in-memory ZIP data. It is not a production importer or proof of current X archive compatibility.

## Official evidence checked on 9 November 2026

- X Help Center, [How to download your X archive](https://help.x.com/en/managing-your-account/how-to-download-your-x-archive): owner request flow; ZIP; machine-readable HTML/JSON; listed archive categories.
- X Help Center, [How to access your X data](https://help.x.com/en/managing-your-account/accessing-your-x-data): archive is a snapshot; account and post-history categories.
- X, [Terms of Service](https://x.com/en/tos): effective 9 October 2026; content ownership/license terms; directs developer-feature use to developer terms.
- X, [Developer Agreement](https://docs.x.com/developer-terms/agreement): updated 27 April 2026; analysis authorization, AI training restriction and removal obligations.
- X, [Developer Policy](https://docs.x.com/developer-terms/policy): privacy/consent and offline content update/removal rules.
- X API, [Timelines](https://docs.x.com/x-api/posts/timelines/introduction): `GET /2/users/:id/tweets`, most recent 3,200, pagination and time filters.
- X API, [Metrics](https://docs.x.com/x-api/fundamentals/metrics): current public metric fields include impressions, replies, reposts, quotes, likes and bookmarks; private/organic/promoted metrics require user context and are restricted to posts under 30 days old.

The public archive documentation does not provide a downloadable sample archive or a versioned field schema. A current owner-provided sample and case-specific rights decision remain manual blockers.

## COD-370 synthetic parser foundation

`bipme.posts.archive.parse_synthetic_archive` is an internal, synthetic-fixture-only
function, not an upload endpoint or production importer. Its explicit fixture marker
is an accidental-use guard, **not proof of authorization or source rights**. A caller
supplies the synthetic creator UUID; no archive content establishes ownership.
The inspector CLI now delegates to `bipme.integrations.x_archive_inspection` so ZIP
validation and inert decoding are shared. The original CLI command remains valid.

Lifecycle: validate local regular-file ZIP and every member's metadata → select exactly
one reviewed candidate path → read bounded bytes → decode strict UTF-8 and inert JSON →
validate every record → return an immutable typed batch → construct transient canonical
rows for synthetic database tests. No archive is extracted, copied, logged, uploaded,
or deleted. The caller owns the input and its cleanup; the parser closes ZIP handles
on failure and retains no temporary files. It does not promise secure erasure of Python
objects or caller-owned files.

The synthetic mapper intentionally supports only `id_str`, legacy timezone-bearing
`created_at`, optional `full_text`, explicit reply/quote IDs and nested repost identity.
Alternate fields are not silently treated as verified mappings. Unknown topology fields,
ambiguous relationships, invalid counters, duplicate IDs and malformed records reject
the batch; reposts are explicitly excluded and counted. Other unsupported fields are
counted by record and not retained. This is a versioned candidate schema, **not detection
or verification of an actual X export version**. Text is omitted unless explicitly
requested for a synthetic fixture, and dataclass representations hide content.

Publication time maps to `CanonicalPost.published_at`; import time is recorded only in
provenance. `source_observed_at` stays null. Candidate likes/reposts/replies/quotes/bookmark
counters retain count units, missingness and unknown measurement time in memory;
**none becomes an OutcomeObservationRecord**. No impressions, age-aligned windows,
media inference, profiles, embeddings, report analysis or provider calls are produced.
The API history normalizer cannot be used directly: it assumes an actual provider-read
observation time and generates mature cumulative observations. Canonical identity,
creator ownership, topology and uniqueness reuse COD-345/COD-348 contracts instead.

The deterministic import identity includes creator UUID, exact selected payload/path,
mapping version and text-retention mode. Replay returns the same identity; syntactically
changed payloads intentionally differ. PostgreSQL tests demonstrate rollback/retry,
canonical uniqueness and foreign-owner conflicts. They do **not** establish a durable
production resumable importer, concurrent receipt arbitration or import-status endpoint.
A future writer must atomically coordinate creator-scoped receipts and canonical writes,
check existing row ownership, reject mismatched replay input, preserve counts/provenance,
and never overwrite official API evidence or resurrect deleted posts. Batches are
all-or-nothing; no malformed record is silently discarded. No migration is added.

Limits: shared inspector caps compressed ZIP at 256 MiB, 2,000 entries, 1 GiB declared
expanded bytes and ratio 200; the mapper further caps selected payload at 4 MiB,
10,000 records and JSON nesting at 64. Duplicate JSON keys and non-finite numbers are
rejected. Only stored/deflated regular entries and directories are accepted; unrelated
bodies are never opened. A five-second cooperative deadline is checked during record
mapping. ZIP-directory loading, decompression and JSON decoding are bounded by input
sizes, not a hard OS CPU/RSS deadline; isolated worker resource limits remain a production
requirement. Parsing does not authenticate the ZIP or its purported author.

Future Platform/Web handoff: after COD-369's written inspection, parsing, retention and
processing approvals plus a verified current sample, design a bounded private upload
and typed status API. Bind creator exclusively from COD-346's server-verified session,
require CSRF, current consent and independently verified owner/source policy; X OAuth
must remain optional. Supply coverage and exclusions without exposing private payloads.
Do not wire this synthetic module into Web onboarding or existing report/evidence APIs.
Before real use, define encrypted isolated temporary storage, crash cleanup, retention
TTL, revocation and canonical/derived deletion, safe source updates, durable replay and
concurrency behavior. Separate explicit approvals are needed for local analysis,
embedding inference and any external processor transfer. No real archive is cleared by
these tests, and neither COD-369 nor full COD-370 is completed by this foundation.
