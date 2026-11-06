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
- Use a locally run pretrained embedding model as the initial approach; verify model license and developer data-processing rights before adding third-party inference.
- Do not train or fine-tune an ML model on X-derived data without confirming this is permitted by applicable X terms.
- Retain data only for the justified experiment; decide retention and deletion periods before storing real creator data.
- Disconnecting the account stops polling and clears tokens. Provide a clear way to delete stored data in accordance with applicable policy.

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
