# BipMe — Security, privacy and API cost controls

**Current state (9 Nov 2026):** COD-346 implements private server-side sessions, mockable PKCE, read-only scope validation, encrypted token persistence, refresh and disconnect. X OAuth remains disabled by default; no live X authorization or API calls have been made. Account-specific X access, numeric user ID and processing-rights decisions remain external gates.

## Threats worth handling immediately

- Unauthorized access to the one-account private experiment.
- OAuth code interception, CSRF, lost state/PKCE verifier, stale refresh tokens and token disclosure.
- Unexpected X API charges from pagination, retries, repeated sync or accidental unbounded jobs.
- X data being retained or sent to AI providers beyond allowed processing purposes.
- Logs, fixtures, screenshots or CI artifacts exposing tokens or creator-private metrics.

## Account and session design

- Official X OAuth **Authorization Code Flow with PKCE**, using a random one-time verifier and state, validated server-side.
- Request least-privilege scopes: `tweet.read`, `users.read`, and `offline.access` only when needed to refresh. Do not request write/DM scopes for this initial phase.
- Resolve the authenticated X account ID server-side and compare with the explicitly configured allowlist. Reject any other identity even if OAuth succeeded.
- Maintain an application session **server side** and send an HttpOnly, Secure (HTTPS), appropriately SameSite-scoped session cookie. Protect mutating routes against CSRF.
- Encrypt X access and refresh tokens at rest, avoid printing tokens in logs/traces, rotate keys where feasible and handle revocation/disconnect.
- Store all secrets outside Git; `.env.example` contains placeholders or local-only database examples. Never check in a real `.env`.

### COD-346 implementation boundary

- `POST /api/auth/private/session` verifies a server-provisioned high-entropy `BIPME_PRIVATE_LOGIN_SECRET` for the single configured `BIPME_CREATOR_ID`. This private BipMe identity path supports archive-only use without X OAuth and does not create public signup or creator records. The browser receives only a random session cookie; the database stores its SHA-256 digest, creator, method, expiry and revocation time.
- Session cookies are HttpOnly and SameSite=Lax, use `__Host-` naming with Secure/Path=/ in production, and fail closed if production cookie security or creator configuration is absent. Set `BIPME_AUTH_COOKIE_SECURE=false` only for local loopback HTTP development. Session lifetime is bounded by configuration. `GET /api/auth/session` returns a session-derived CSRF token, and unsafe operations require it in `X-CSRF-Token`; logout revokes the database session and clears its cookie.
- X authorization is opt-in and requires `BIPME_X_OAUTH_ENABLED=true`, a confidential client ID/secret, exact callback URI, app origin, immutable numeric account allowlist, and token-encryption key ring. `.env.example` keeps OAuth disabled. The authorization start stores hashed state/browser nonce and encrypted PKCE verifier in `oauth_authorization_transactions`; state is browser-bound, expires after ten minutes, and is marked consumed before the callback processes consent or exchanges a code. The callback validates the exact callback URI, requires the read-only scope set, resolves the account through the provider and rejects an ID outside the immutable allowlist.
- X access/refresh tokens are encrypted using the `cryptography` Fernet implementation, tagged with the existing `BIPME-ENC` marker and a server-only key version. `BIPME_TOKEN_ENCRYPTION_KEYS` is a JSON map of key version to Fernet key; retain old keys while encrypted rows remain, set the new active version, and call the internal rewrap operation before retiring old keys. Refresh rotates encrypted values; disconnect attempts provider revocation and always clears local ciphertext.
- All X network operations sit behind the replaceable `XOAuthProvider` and are mocked in CI. Do not enable OAuth or use real X credentials until COD-344 verifies account-specific configuration, numeric user ID, permissions and applicable rights. The code implements the contract; it does not establish those external gates.

## Creator-supplied archive threat model and rights gate (planned, COD-369/370)

The original X API-first authentication model is **not** authorization to accept arbitrary ZIP uploads. A secure private BipMe app session must identify and authorize the creator for archive-only use without forcing X OAuth. Until this is implemented, production routes remain fail-closed; no unauthenticated fallback, header-based creator ID or publicly accessible archive upload may be introduced.

- **Pre-ingestion go/no-go:** Validate X export format and actual post-history fields using a voluntarily supplied recent sample; determine applicable terms for local parsing, derived profiles, local pretrained embedding inference, storage, permitted reuse and deletion. Archive possession or user consent alone does not override platform rules. If rights remain unclear, use synthetic fixtures only.
- **Upload isolation:** Accept only explicitly selected, allowlisted post-history files; validate extension and actual content, bound archive bytes/decompressed bytes/entry count/nesting/time, reject traversal/absolute paths/symlinks, executable code and HTML entry points. `data/tweets.js` and assignment wrappers such as `window.YTD.tweets.part0 = ...` are candidate layouts mentioned in prior research, **not verified against a current creator export**; X's public archive help does not publish a versioned filename/schema contract. Verify against a voluntary owner sample before enabling the mapping. If accepted, parse only recognized contained JSON **as inert data, never evaluate or execute JavaScript**. Disable untrusted extraction paths and fail safely on malformed/duplicate entries.
- **Data minimization:** Never ingest direct messages, contacts, authentication credentials or unrelated account metadata. Avoid persistent raw ZIP storage; use private isolated temporary processing, bounded retention, cleanup on success/failure and deletion of derived content/embeddings when required. Do not log raw archives or creator post text.
- **Ownership/provenance:** Enforce verified creator ownership and cross-account boundaries, source-specific consent provenance, idempotent canonical import, original publication and actual observed timestamps, exact metric identities and explicit missingness. Snapshot engagement counters are not early attention trajectories or impression-denominator estimates.
- **Cross-creator comparison:** No scraping, shared niche corpus, republishing or inference on third-party X posts until permissions and applicable rights are verified. Separate personal and permissioned niche pools, restrict disclosure of other contributors' raw content, provide withdrawal/deletion and avoid irreversible training on data that must be removed.
- **Monitoring:** Optional official API polling must enforce explicit consent, immutable account authorization, actual observation timestamps, per-operation quotas and total hard spend ceiling; archive import must not silently trigger paid refresh.

**COD-369 research checkpoint (9 Nov 2026):** X documents owner-downloadable HTML/JSON ZIP snapshots but does not specify post entry names, fields, metric snapshots or an export schema. No real sample was inspected. Archive-first import is **Conditional Go for synthetic-tested parser work only**; real post-text analysis, embedding inference, external model transfer, retention and deletion rules remain unresolved. See [X archive feasibility](research/X_ARCHIVE_FEASIBILITY.md). Creator archive possession/consent alone is not an established X processing license.

## X API budget safeguards (COD-347 implementation)

- `APIUsageLedger` is the shared durable ledger for OAuth identity reads and timeline reads. Reservations lock the creator row, check existing reservations and all applicable ceilings, and commit before any provider request. PostgreSQL `FOR UPDATE` serializes concurrent operations across X integrations; duplicate idempotency keys do not authorize a second request.
- The read adapter accepts explicit total, UTC-daily, per-operation and per-import USD ceilings plus an operator-supplied request/result price with source and validity timestamps. Missing, malformed or stale pricing, unavailable ledger storage, invalid limits and exhausted budgets fail closed. No price is embedded as a default. The adapter reserves the full configured result cap across its maximum bounded retry count before a page request; actual usage remains separately labeled and pending until a provider/account usage report is reconciled.
- Creator-history reads use only the allowlisted `GET /2/users/{id}/tweets` path, require an active creator-owned X connection and read scopes, bound pages/results/timeouts/concurrency/retries, and return normalized fields with source and observation timestamps. Missing public metrics remain explicitly missing. A failure after valid pages returns a partial result with a safe reason; 401 clears local tokens and marks reauthorization required. Niche search has a separate unavailable boundary and cannot be enabled until COD-375/COD-344 confirm rights and account entitlement.
- Settings and pricing are explicit constructor inputs; the adapter itself defaults disabled and is not wired to a production API route. COD-344's account access, rights, and actual prices remain unverified, so this code does not establish production readiness. Do not enable OAuth, creator-history ingestion, or niche search until those external gates are verified and approved.
- Ledger metadata stores bounded endpoint/operation, page limits, opaque hashed import identity, pricing reference and reservation estimate only. Never add bearer tokens, authorization headers, raw responses, post text or arbitrary provider error bodies to logs or ledger metadata.

Do **not** hardcode old X prices or assume a discounted owned-read tier is generally available. The authenticated developer console and live official documentation are authoritative at integration time.

## Ship-first safety boundary — 8 November 2026

V1 prioritizes **working delivery**, not exhaustive benchmarks or perfect analysis. This does **not** waive authenticated private sessions, account isolation, safe archive handling, source-processing and third-party LLM transfer authorization, provenance checks, prompt-injection isolation, enforced API/LLM spend ceilings, or output-citation validation. Never turn privacy or billing controls into optional polish.

The selected V1 hosted inference is **GroqCloud serving `openai/gpt-oss-120b`** through a provider-neutral server adapter; do not call it on real X-derived post text until both X source rules and the provider's applicable retention/subprocessor terms permit the specific use. On unresolved rights, free-tier rate-limit exhaustion (HTTP 429), invalid model entitlement or provider downtime, serve deterministic evidence-linked templates and report any missing-source status honestly. Never silently enable paid Groq billing. Do not silently upgrade to a costlier model.

Do not run a prelaunch multi-model benchmark. Require only focused smoke/unit tests of auth, source entitlement, spend boundaries, output schema, supported evidence references, prompt-injection resistance, and the deterministic fallback. Decide precise retention windows and private sign-in mechanism before handling real user data.

## Generative-model data processing boundary

- Treat evidence supplied to any LLM as *untrusted* content: reject prompt injection in posts, delimit data, constrain structured outputs and validate every cited post ID and numeric claim.
- Confirm both **X-derived content inference rights** and separately **third-party transfer/subprocessor rights** before sending any real creator/niche post text to an external LLM. The synthesis interface requires separate source-processing and provider-transfer attestations and source-ID allowlists; these attestations must come from a verified authorization flow before real data is eligible. Model training policies, retention, geographic processing and provider DPA require verification; consent alone may not override platform terms.
- Prefer minimal derived, approved evidence bundles rather than raw archives, tokens or entire corpora; never put post history, credentials, PII or prompts containing private content in logs/CI fixtures.
- Define bounded token, latency and monetary budgets; redact errors, disable unsupported training/data retention where contractually possible, and fail safely with a deterministic template when access or quality is insufficient.
- Keep audit trails with evidence IDs, prompt/model/schema versions and policy decisions so explanations can be reproduced and deleted when source rights change.

The pure COD-380 synthesis service is disabled by default and is not yet connected to a report API or persistence layer. Its built-in daily cost reservation is process-local and resets when the process restarts; use a shared durable budget implementation before enabling it across production workers. Current tests use synthetic fixtures and mocked provider responses only. They do not verify real X processing rights, provider-transfer rights, Groq account access, quotas, retention terms or billing configuration.

## Data handling

- Use official X APIs only; no unsupported scraping to bypass limits.
- Normalize external payloads into minimal canonical data structures; do not retain full raw responses by default.
- Keep historical content, creator metrics and tokens separated according to their sensitivity.
- The COD-345 connection table exposes only opaque encrypted-token byte columns and a key-version marker. ORM and database checks require a `BIPME-ENC` v1 envelope marker, so ordinary plaintext values are rejected. COD-346 encrypts before persistence, keeps keys server-side, avoids token responses/logs and clears encrypted token bytes on disconnect; the marker itself remains a format guard, not encryption.
- Canonical posts do not store copied X response payloads or raw post text. Post Profiles are descriptive derived fields; embeddings are versioned derivatives and must be removed or regenerated when their source post is deleted or changed. API usage metadata must be allowlisted/sanitized and must not contain tokens, authorization headers or unnecessary content.
- Use a locally run pretrained embedding model as the initial approach; verify model license and developer data-processing rights before adding third-party inference.
- Do not train or fine-tune an ML model on X-derived data without confirming this is permitted by applicable X terms.
- Retain data only for the justified experiment; decide retention and deletion periods before storing real creator data.
- Disconnecting the account stops polling and clears tokens. Provide a clear way to delete stored data in accordance with applicable policy.

## COD-358 creator-analysis API boundary

- The baseline, draft-assessment and assessment-read routes use a `creator/me` boundary and accept no creator ID from the client. Every persistence query scopes by the server-verified creator UUID, including assessment lookup and historical post/outcome retrieval.
- COD-346's session dependency accepts only a live, unexpired, unrevoked server-side session for the configured creator; it does not accept a client-supplied creator ID or an environment-selected identity as an authorization shortcut. Missing production configuration returns `503 authentication_not_configured`. OAuth remains optional for private archive-only sessions.
- Analysis persists a versioned response snapshot and fingerprint but not the draft's raw text. The fingerprint is deterministic and binds canonicalized text plus descriptive/metric-selection inputs. The optional accepted hypothesis is creator-supplied at assessment creation; the database enforces snapshot immutability.
- Embedding or database failures map to safe structured errors. Request bodies, stored content, access tokens and internal exception text are not returned in errors. Metric outcomes are read only after retrieval and never influence candidate selection/ranking.

## COD-344 — X access and feasibility gate (research checked 7 Nov 2026)

**Status: Official endpoint documentation reviewed; owner-provided console screenshots confirm OAuth Web App settings and a USD 5 billing-cycle cap, but actual API entitlements, numeric user ID, approved data-processing use cases, and live response fields remain unverified. No live X API calls were made.** Do not consider COD-344 passed or start real ingestion based on this section alone.

### Official API capabilities, subject to developer-app access

| Capability | Documented endpoint / field | Remaining verification |
| --- | --- | --- |
| Creator identity | OAuth 2.0 PKCE plus user read permission; verify account ID server-side | Confirm OAuth 2.0 enabled, `Web App` confidential client selected, registered redirect URI and allowed user ID |
| Historical posts | `GET /2/users/{id}/tweets`; latest 3,200 post ceiling, filtering/pagination | Confirm this app can invoke the endpoint; bound page size and actual returned record count |
| Historical public outcomes | `public_metrics`: impressions, likes, replies, reposts, quotes, bookmarks | Verify each field in the response from the approved account; missing/unavailable fields stay unknown |
| Creator-only outcomes | `non_public_metrics` for clicks and other private fields using user-context auth | Available only for posts less than 30 days old; confirm actual entitlements before relying on fields |
| Refresh tokens | OAuth scope `offline.access` | Request only when needed for monitored post snapshots; confirm X app scopes and session lifecycle |

Sources: [X timeline reference](https://docs.x.com/x-api/posts/timelines/introduction), [X metric definitions](https://docs.x.com/x-api/fundamentals/metrics), [OAuth PKCE documentation](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code). API documentation is not proof of account-specific permissions or real responses.

### Pricing assumptions and proposed hard limits — not enabled yet

- Public [X pay-per-use pricing](https://docs.x.com/x-api/getting-started/pricing) rechecked 9 Nov 2026: standard Post reads **$0.005 per returned Post**, user reads **$0.010 per returned User**, and eligible **owned-account reads $0.001 per returned resource** when the requested user ID matches the authenticated user *and that user owns the developer app*. Confirm BipMe's eligibility and active rates in the console, never assume it because the creator is authorized. The published pay-per-use plan lists a 3-million Post-read monthly cap; prices/credits can change. Search count endpoints have separate per-request prices; see COD-375 research before adding them.
- **Proposed initial spending configuration (awaiting user approval and implementation):** app-level total experiment allowance **USD 5**, single import allowance **USD 1**, initial import **up to 25 posts**. These are conservative *engineering defaults to discuss*, not a guarantee of billing protection, an actual console spending limit or approval to purchase credits.
- Before any billable request, confirm the console's **billing-cycle spending cap** is explicitly configured and **auto-recharge is OFF**; use the console's actual rates to configure a numeric per-operation maximum. Console spending limit and internal application limits are complementary; neither is currently verified.
- The OAuth `/2/users/me` identity check is also treated as a billable X request. It is disabled unless an operator configures a verified per-request estimate and UTC daily ceiling. BipMe reserves that estimate in `api_usage_ledger` before the network call; exhausted or unavailable accounting fails closed. The record remains pending until reconciled with the account usage report.
- Future X adapter (`COD-347`) must reserve budget *before* issuing calls, count **worst-case billed resources** including other requested user objects, and reconcile actual usage with X's console/usage endpoint. Unknown costs, exhausted balance or uncertain deduplication → fail closed. Persist operation, endpoint, requested cap, returned resource count, billable estimate, observed timestamp and reconciliation status.
- X documents same-day UTC resource deduplication as a **soft guarantee**. Do not rely on deduplication to prevent costs. Per-post monitoring must also obey limits and store actual observation times.
- Estimate-only examples, **not charges incurred**: 25 post reads at standard price ≈ **$0.125**, or **$0.025** if the owned-read rate truly applies, excluding other resources and API requests. No resource was fetched to establish the exact cost for this account.

### Data rights, display and AI gates

- Follow the [X Developer Agreement](https://docs.x.com/developer-terms/agreement) and [X Developer Policy](https://docs.x.com/developer-terms/policy), not only the summarized guidelines. The agreement forbids using X data to **train or fine-tune foundation/frontier models**; the guidelines likewise forbid unauthorized ML training. **Inference with a pretrained embedding encoder over X post text remains unconfirmed** under the applicable agreement: obtain an authoritative determination before feeding any real X text into E5 or another model. Synthetic/offline testing of the model is allowed as a separate engineering activity, not evidence of authorization to process X content.
- Keep the core one-account experiment authorized and read-focused. No scraping, automated posting, follower harvesting, cross-account redistribution, third-party inference, or external advertising targeting with X content.
- If storing X Content, honor later deletions, edits, protected status and removal notices; the policy calls for updates as soon as reasonably possible, and within **24 hours of a removal/change request** from X or the owner, subject to the terms. Derived content/embeddings require a deletion/update strategy as well; this must be handled during the persistence/ingestion design.
- Follow X's content display requirements (freshness and attribution); show the connected X identity as required by the policy. Provide a privacy notice, consent and account disconnect/data-deletion workflow before offering real service access.
- **Creator-baseline analysis is also a data-use gate**: before running aggregation, creator-profile analytics, or any local embedding inference on real X posts, confirm the actual approved app use case and applicable X terms allow that specific processing. Authentication and possession of an account archive alone do not establish these rights. If approval is required, seek it before processing.
- **Retention period is not finalized**. Decide the minimum justified duration and deletion cadence, subject to X policy, before storing real creator data. Avoid treating an arbitrary number of days as an approved rule.

### COD-375 third-party niche search feasibility — verified 9 Nov 2026

The official [Search Posts documentation](https://docs.x.com/x-api/posts/search/introduction) currently describes `GET /2/tweets/search/recent` as available to all developers for the previous seven days and `GET /2/tweets/search/all` as full archive back to 2006 for pay-per-use or Enterprise customers. This is a **published capability statement**, not confirmation that BipMe's developer app is approved, enabled, funded, or entitled to either endpoint. The Developer Agreement grants use of X Content for analysis only when the use is explicitly approved by X; therefore niche collection, creator comparisons, local embeddings, and report synthesis remain disabled until the declared BipMe use case is confirmed as approved. Public visibility, account authentication, and a successful endpoint response would not independently grant processing rights.

| Use | Current classification | Gate before real niche content |
| --- | --- | --- |
| Fetch public third-party posts through official search | Technically documented; account entitlement unresolved | Confirm the approved app, intended niche-research use case, endpoint access, current limits, and price in the developer console. No scraping. |
| Analyze/aggregate posts into a creator's private report | Unresolved; Agreement says analysis must be explicitly approved; do not generalize global X-performance statistics | Obtain authoritative confirmation that this private, per-creator comparative use is within the app's approved purpose. Keep cross-creator cohorts and shared aggregates disabled. |
| Persist or display post text and profile data | Conditional, not blanket permission | Minimize and time-limit storage; display only per X display requirements with source attribution and current content. Remove/update content as soon as reasonably possible and within 24 hours of a removal/change request. Verify whether the proposed report display is permitted. |
| Local pretrained E5 embedding inference | Unresolved | X expressly prohibits training/fine-tuning foundation or frontier models; it does not expressly settle ordinary pretrained inference. Since inference is content analysis/derivation, obtain X approval before processing real X text. Synthetic fixtures only meanwhile. |
| GroqCloud report synthesis over X-derived content | Unresolved; separate provider disclosure/processing gate | Obtain X authorization for this transfer and complete privacy/processor review. Groq's current data guide says inference inputs/outputs are not retained by default, but reliability/abuse logs may be retained for up to 30 days unless Zero Data Retention is enabled; verify the BipMe organization setting and applicable terms. A provider retention control does not create X rights. |
| Reuse raw posts, embeddings, or derived niche findings across creators | Disabled; no cross-creator reuse | X restricts redistribution of X Content and defines derivatives within X Content. Keep per-creator evidence isolated. Do not create a shared training, embedding, or comparative-performance corpus without explicit written permission and a separate privacy review. |

Search docs list OAuth 2.0 Bearer authorization; X describes app-only bearer auth as typically read-only public access and app-rate-limited. The BipMe app is active and linked to an active Pay Per Use project, as observed in the authenticated console on 9 Nov 2026. That plan is consistent with the public full-archive access description, but no search request was made, so endpoint-level access and actual returned fields remain unverified. The inspected console pages did not expose per-endpoint rates; public rates and the current project-specific rate schedule must not be conflated. No live or billable X calls were made for COD-375.

For bounded example budgets and source-field details see [COD-375 research findings](research/X_DISCOVERY_DISTRIBUTION_MVP.md). The examples are estimates at the published rates, assume no daily deduplication discount, and are not charges or an approval to buy credits. The live console review on 9 Nov 2026 confirmed the displayed USD 5 cycle cap, USD 0 balance/free credits/current spend, and auto-recharge unavailable because no payment method is configured. Do not make requests while the balance is zero; do not buy credits or alter billing as part of this research.

### COD-378 report processing boundary

- The report API requires an authenticated private creator session and CSRF validation for mutations. Creator identity is derived only from that session; profile, permission, report, evidence and deletion queries are scoped to that ID.
- A signed-in creator can grant or revoke local deterministic processing of their personal history. Consent alone does not satisfy platform rights: X-history processing also requires the server-only `BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED=true` gate and a valid `BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT` timestamp, both blocked by default until COD-344 confirms the specific use. The report route reads only canonical, owner-scoped X records already stored; it does not call X, perform scraping or invoke a model.
- Niche discovery is always reported unavailable on this route until COD-375/COD-376 establishes and implements its separate rights, fields and budget boundary. Optional synthesis remains disabled; no X-derived content is transferred to GroqCloud.
- Reports persist a minimized evidence/provenance snapshot rather than raw post text. Revoking local history-processing consent deletes derived report snapshots immediately. `DELETE /reports` and `DELETE /profile` erase report-owned data; canonical post/archive deletion remains the responsibility of the COD-370/COD-348 ingestion owner and must be coordinated with that path before production data use.

### Current console observations (authenticated read-only review, 9 Nov 2026)

- The authenticated console identifies the **BipME by CodedDevs** app as active and linked to **Default Project (Pay Per Use)**. This is a current plan observation, not proof of a particular endpoint's access or an approved use case.
- The Credits page displays **USD 0.00 remaining balance**, **USD 0.00 free credits**, **USD 5.00 billing-cycle cap**, **USD 0.00 current spend**, and auto-recharge unavailable because a payment method is not configured. The displayed cycle is **6 Nov–6 Dec 2026**. No billing settings were changed.
- The Usage analytics page shows **0 billable events** and **USD 0.00 total cost** for 10 Oct–9 Nov 2026, with no request rows. This is the console's displayed history, not evidence of search endpoint access.
- The console Notifications page contains an X notice dated **26 Oct 2026** stating that, starting **22 Nov 2026**, objects returned through expansions (Posts, Users, media, polls and places) will be billed at the standard Pay Per Use rate for each resource. The example expanded-result budgets therefore use a conservative post-22-Nov rate assumption; the effective rate for a future request must be rechecked in the console.
- The app's authentication settings form currently displays OAuth 1.0a **Read** permission, email request off, **Web App / confidential client**, callback `http://127.0.0.1:8000/api/auth/x/callback`, and the BipMe GitHub website URL. The inspection made no edits; because the form did not show a saved-state confirmation, persistence is not independently proven. OAuth 2.0 requested scopes and a successful OAuth handshake remain unverified.
- No X API request was made. The account's returned fields, recent/full-search endpoint-level entitlement, account-specific endpoint pricing, immutable numeric X user ID, and written X approval for this niche-analysis use case remain unverified. Zero credits do not authorize a call. The public pay-per-use schedule is documented separately from account-specific console rates.
- Earlier owner-provided 7 Nov screenshots recorded the same USD 5 cap, USD 0 balance/spend and auto-recharge unavailable; they also showed these auth values, but did not establish their saved state. The 9 Nov review supersedes them for what the console displayed during this inspection.
- COD-347's budget-guarded read adapter and usage ledger are implemented on `main` through [PR #33](https://github.com/onerandomd3v/BipMe/pull/33) (merged 9 Nov 2026). Code availability does not verify this app's endpoint entitlement, current billing controls, or processing rights; live reads remain disabled until COD-344 gates pass.
- The owner requested developer-credit support through X's community; no grant or credits have been verified. Do not infer special privileges or discounts.

### Console-only checks needed from the developer-app owner

1. Verified 9 Nov: the app is active on a Pay Per Use project; balance/free credits and current spend are USD 0, billing-cycle cap USD 5, and auto-recharge is unavailable. A console notice says expansion resources begin billing on 22 Nov 2026. Still confirm recent/full-search endpoint-level access and the effective endpoint/expansion rates before any future request; do not paste tokens, client secrets or payment details into issue comments.
2. The current auth form displays Read-only OAuth 1.0a permission, email request off, Web App/confidential client, and callback `http://127.0.0.1:8000/api/auth/x/callback`; saved-state confirmation and OAuth 2.0 console settings remain unverified. Separately, the current BipMe OAuth callback implementation requires exactly `tweet.read`, `users.read`, and `offline.access`, and rejects authorization without all three scopes and a refresh token. Although X documents `offline.access` as the scope for receiving a refresh token, optional refresh behavior is only a future proposal; it is not the current callback behavior. This implementation requirement does not verify that the console is configured with these scopes or that a successful OAuth handshake has occurred.
3. Configure allowlist for the **immutable X numeric user ID**, resolved securely after OAuth; don't rely on handle strings. Store the real ID and OAuth secrets outside the repository.
4. Record a yes/no decision from X or applicable contractual guidance for **both creator-baseline/aggregate content analysis and local pretrained-embedding inference**; until resolved, use synthetic data only.
5. Hand off the first **single bounded owner-authorized read** to COD-349 **after** COD-346/COD-347 safeguards have passed. COD-344 itself must not make a live read or wait for COD-349 to finish; that would create a circular dependency. COD-349 records the observed endpoint, fields, cost and timestamp without committing private raw payloads.

### Exit criteria

COD-344 may be marked **Done** after the owner has confirmed the relevant developer-console access and OAuth *configuration* (not implemented OAuth code), the real numeric X ID and registered redirect, approved numeric billing-cycle and proposed app-level budget settings, and an authoritative determination of whether the intended creator-baseline analysis **and** X-text embedding inference are allowed. The subsequent implementation and first billable read are owned by COD-346/347/349; they are **not** prerequisites to completing this upstream issue. If legal/API restrictions prevent the proposed approach, record the restriction and revise scope before proceeding; do **not** bypass policy with scraping or unapproved processing.

## Verification gates

- **Before OAuth:** state/PKCE tests; allowlist enforcement; session cookies and CSRF coverage; token encryption and log-redaction tests.
- **Before history import:** API price/permissions review, budget limits, safe pagination and failed/retry behavior tests.
- **Before monitoring:** idempotent jobs, missing-window handling, no fabricated observation timestamps, explicit cost model.
- **Before any external deployment:** HTTPS, secure secret management, least privilege, access control, and relevant X requirements.

## References

- [Architecture](architecture.md), [Product](product.md), [Development](development.md)
- [Official X OAuth documentation](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)
- [Official X API pricing](https://docs.x.com/x-api/getting-started/pricing)
- [Official X developer guidelines](https://docs.x.com/developer-guidelines)
