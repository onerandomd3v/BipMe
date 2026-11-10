# BipMe — Development guide

**Status:** Deterministic intelligence, canonical persistence, COD-358 analysis routes, COD-346 private session/auth contracts, and COD-362 PostgreSQL worker infrastructure are implemented. Private sessions and the current creator endpoints remain fail-closed until the configured creator, database and private login secret are provisioned. X OAuth is opt-in and remains disabled until COD-344's account-specific access and rights gates are verified.

## Prerequisites

- Python **3.13**, with [uv](https://docs.astral.sh/uv/)
- Node.js **24** and **pnpm 10**
- Docker with Compose
- Git and a GitHub account with repo access

From the repository root, `apps/api` and `apps/web` are independent dependency roots, even though the code lives in one monorepo. Commit both `uv.lock` and `pnpm-lock.yaml` on dependency changes.

## Minimum Environment Configuration

The API process can start without environment variables and serve `GET /api/health`; that endpoint is liveness only. `BIPME_DATABASE_URL` is the only environment setting required for migrations or the baseline worker, and is needed by database-backed API routes. Authentication routes can also require the creator/session settings below. The template at `apps/api/.env.example` documents optional settings too; Python does not automatically load `.env.example` or `.env`.

From the repository root, start local PostgreSQL, set the one required database value, then migrate and start FastAPI:

```bash
docker compose up -d --wait db
cd apps/api
uv sync --locked --group dev
export BIPME_DATABASE_URL='postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
uv run alembic upgrade head
uv run uvicorn bipme.api.app:app --reload
```

Run the worker in a separate terminal with the same database value:

```bash
cd apps/api
export BIPME_DATABASE_URL='postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
uv run python -m bipme.jobs
```

Windows PowerShell uses the same process environment contract:

```powershell
docker compose up -d --wait db
Set-Location apps/api
$env:BIPME_DATABASE_URL = 'postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
uv sync --locked --group dev
uv run alembic upgrade head
uv run uvicorn bipme.api.app:app --reload
```

For private creator sign-in, also set `BIPME_CREATOR_ID` to an existing creator row and `BIPME_PRIVATE_LOGIN_SECRET` to a server-side secret of at least 32 bytes. No X OAuth settings are needed. In local development, the session lifetime defaults to 12 hours and insecure cookies are allowed only for loopback HTTP; production requires secure cookies over HTTPS. Never put this secret in a Vite variable or browser bundle.

For example, in the API process environment (replace both placeholders; the secret must be unpredictable and at least 32 bytes):

```bash
export BIPME_CREATOR_ID='existing-creator-uuid'
export BIPME_PRIVATE_LOGIN_SECRET='replace-with-a-generated-secret-of-at-least-32-bytes'
```

The API and worker share `apps/api/src/bipme` and the same environment-variable definitions, but run as separate processes. The baseline worker needs only `BIPME_DATABASE_URL`; no `apps/worker` package or duplicate worker example is needed. If scheduled X metric snapshots are enabled, give the worker only the additional encryption-key and snapshot settings it needs. X OAuth client secrets and unrelated API-only settings should not be copied into the worker environment.

The service examples remain optional templates. To load one explicitly, copy `apps/api/.env.example` to `apps/api/.env`, then source it with `set -a; . ./apps/api/.env; set +a` in Bash. In PowerShell, import its simple `KEY=value` lines into the current process:

```powershell
Copy-Item apps/api/.env.example apps/api/.env
Get-Content apps/api/.env | ForEach-Object {
  if ($_ -match '^\s*([^#=][^=]*)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2], 'Process')
  }
}
```

Do not fill every value: blank values and disabled flags intentionally leave optional features unavailable. In production, inject only each process's required values through its secret manager or deployment environment. The root Compose file has fixed local-only PostgreSQL credentials and does not load the API `.env`; Brev Compose interpolation is separate and uses `infra/brev-embedding/.env.example`.

The web app currently consumes no custom environment variables and has no web `.env.example`. Any future `VITE_` value is public browser configuration; never place database credentials, session secrets, X credentials, Brev tokens, or Groq keys in it.

### Optional integrations

- **Remote embeddings:** API only. Set `BIPME_EMBEDDING_PROVIDER=remote`, `BIPME_EMBEDDING_REMOTE_URL` to the private Brev HTTPS endpoint, `BIPME_EMBEDDING_REMOTE_TOKEN` to the server-side bearer token, and optionally `BIPME_EMBEDDING_TIMEOUT_SECONDS` (default 10, valid above 0 through 60). The Brev side uses `BIPME_EMBEDDING_TOKEN`; provision the matching token separately in both hosts. Keep the pinned E5 model/revision unchanged. Remote failure does not fall back to local inference, and a process restart is required after changing API settings. See [COD-421 setup](#cod-421-private-brev-embeddings).
- **GroqCloud synthesis:** GroqCloud is the selected V1 generative AI provider. The backend can start without a Groq key while synthesis remains disabled. When synthesis is enabled, `GROQ_API_KEY` is required, along with `BIPME_REPORT_SYNTHESIS_ENABLED=true` and `BIPME_REPORT_MODEL=openai/gpt-oss-120b` (the selected default). Set `BIPME_REPORT_MAX_REQUEST_COST_USD` and `BIPME_REPORT_MAX_DAILY_COST_USD` from verified current pricing before enabling; the daily budget is in-memory per process, not a deployment-wide ceiling. Verify Groq account/model access and source-processing plus provider-transfer rights. These settings do not currently connect synthesis to the report API or persistence layer, and they do not grant permission to send real X content.
- **X OAuth:** the API requires `BIPME_X_OAUTH_ENABLED=true`, an existing `BIPME_CREATOR_ID`, `BIPME_X_CLIENT_ID`, sensitive `BIPME_X_CLIENT_SECRET`, numeric `BIPME_X_ALLOWED_USER_ID`, exact `BIPME_X_REDIRECT_URI`, `BIPME_APP_ORIGIN`, `BIPME_TOKEN_ENCRYPTION_KEYS` plus `BIPME_ACTIVE_TOKEN_KEY_VERSION`, and verified positive `BIPME_X_IDENTITY_READ_ESTIMATED_COST_USD` and `BIPME_X_DAILY_COST_LIMIT_USD`. Production also requires `BIPME_ENVIRONMENT=production` and `BIPME_AUTH_COOKIE_SECURE=true`. Verify account entitlement, requested scopes, current pricing, processing rights, and enforceable caps before turning it on; see [Security](security.md#cod-344--x-access-and-feasibility-gate-research-checked-7-nov-2026).
- **X history import:** in addition to OAuth identity/key readiness, it requires `BIPME_X_HISTORY_IMPORT_ENABLED=true`, `BIPME_X_ACCOUNT_ENTITLEMENT_VERIFIED=true`, `BIPME_X_HISTORY_DATA_RIGHTS_VERIFIED=true`, `BIPME_X_HISTORY_REQUEST_COST_USD`, `BIPME_X_HISTORY_RESULT_COST_USD`, `BIPME_X_HISTORY_PRICING_OBSERVED_AT`, `BIPME_X_HISTORY_PRICING_EXPIRES_AT`, `BIPME_X_HISTORY_PRICING_SOURCE`, `BIPME_X_DAILY_COST_LIMIT_USD`, and positive `BIPME_X_HISTORY_OPERATION_LIMIT_USD` and `BIPME_X_HISTORY_IMPORT_LIMIT_USD`. `BIPME_X_HISTORY_TOTAL_LIMIT_USD` is optional in the current code but should be configured as an additional hard cap. Keep disabled until entitlement, rights, prices, and limits are verified.
- **X metric snapshots:** requires `BIPME_X_METRIC_SNAPSHOT_ENABLED=true`, `BIPME_X_ACCOUNT_ENTITLEMENT_VERIFIED=true`, either `BIPME_X_METRIC_SNAPSHOT_DATA_RIGHTS_VERIFIED=true` or the supported `BIPME_X_HISTORY_DATA_RIGHTS_VERIFIED=true`, `BIPME_X_ALLOWED_USER_ID`, `BIPME_X_METRIC_SNAPSHOT_REQUEST_COST_USD`, `BIPME_X_METRIC_SNAPSHOT_PER_POST_LIMIT_USD`, current `BIPME_X_METRIC_SNAPSHOT_PRICING_OBSERVED_AT`, `BIPME_X_METRIC_SNAPSHOT_PRICING_EXPIRES_AT`, `BIPME_X_METRIC_SNAPSHOT_PRICING_SOURCE`, and a positive `BIPME_X_DAILY_COST_LIMIT_USD` (the code also accepts `BIPME_X_PUBLICATION_DAILY_COST_LIMIT_USD` as a fallback). `BIPME_X_METRIC_SNAPSHOT_TOTAL_LIMIT_USD` and `BIPME_X_METRIC_SNAPSHOT_OPERATION_LIMIT_USD` are optional in the current validator; configure them for defense in depth. The API scheduler and worker are separate processes: the worker also needs `BIPME_DATABASE_URL`, `BIPME_TOKEN_ENCRYPTION_KEYS`, and `BIPME_ACTIVE_TOKEN_KEY_VERSION` to decrypt the connection and execute a scheduled read.
- **Published-post verification:** requires `BIPME_X_PUBLICATION_LINK_ENABLED=true`, verified `BIPME_X_PUBLICATION_ACCOUNT_ENTITLEMENT_VERIFIED` and `BIPME_X_PUBLICATION_DATA_RIGHTS_VERIFIED`, `BIPME_X_ALLOWED_USER_ID`, `BIPME_X_PUBLICATION_READ_ESTIMATED_COST_USD`, `BIPME_X_PUBLICATION_PRICING_OBSERVED_AT`, `BIPME_X_PUBLICATION_PRICING_EXPIRES_AT`, `BIPME_X_PUBLICATION_PRICING_SOURCE`, and positive `BIPME_X_PUBLICATION_DAILY_COST_LIMIT_USD`. Total, operation, and import caps are optional in the current validator; configure them where supported. This route uses the API process and connected creator-owned X account.
- **Local history report processing:** independently gated by `BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED=true` and a valid `BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT` timestamp. This is not OAuth or external synthesis; platform rights still need a separate decision.

All X feature gates and prices remain false or blank in the template. Do not infer entitlement or costs from consent, test fixtures, or previous prices; see [COD-349 verification notes](#cod-349-one-account-history-verification) before any live read.

## Local database

```bash
docker compose up -d --wait db
docker compose ps
```

The `--wait` flag waits for the configured PostgreSQL health check to pass before proceeding to migrations. If the service never becomes healthy, check `docker compose logs db` before continuing.

The local service exposes PostgreSQL on `127.0.0.1:5432` with **development-only** credentials in `compose.yaml`. Never reuse them outside local development. The volume persists between restarts.

Alembic, the API's database-backed routes, and the worker read `BIPME_DATABASE_URL` **from their process environment**. Set it in each process that needs database access; copying `.env.example` does not load it. To use a different database, override this process value. Authentication secrets and creator IDs are also process environment values; keep real values out of Git.

## Start the API

```bash
cd apps/api
uv sync --locked --group dev
uv run alembic upgrade head
uv run uvicorn bipme.api.app:app --reload
```

Run a separate durable job worker with the same database URL:

```powershell
cd apps/api
uv run python -m bipme.jobs
```

For Windows PowerShell, use a separate terminal and set the same database variable before starting the worker:

```powershell
Set-Location apps/api
$env:BIPME_DATABASE_URL = 'postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
uv run python -m bipme.jobs
```

The worker listens only to the `bipme` queue, retains runner jobs, uses a 30-second graceful timeout, and checks for stalled workers by heartbeat. Recovery is supervised alongside the worker; a recovery failure stops intake and drains the worker before returning a sanitized failure. A handler must complete within a bounded duration because Python cannot cancel its synchronous thread; shutdown waits for in-flight handler work to finish, even after Procrastinate's graceful timeout. On Windows use Ctrl+C for cooperative shutdown; Python does not install Procrastinate signal handlers there, so do not assume SIGTERM drains active work. Scheduling is currently an internal service API; no public scheduling route or COD-363 metric handler is enabled. Migration `0005_durable_jobs` installs the pinned Procrastinate schema snapshot and permanent BipMe receipts. The runner schema snapshot is fixed at Procrastinate 3.10.0 and is not dynamically upgraded by Alembic. Consent-generation invalidation is deferred to COD-363. Procrastinate startup/prune lifecycle behavior and sanitization of its own exception logs have not been verified beyond BipMe receipt/outcome logging.

The original delay/runtime test in `test_persistence_postgres.py` clears `scheduled_at` and recreates a runtime inside one process. The separate POSIX suite `tests/test_worker_process.py` closes the process-restart evidence gap: it starts real Python subprocesses against a freshly migrated disposable database per case, terminates Worker A with SIGTERM or SIGKILL before the deadline, and lets Worker B complete the job at its unchanged wall-clock deadline. It checks persisted receipt/queue state, execution PID/time, duplicate submission and actual duplicate delivery. It also verifies SIGTERM drains an active handler beyond the configured grace period, and SIGKILL after a durable mocked-provider reservation leads to `needs_reconciliation` after genuine heartbeat expiry without a second provider call. A separate exception case verifies uncertain handler outcomes remain terminal across restart. No live X transport is used. Polling, handler barriers, subprocess waits and recovery waits are bounded; the recovery case may take roughly 45 seconds. Windows skips these POSIX signal cases explicitly. CI runs this suite in a dedicated step against its disposable PostgreSQL service:

```bash
cd apps/api
uv run pytest -q tests/test_worker_process.py
```

Supply `BIPME_TEST_DATABASE_URL` pointing to a disposable database. The test database role needs CREATEDB permission (the CI service role has it). Each case creates/drops its own disposable database and force-reaps only subprocesses it started. The test-only call journal records every invocation without a uniqueness constraint so duplicate handler execution cannot be hidden by test-side deduplication.

Check `http://127.0.0.1:8000/api/health`. Migration `0001_enable_vector` creates the pgvector extension; `0002_canonical_persistence` creates canonical creator/post records; `0003_private_auth_sessions` adds revocable sessions and short-lived OAuth transactions. COD-346 provides `POST /api/auth/private/session`, `GET /api/auth/session`, `POST /api/auth/logout`, `GET /api/auth/x/authorize`, `GET /api/auth/x/callback`, and authenticated X status/refresh/disconnect routes. Protected endpoints require a configured existing `BIPME_CREATOR_ID`; private sign-in additionally requires a high-entropy `BIPME_PRIVATE_LOGIN_SECRET` (at least 32 bytes). For local OAuth callback cookies, use the same loopback host in `BIPME_APP_ORIGIN` and the registered callback URI. X OAuth stays disabled unless explicitly enabled after COD-344's access and rights checks.

X OAuth also requires operator-supplied `BIPME_X_IDENTITY_READ_ESTIMATED_COST_USD` and `BIPME_X_DAILY_COST_LIMIT_USD` values from verified current pricing. The callback reserves the configured worst-case identity lookup cost in `api_usage_ledger` before calling X and fails closed at the UTC daily ceiling. Reservations stay pending until reconciled against X account usage. Keep OAuth disabled until COD-344's account-specific access/rights gates and current pricing are confirmed.

COD-348 adds creator-owned, bounded history import at `POST /api/v1/creators/me/history/imports` with `{import_id, max_posts}` and status at `GET /api/v1/creators/me/history/imports/{import_id}`. The route remains fail-closed unless the operator explicitly supplies `BIPME_X_HISTORY_IMPORT_ENABLED`, entitlement/rights verification flags, current pricing timestamps/source, and total/daily/operation/import USD limits. Returned posts are normalized into owner-scoped canonical records with source provenance; each metric is stored as observed, missing, or invalid rather than treating unavailable data as zero. CI uses mocked providers only; no live X read is part of routine verification.

### COD-349 one-account history verification

**Mocked baseline (10 Nov 2026):** `tests/test_history_import.py` now carries two deterministic X pages through the real budgeted reader, importer and isolated persistence. It verifies pagination, duplicate suppression, creator ownership, reply topology, publication/observation timestamps, provenance, missing impressions, two usage reservations and same-import replay without another provider call. The existing history-route tests check request bounds, creator-scoped status and disabled import configuration; `test_auth.py` checks session renewal/revocation, CSRF, token-free responses and disconnect. `test_x_read.py` checks entitlement/rights/allowlist failures, budget and stale-pricing rejection before transport, 401 credential clearing, 403/429/5xx and timeout handling, bounded retries, and partial-result behavior. These are synthetic fixtures: estimated ledger reservations are **not actual X charges**. A terminal partial/unavailable import is replayed under the same import ID; a new, explicitly bounded import ID is needed for a later attempt. The importer does not resume a page cursor after process interruption. No real account, entitlement, field coverage, cost or restart recovery is established by these tests.

**Manual live checklist (blocked; do not run from CI):**

1. Obtain the account owner's separate authorization for the *specific potentially billable* small test. First document X/app approval for owner-history processing and storage, a retention/deletion route, endpoint entitlement, the immutable numeric account ID and the verified account allowlist. The USD 5 console cap alone is not authorization. Do not proceed on an unresolved item.
2. Verify the saved OAuth 2.0 Web App callback/origin, `tweet.read`, `users.read` and `offline.access` scopes, refresh-token issuance and protected session/CSRF behavior. Confirm no credentials appear in responses or logs. Use non-repository secrets. Confirm the intended account identity after the callback before importing.
3. Recheck the current console balance/credits, actual endpoint/resource rates, auto-recharge setting and billing-cycle ceiling. Set current, source-referenced app total/daily/operation/import limits and conservative retry/page estimates; reserve room for the OAuth identity read. Stop if credits are unavailable, pricing is unknown or a ceiling cannot be enforced. Do not purchase credits as part of this verification.
4. With a single connected, authorized account, submit one unique import ID and a **maximum of 5 posts / 1 page**. Record the endpoint, request time, returned count and field-presence counts privately. Compare IDs, UTC publication times, topology, owner IDs, source, observed-at times and each metric's state/definition against the canonical and observation rows. Never publish raw responses, post text or tokens.
5. Compare the usage ledger reservation and observed request/result counts to the provider's actual usage/billing report; record currency, unit, rate, measured cost and any unresolved difference. An estimate is not a bill. Stop at the configured ceiling or unexpected charge.
6. Reissue the same import ID and confirm no extra call, row or charge; test a safe failure only if it can be induced without an extra billable call. Check status visibility from the owner session and non-visibility from another session in a disposable/synthetic environment. Verify disconnect revokes local access and a subsequent import fails closed. Record whether refresh/reconnect restores only the authorized account. Do not retry a terminal partial import with a new ID until the remaining budget and rights are rechecked.

Record actual outcomes, missing fields, exclusions, status transitions, cost reconciliation and any blocked step in a private verification record. Do not send real X content to embeddings, Groq or another processor while those uses remain unresolved. COD-349 is **mock-verified only** until this checklist is completed with approved rights and an authorized account.

COD-347 adds a mockable creator-history read adapter over that same `api_usage_ledger`. It reserves the maximum configured page/retry envelope before each HTTP request, then records response count separately from the still-estimated cost until usage reconciliation. Total, daily, operation and import ceilings and a current, source-referenced price must be supplied explicitly; the adapter defaults disabled and has no live API route. The only implemented endpoint is the creator-owned timeline; niche discovery remains unavailable pending COD-375/COD-344. Do not enable real reads until account access, usage rights, billable fields/pricing and limits have been verified.

### COD-421 private Brev embeddings

The API keeps `BIPME_EMBEDDING_PROVIDER=local` by default. To select `remote`, configure `BIPME_EMBEDDING_REMOTE_URL=https://<private-tunnel-host>` and `BIPME_EMBEDDING_REMOTE_TOKEN` in the API secret manager, never in source control. Remote calls require HTTPS, use the immutable `intfloat/multilingual-e5-small` revision and 384-dimensional normalized identity, and fail with a safe 503 through draft analysis; there is no local fallback. The Brev server deployment recipe is in `infra/brev-embedding/`.

Keep inference bound to the Brev VM loopback (`127.0.0.1:8000`). Brev browser terminals/web tunnels do not establish unattended app-to-app transport. For a private Tailscale overlay, on **both Linux hosts** install the official client with `curl -fsSL https://tailscale.com/install.sh | sh`, then run `sudo tailscale up --hostname=bipme-inference` on Brev and `sudo tailscale up --hostname=bipme-api` on the API host. An administrator must authorize both devices in the same tailnet and configure an ACL/grant that permits only the API device to reach the Brev device on TCP 443. On the Brev VM, run `sudo tailscale serve --bg 8000` and inspect `sudo tailscale serve status`; it should show an HTTPS `*.ts.net` address proxying to `127.0.0.1:8000`. Set `BIPME_EMBEDDING_REMOTE_URL` on the API host to that HTTPS origin, then verify `/health` and authenticated synthetic `/embed` from that host before enabling remote mode. The container port remains bound only to Brev loopback. Tailscale Serve requires tailnet HTTPS to be enabled and ACLs still apply; use Serve, never Funnel. See [Tailscale Linux installation](https://tailscale.com/docs/install/linux) and [Serve](https://tailscale.com/docs/features/tailscale-serve). Keep the bearer token in both hosts' secret stores and provision the same value without printing it. If Brev or the API host cannot run the overlay agent, use an approved TLS protected private proxy/tunnel before setting the remote URL; the backend rejects plain HTTP. Brev instance localhost is not backend localhost. No overlay, ACL or live connectivity is provisioned or verified by this repository change.

Before starting GPU compute, have the Brev owner recheck the displayed GPU and storage rates, credit balance and expiry, and any enforceable billing/automatic-stop ceiling. The Linear checkpoint reported USD 1.49/hour and USD 68.63 credits, but expiry and stop controls were not verified; those figures may have changed. Do not start the instance while current costs and stop controls are unknown.

To deploy, copy `infra/brev-embedding/` to the Brev VM, create a private `.env` there with a high-entropy `BIPME_EMBEDDING_TOKEN` from the secret manager (`umask 077` and mode `0600`), then run `docker compose up -d --build` and wait for `/health`. The server caps request bodies at 512 KiB, each batch at eight texts, each text at the API contract's 10,000-character maximum and concurrent GPU inference at one request. On the BipMe API host, provision the same token as `BIPME_EMBEDDING_REMOTE_TOKEN`; set `BIPME_EMBEDDING_REMOTE_URL` to the Serve HTTPS origin and `BIPME_EMBEDDING_TIMEOUT_SECONDS` greater than 0 and at most 60 seconds (default 10). Keep `BIPME_EMBEDDING_PROVIDER=local` until the API host successfully verifies the private route with synthetic content; then explicitly set it to `remote` and restart the API process. The API embedder is cached for the process lifetime, so configuration changes require a process restart. The Docker image pins CUDA runtime, PyTorch, serving packages and model revision; the named model-cache volume retains downloaded weights. Confirm `docker compose ps` health, and use an authenticated synthetic `POST /embed` to verify model/revision/dimensions. Record cold and warm synthetic inference latency without retaining request bodies or vectors. Do not expose port 8000, Jupyter, Swagger/OpenAPI or a public unauthenticated route. Roll back by setting `BIPME_EMBEDDING_PROVIDER=local` and restarting the API, then restore the last known-good image tag or git revision and run `docker compose up -d --build`. Stop Serve with `sudo tailscale serve off` when the service is not in use. Stop GPU compute with `docker compose stop`; this preserves cache on persistent disk, which may continue to incur storage charges. Remove the volume only when deliberately discarding the cache. Restart the Brev instance before starting the container; stop the container and VM afterward to limit GPU charges.

The container runs as UID 10001. A new empty named cache volume inherits that ownership from the image. If an existing cache volume is root-owned, stop the service and either correct it with `docker compose run --rm --user 0 --entrypoint chown embeddings -R 10001:10001 /model-cache`, or remove it and download the model again. Concurrent inference waits up to two seconds for the single GPU slot, then returns a sanitized 503 if it remains busy.

Final smoke sequence (synthetic strings only): start the Brev instance and compose service; verify `/health` reports the pinned revision; bring up the approved private tunnel and check the API host can reach its HTTPS endpoint; set the remote env variables and restart BipMe; run a synthetic query through the actual API `get_embedder()` boundary and assert one 384-value normalized vector plus the expected identity; run the existing COD-352 synthetic retrieval fixture with local and remote providers and compare ranking behavior before enabling remote mode; send a wrong bearer token to `/embed` and verify 401; stop the Brev service and confirm draft analysis returns the safe `embedding_unavailable` 503 without CPU fallback; restart as needed, then stop the container and GPU VM. The private network smoke remains pending until operators establish access and the instance is restarted.

The PostgreSQL-backed API CI job starts `pgvector/pgvector:pg17` and sets `BIPME_TEST_DATABASE_URL`; migration integration tests create an isolated schema, apply the full chain, downgrade to `0001_enable_vector`, verify the extension remains, then upgrade again. To run those tests locally, start the Compose database and run:

```bash
export BIPME_TEST_DATABASE_URL='postgresql+psycopg://bipme:bipme_local_only@127.0.0.1:5432/bipme'
cd apps/api
uv run pytest -q tests/test_persistence_postgres.py
```

The test URL must point at a disposable development database; tests create and drop an isolated schema inside it.

## Start the web app

In a separate terminal:

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

Open the Vite URL printed by the process. The Vite development proxy forwards `/api` calls to `http://127.0.0.1:8000`. The web UI is currently only a development shell with health status.

## Verify changes

Run each block **from the repository root** (or in a separate terminal). The first `cd` changes your working directory.

API:

```bash
cd apps/api
uv run ruff check src tests alembic
uv run ruff format --check src tests alembic
uv run mypy src
uv run pytest -q
```

Web:

```bash
cd apps/web
pnpm lint
pnpm typecheck
pnpm build
pnpm format:check
```

`pnpm format:check` is available locally but is **not currently a CI step**. Add browser E2E tests when actual user flows are introduced. `api-checks`, `web-checks` and `workspace-checks` are the three existing GitHub Actions jobs.

## OpenAPI and Web handoff

FastAPI owns the API contract. Regenerate the committed OpenAPI artifact from the app when routes or schemas change:

```bash
cd apps/api
uv run python -c 'import json; from bipme.api.app import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))' > openapi.json
```

`tests/test_analysis_api.py` checks that the artifact matches the generated schema. COD-356 and COD-360 should generate their client types from `apps/api/openapi.json`; do not hand-copy response interfaces. Draft text is fingerprinted but is not stored. Reusing an `Idempotency-Key` with the same creator and canonical input replays the original immutable assessment; a different input returns 409.

The Web client contract is generated from that checked-in artifact with pinned `openapi-typescript`, `openapi-fetch`, MSW and Vitest versions. From `apps/web`, run:

```bash
pnpm generate:api
pnpm check:api
pnpm test
```

`generate:api` writes `src/api/generated/schema.d.ts`; `check:api` regenerates into a temporary directory and fails when the checked-in output is stale. Neither command starts the API or makes network requests. `src/api/client.ts` is the reusable same-origin client: it sends cookies, retains the server-provided CSRF token only in memory, accepts `AbortSignal` for cancellable reads, maps structured API errors to `ApiRequestError`, and preserves HTTP status, API codes, validation details and rate-limit headers. Synthetic MSW handlers and fixtures live in `src/api/mocks.ts` and `src/api/fixtures.ts`; they must not be treated as production creator data.

COD-361's publication route is `POST /api/v1/creators/me/draft-assessments/{assessment_id}/publication`. It accepts only a trimmed HTTPS `x.com`/`twitter.com` status URL or numeric post ID; the provider, not the browser, supplies author and publication time. The route is read-only, requires the connected creator-owned account, reserves a bounded retry envelope before any provider call, and relies on database uniqueness for safe duplicate/concurrent requests. A private assessed-text fingerprint is compared with provider evidence; `mismatch` and `unknown` remain linked for audit context but are not exact-draft evaluation evidence. Legacy assessments without the private comparison metadata stay `unknown`.

COD-378 adds typed `/api/v1/creators/me/profile`, `/data-permissions`, `/report`, `/report/latest` and `/reports/{id}` contracts. Profile updates append revisions; report generation is draft-free and replays by creator-scoped `Idempotency-Key`. `data_sources` currently accepts only explicitly opted-in personal history; the server-side X-history policy gate requires both `BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED=true` and a valid `BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT` timestamp, niche discovery is unavailable, and synthesis is disabled. The latest report response exposes coverage, source freshness, processing permission snapshot and limitations so Web can render insufficient/partial states without inventing data. Regenerate `openapi.json` when these schemas change.

COD-379's dashboard uses those wrappers for concise profile onboarding, history-permission consent, latest-report retrieval, deterministic report generation and report-snapshot deletion. It keeps personal history and niche evidence in separate sections, labels historical/partial/insufficient states, and routes `Analyze a Draft` to the existing navigation shell without implementing COD-360. The dashboard passes only a typed in-memory creator/report context to that route; refresh or direct navigation intentionally loses the handoff and displays the safe unconfigured draft state. COD-378 currently has no niche-discovery consent field, niche import/progress field or budget/cost-cap state; its `niche_discovery` permission is fixed to `unavailable`, so COD-379 must not claim the intended two-source experience. The report's nested `report` and `evidence` structures remain weakly typed dictionaries in the generated COD-378 contract, so the web layer defensively narrows them at render time until an upstream contract revision provides stable sub-schemas.

COD-357 PR #40 remains a separate draft integration risk: it introduces another web auth client and overlapping navigation/state components in `App.tsx`. It should be rebased onto current `main` and reconciled with COD-356's shared generated client before merging; COD-379 does not alter that branch.

The GitHub Actions workflow runs on PRs targeting `main`; it uses locked Python installation and frozen pnpm installation. The API job's PostgreSQL service is pgvector-enabled so persistence tests exercise real PostgreSQL constraints, vector queries and Alembic upgrades/downgrades. No CI job should call live X endpoints.

## Repository workflow

1. Read the relevant file(s), applicable `AGENTS.md`, and only the necessary documentation for the task.
2. Confirm task scope and acceptance criteria; create a **short-lived branch from current `main`**.
3. Implement a cohesive change with corresponding tests. For features, update their documented behavior when it changes.
4. Run targeted checks and relevant full checks; review the diff for accidental secrets, data leakage and unrelated changes.
5. Open a PR to `main` with scope, verification, limitations and risk notes. Resolve real review findings and rerun CI on the latest commit.
6. **Do not merge without explicit authorization.** Prefer squash merges. Delete merged branches when GitHub configuration allows.

No permanent `dev`/`beta` branch is needed for the one-account phase. GitHub ruleset and merge preferences must be verified in the **repository settings**; this guide alone does not enforce them.

## Database and API changes

- All persistent schema changes use SQLAlchemy models plus an Alembic migration; check forward and downgrade behavior.
- Keep the X payload adapter separate from canonical application entities.
- Maintain FastAPI OpenAPI as the authoritative API contract; generate TypeScript API types rather than manually duplicating contracts.
- Add Python dependencies via `uv add` (or `uv add --dev`) and frontend dependencies via `pnpm add`, then commit resolver-produced lockfile changes.
- Do not add network services, queues or separate databases without a demonstrated need.

## Testing live X integration

No real X API credentials are required for routine local/CI scaffold tests. Before testing real OAuth or ingesting post data, see [Security](security.md); verify developer console permissions, enforce an API budget, and use a small initial read. Do not commit screenshots, logs or fixtures containing tokens or private creator data.

## Troubleshooting

- **API unavailable in web shell:** confirm the FastAPI process runs on port 8000 and the Vite proxy is active.
- **Migration cannot connect:** check `docker compose ps`, the host port, and exported `BIPME_DATABASE_URL`.
- **Dependency mismatch:** regenerate locks using the real package managers; do not edit lockfiles manually.
- **Type/lint failures:** run the exact job commands above and fix underlying code, not just CI configuration.

COD-361 also exposes `GET /api/v1/creators/me/draft-assessments/{assessment_id}/publication` for owner-scoped historical status without a provider call. Publication verification requires `BIPME_X_PUBLICATION_PRICING_OBSERVED_AT`, `BIPME_X_PUBLICATION_PRICING_EXPIRES_AT` and `BIPME_X_PUBLICATION_PRICING_SOURCE` as well as the existing explicit rights, entitlement and budget settings. Missing/expired pricing fails closed. Committed verification digests are reused after attachment rollback; ambiguous reservations without evidence remain blocked for reconciliation rather than authorizing another paid read. Equal text with unverifiable media content, thread role or reply/quote targets remains unknown for evaluation.

## COD-420 frontend handoff for COD-359 / COD-360

Aliyu should use the generated `PostEvidence`, `MetricObservationEvidence`, `EvidencePage` and `ImportPage` contracts; the only Web change in COD-420 is regenerated types. Use the existing same-origin authenticated client and cookies:

```ts
// COD-359 history: retain next_cursor and pass it as cursor on the next call.
client.GET('/api/v1/creators/me/history/posts', {
  params: { query: { limit: 20 } },
})
// COD-360 comparable drill-down: take canonical IDs from the saved assessment,
// not provider IDs; this pins observations to the immutable prediction cutoff.
client.GET('/api/v1/creators/me/history/evidence', {
  params: { query: { post_ids: canonicalIds.slice(0, 50), assessment_id: assessmentId } },
})
client.GET('/api/v1/creators/me/history/posts/{post_id}', {
  params: { path: { post_id: canonicalPostId } },
})
client.GET('/api/v1/creators/me/history/imports', {
  params: { query: { limit: 10 } },
})
```

Batch items are ordered by publication time/ID, not request order. Match IDs explicitly and treat omitted IDs as unavailable without inferring their ownership. Render disclosure states, null text/URL, observation truncation, source freshness and empty evidence honestly. Decimal metric values arrive as strings: never coalesce null to zero. Use each exact metric definition/unit/window; never substitute another series or newer observations for original prediction evidence. Observation provenance is deliberately narrow. An archive/unknown-source metadata-only card does not establish permission to display its text or metrics. Import status does not prove sufficient analytical evidence. The current policy and creator permission apply even to a historical assessment read; revocation is not bypassed by an old cursor.

Run `BIPME_TEST_DATABASE_URL=... uv run pytest -q tests/test_evidence_api.py` against disposable PostgreSQL for auth/isolation, cursor, temporal, permission, provenance and query-count checks. Read routes do not need X credentials. The API returns 401/403 through existing auth, 404 for hidden/missing detail, 422 for invalid bounds/cursors/cutoffs, and sanitized 503 for store failure.
