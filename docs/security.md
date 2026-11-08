# BipMe — Security, privacy and API cost controls

**Current state:** This is a **requirements and implementation checklist**, not a claim of completed OAuth security controls. Real X connection and cost-management logic have not been implemented.

## Threats worth handling immediately

- Unauthorized access to the one-account private experiment.
- OAuth code interception, CSRF, lost state/PKCE verifier, stale refresh tokens and token disclosure.
- Unexpected X API charges from pagination, retries, repeated sync or accidental unbounded jobs.
- X data being retained or sent to AI providers beyond allowed processing purposes.
- Logs, fixtures, screenshots or CI artifacts exposing tokens or creator-private metrics.

## Account and session design (planned)

- Official X OAuth **Authorization Code Flow with PKCE**, using a random one-time verifier and state, validated server-side.
- Request least-privilege scopes: `tweet.read`, `users.read`, and `offline.access` only when needed to refresh. Do not request write/DM scopes for this initial phase.
- Resolve the authenticated X account ID server-side and compare with the explicitly configured allowlist. Reject any other identity even if OAuth succeeded.
- Maintain an application session **server side** and send an HttpOnly, Secure (HTTPS), appropriately SameSite-scoped session cookie. Protect mutating routes against CSRF.
- Encrypt X access and refresh tokens at rest, avoid printing tokens in logs/traces, rotate keys where feasible and handle revocation/disconnect.
- Store all secrets outside Git; `.env.example` contains placeholders or local-only database examples. Never check in a real `.env`.

## Creator-supplied archive threat model and rights gate (planned, COD-369/370)

The original X API-first authentication model is **not** authorization to accept arbitrary ZIP uploads. A secure private BipMe app session must identify and authorize the creator for archive-only use without forcing X OAuth. Until this is implemented, production routes remain fail-closed; no unauthenticated fallback, header-based creator ID or publicly accessible archive upload may be introduced.

- **Pre-ingestion go/no-go:** Validate X export format and actual post-history fields using a voluntarily supplied recent sample; determine applicable terms for local parsing, derived profiles, local pretrained embedding inference, storage, permitted reuse and deletion. Archive possession or user consent alone does not override platform rules. If rights remain unclear, use synthetic fixtures only.
- **Upload isolation:** Accept only explicitly selected, allowlisted post-history files; validate extension and actual content, bound archive bytes/decompressed bytes/entry count/nesting/time, reject traversal/absolute paths/symlinks, deny executable/HTML/script ingestion, disable untrusted extraction paths and fail safely on malformed/duplicate entries.
- **Data minimization:** Never ingest direct messages, contacts, authentication credentials or unrelated account metadata. Avoid persistent raw ZIP storage; use private isolated temporary processing, bounded retention, cleanup on success/failure and deletion of derived content/embeddings when required. Do not log raw archives or creator post text.
- **Ownership/provenance:** Enforce verified creator ownership and cross-account boundaries, source-specific consent provenance, idempotent canonical import, original publication and actual observed timestamps, exact metric identities and explicit missingness. Snapshot engagement counters are not early attention trajectories or impression-denominator estimates.
- **Cross-creator comparison:** No scraping, shared niche corpus, republishing or inference on third-party X posts until permissions and applicable rights are verified. Separate personal and permissioned niche pools, restrict disclosure of other contributors' raw content, provide withdrawal/deletion and avoid irreversible training on data that must be removed.
- **Monitoring:** Optional official API polling must enforce explicit consent, immutable account authorization, actual observation timestamps, per-operation quotas and total hard spend ceiling; archive import must not silently trigger paid refresh.

## X API budget safeguards (planned)

Implement and test safeguards **before** a live import:

1. Explicit total spend ceiling and per-import cap, controlled by configuration.
2. A small initial history page/sample; progressive import only with observed benefit.
3. Endpoint/operation-level counters, response counts, estimated cost, reset/period and creator ID.
4. Rate-limit handling with bounded retries and backoff; prevent duplicate scheduled work.
5. A fail-closed rule when cost cannot be estimated confidently or budget is depleted.
6. No broad follower graph crawling, unnecessary recent searches or repeated high-cost requests.
7. Clear distinction between public and creator-authorized private metrics, including temporal availability.

Do **not** hardcode old X prices or assume a discounted owned-read tier is generally available. The authenticated developer console and live official documentation are authoritative at integration time.

## Data handling

- Use official X APIs only; no unsupported scraping to bypass limits.
- Normalize external payloads into minimal canonical data structures; do not retain full raw responses by default.
- Keep historical content, creator metrics and tokens separated according to their sensitivity.
- The COD-345 connection table exposes only opaque encrypted-token byte columns and a key-version marker. ORM and database checks require a `BIPME-ENC` v1 envelope marker, so ordinary plaintext values are rejected; OAuth/integration code must still encrypt tokens before persistence, never log them, and clear encrypted token bytes on revocation. The marker is a format guard, not encryption. Encryption, key management and OAuth are not implemented by the schema migration itself.
- Canonical posts do not store copied X response payloads or raw post text. Post Profiles are descriptive derived fields; embeddings are versioned derivatives and must be removed or regenerated when their source post is deleted or changed. API usage metadata must be allowlisted/sanitized and must not contain tokens, authorization headers or unnecessary content.
- Use a locally run pretrained embedding model as the initial approach; verify model license and developer data-processing rights before adding third-party inference.
- Do not train or fine-tune an ML model on X-derived data without confirming this is permitted by applicable X terms.
- Retain data only for the justified experiment; decide retention and deletion periods before storing real creator data.
- Disconnecting the account stops polling and clears tokens. Provide a clear way to delete stored data in accordance with applicable policy.

## COD-358 creator-analysis API boundary

- The baseline, draft-assessment and assessment-read routes use a `creator/me` boundary and accept no creator ID from the client. Every persistence query scopes by the server-verified creator UUID, including assessment lookup and historical post/outcome retrieval.
- COD-346's OAuth/session dependency is not yet implemented. Until it supplies a verified, active creator identity, the production dependency returns `503 authentication_not_configured`; it does not accept a cookie, header, query parameter or environment-selected creator as a temporary bypass. API tests inject synthetic identities through FastAPI dependency overrides only.
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

- Public [X pay-per-use pricing](https://docs.x.com/x-api/getting-started/pricing) reviewed 7 Nov 2026: standard Post reads **$0.005 per returned Post**, user reads **$0.010 per user**, and eligible **owned-account timeline reads $0.001 per returned resource** when the requested user ID matches the authenticated user *and that user owns the developer app*. Confirm BipMe's eligibility in the console, never assume it because the creator is authorized. Costs/credits can change.
- **Proposed initial spending configuration (awaiting user approval and implementation):** app-level total experiment allowance **USD 5**, single import allowance **USD 1**, initial import **up to 25 posts**. These are conservative *engineering defaults to discuss*, not a guarantee of billing protection, an actual console spending limit or approval to purchase credits.
- Before any billable request, confirm the console's **billing-cycle spending cap** is explicitly configured and **auto-recharge is OFF**; use the console's actual rates to configure a numeric per-operation maximum. Console spending limit and internal application limits are complementary; neither is currently verified.
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

### Confirmed console configuration (owner-provided evidence, 7 Nov 2026)

- X developer app: BipME by CodedDevs; connected test-account **handle** `@onerandomd3v` (the immutable numeric X user ID is still unverified).
- The owner reported saving OAuth 2.0 **Web App, Automated App or Bot**, read permissions, email request off, and local callback `http://127.0.0.1:8000/api/auth/x/callback`. These are console configuration observations, **not** a successful OAuth handshake or API authorization proof.
- Console screenshot confirmed **USD 5.00 billing-cycle cap** and **USD 0.00 available credits/spend**; auto-recharge unavailable without a payment method. Application-level spending limits and ledger remain unimplemented under COD-347, so no billable reads are approved.
- The owner requested developer-credit support through X's community; no grant or credits have been verified. Do not infer special privileges or discounts.

### Console-only checks needed from the developer-app owner

1. Confirm the BipMe application and project status, current pay-per-use credit balance, billing-cycle cap, auto-recharge state, and current price of its intended endpoints; do not paste tokens, client secrets or payment details into issue comments.
2. Confirm OAuth 2.0 app type, read-only permissions and exact registered callback `http://127.0.0.1:8000/api/auth/x/callback` **if the console accepts that exact development callback**; this is a planned route, not yet implemented. Request `tweet.read`, `users.read`, and `offline.access` only when token renewal is required.
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
