# Forge Team 17 release runbook (COD-426)

This prepares a release; it does not deploy one. The authoritative contract is the
operator-supplied **Forge 2026 Sandbox Participant Platform Guide v1.0, 9 Nov 2026**,
sections 2–4 and 7–9. Do not publish the private guide or any credentials.
Run commands in Bash (WSL/Linux), from the repository root, with kubectl >=1.30.
Do not run these cluster commands until the owner explicitly authorizes deployment.

## Mandatory gates

1. The previously shared `team17.yml` is compromised. Ask organizers to revoke it
   and issue a replacement through their private channel. Never read, decode, test,
   reuse or paste it. Do not put either credential in this repository, CI, or chat.
   Organizers must confirm revocation before replacement access is used. Contact
   details in guide section 9 are TBC; obtain the actual private support channel.
2. Obtain the approved storage class name, support for a **10Gi ReadWriteOnce PVC**,
   retention/reclaim policy, event-end export deadline, and permission for StatefulSets,
   Jobs, PVCs, ConfigMaps, Secrets and NetworkPolicies. The guide does not name the
   storage class or specify Pod Security admission. Confirm UID/GID 999 with fsGroup
   ownership for PostgreSQL, UID 101 for web, UID 10001 for API/worker, RuntimeDefault
   seccomp and non-root volume writes. No privileged/chown init container is included.
   If cluster-scoped storage discovery is forbidden, ask organizers; do not broaden RBAC.
3. Verify the gateway preserves browser Origin and Set-Cookie and provides HTTPS-only
   public access. The guide establishes upstream TLS termination, but not header
   sanitization. This deployment does **not** trust its forwarded headers: NGINX uses
   the fixed public origin and overwrites forwarded metadata; Uvicorn ignores proxy
   headers. Confirm existing namespace network policies do not independently allow
   ingress to API/DB: Kubernetes policy allows are additive. Keep organizer isolation.
4. Only synthetic data and synthetic creator identities. No X OAuth secrets, real
   exports, real creator data, remote-model credentials, bank integration or gateway
   key. X gates and synthesis remain disabled. No public seed endpoint exists.
5. Run the static/container checks below and require CI green for the chosen SHA.
   Verify all three published linux/amd64 image digests and cluster registry access.
   Runtime fit and cluster quota consumption must be measured after authorization;
   the requests below are an initial budget, not evidence that Forge will fit.

## Resources and architecture

| Workload | CPU request / limit | Memory request / limit |
| --- | --- | --- |
| app | 25m / 200m | 32Mi / 96Mi |
| api | 100m / 650m | 256Mi / 640Mi |
| worker | 50m / 350m | 128Mi / 384Mi |
| db | 150m / 600m | 256Mi / 640Mi |
| one migration Job | 50m / 200m | 64Mi / 192Mi |
| steady state | 325m / 1800m | 672Mi / 1760Mi |
| including migration | **375m / 2000m** | **736Mi / 1952Mi** |
| namespace ceiling | **400m / 2000m** | **768Mi / 2048Mi** |

Four steady pods, five with migration, of ten allowed; three ClusterIP Services of
five; one 10Gi PVC of one allowed. No worker Service, Ingress, LoadBalancer,
NodePort, Namespace, cluster RBAC, autoscaler or sidecar. Default container limits
from the guide are not relied upon. No extra diagnostic pods fit the CPU limit
while migration is active. Include unrelated existing namespace workloads in checks.
Deployments use Recreate (brief downtime); stop and wait for termination before
migrations/upgrades. Do not scale replicas or manually delete a running pod to
force an overlapping replacement. Delete completed/failed Jobs after recording a
sanitized result; only one migration may exist/run at once.

Gateway -> `app:80` -> NGINX:8080 -> `api:8000` -> `db:5432`.
Worker uses the same API image and PostgreSQL queue. Backend ingress permits only
the required same-namespace pod labels. Egress permits DNS and internal API/DB
ports only; external inference and live X cannot be enabled by flipping a flag alone.
No service-account tokens are mounted. Web/API roots are read-only with bounded
temporary volumes; PostgreSQL persists only on the PVC and uses a `pgdata`
subdirectory so a filesystem's `lost+found` does not break initdb.

NGINX resolves the stable API **Service ClusterIP** using Kubernetes pod DNS at
startup, not Docker's `127.0.0.11`. Apply Services before web. API pod replacement
does not change the Service IP. If the API Service is deliberately recreated,
restart web after the Service exists. The Forge template is mounted into the
existing image; the Compose frontend configuration remains unchanged. `/api` and
the full query string are preserved. Cookies, CSRF and Origin pass through; response
cache headers are forced private/no-store. Requests are not retried upstream.
Headers/cookies/URL query strings are not logged by NGINX; Uvicorn access logs are off.

`/healthz` checks NGINX; `/api/health` checks API liveness only. API and worker
readiness execute a bounded DB connection and require the exact Alembic heads
in the image. DB readiness uses pg_isready. Worker readiness does not prove task
execution/heartbeat freshness; inspect queue/worker state separately. A DB outage
removes API readiness without liveness restart loops. Migrations are not run at
every API/worker startup. The one-shot Job has no automatic retry; inspect a failed
migration before retrying. Alembic upgrade head is repeatable once successful, not
a promise that every interrupted future migration is safely retryable.

## Build and offline verification

```bash
python3 infra/forge/test_manifests.py
python3 infra/forge/render.py --sha "$(git rev-parse HEAD)" --storage-class ci-validation-only
docker run --rm -v "$PWD/infra/forge/rendered:/manifests:ro" \
  ghcr.io/yannh/kubeconform:v0.6.7 -strict -summary -kubernetes-version 1.30.0 /manifests
docker build --platform linux/amd64 -f apps/web/Dockerfile -t bipme-forge-web:test .
python3 infra/forge/smoke_proxy.py
```

`forge.yml` validates PRs without Kubernetes credentials; main pushes, an explicit
`forge-<full-git-sha>` Git tag, or deliberate workflow_dispatch builds publish the existing API/frontend Dockerfiles and a
pgvector image wrapper. Images are `ghcr.io/onerandomd3v/bipme-api:<full-git-sha>`,
`bipme-web:<full-git-sha>`, and `bipme-postgres:<full-git-sha>` under the same registry
owner. Worker/migration use the exact API tag. No latest tags. CI refuses an existing
tag rather than overwriting it; retain the original digest on reruns. A partial
publication requires investigating and verifying the already published image(s),
not deleting/retagging them. Record all three digests from the workflow summary in
the private release record. Upstream base tags are mutable: a Git SHA identifies
the once-published build, not a guarantee that rebuilding later gives identical bits.
Do not change PostgreSQL major version during an application release.

To publish a reviewed PR commit before merge, wait for all its CI checks to pass,
then create and push its exact release tag. This publishes images only; no job has
cluster credentials or deploys anything. Do not move or overwrite a release tag.

```bash
SHA=$(git rev-parse HEAD)
git tag "forge-$SHA"
git push origin "forge-$SHA"
```

For private GHCR packages, provision a read-only package pull credential in a private
Docker config file **outside Git**, then after authorization:

```bash
kubectl -n team17 create secret generic regcred \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson="$HOME/forge-private/docker-config.json"
```

Do not put tokens on command lines, paste Secret YAML, or add registry credentials
to CI beyond its scoped GITHUB_TOKEN. Use `--pull-secret regcred` when rendering.
For confirmed public packages omit it. Never inject `huawei-gateway` into BipMe.

## Private configuration and preflight (after authorization and rotation)

```bash
export KUBECONFIG="$HOME/forge-private/team17-replacement.yaml"
chmod 600 "$KUBECONFIG"
kubectl -n team17 auth can-i create deployments
kubectl -n team17 auth can-i create statefulsets
kubectl -n team17 auth can-i create jobs
kubectl -n team17 auth can-i create persistentvolumeclaims
kubectl -n team17 auth can-i create networkpolicies
kubectl -n team17 auth can-i create secrets
kubectl -n team17 get pods,svc,pvc
kubectl -n team17 describe resourcequota team-quota
kubectl -n team17 get limitrange,networkpolicy
```

Review policies privately with organizers; do not probe another namespace. No
command in this runbook retrieves Secret data, service-account tokens or kubeconfig
contents. Never run `kubectl config view --raw` or `kubectl get secret -o yaml`.

Provision two private files through the operator's secret manager: `db.env` has
POSTGRES_PASSWORD (fresh high-entropy URL-safe password) and BIPME_DATABASE_URL
(`postgresql+psycopg://bipme:<same-password>@db:5432/bipme_demo`). `auth.env` has
BIPME_CREATOR_ID (new synthetic UUID) and BIPME_PRIVATE_LOGIN_SECRET (at least 32
random bytes). Use restrictive directory/file permissions; neither file belongs in
the repo or a shell transcript. Both files contain server secrets. The worker and
migration reference only the database URL, never the auth secret.

```bash
kubectl -n team17 create secret generic bipme-db --from-env-file="$HOME/forge-private/db.env"
kubectl -n team17 create secret generic bipme-auth --from-env-file="$HOME/forge-private/auth.env"
```

The initial API runs production auth with Secure, HttpOnly, SameSite=Lax, Path=/,
`__Host-bipme_session`, and origin `https://team17.xtradot.co`. Creator sign-in stays
unavailable until that synthetic creator exists; this does not block an initial
healthy infrastructure release. Do not insert real creator identity to bypass it.
The database bootstrap role is the single synthetic instance's owner; never reuse
it for real data or a shared production database. Separate least-privilege runtime
DB roles would be a prerequisite to expanding that boundary.

## Exact first rollout

Set SHA to the reviewed **full commit SHA** whose three images were published;
set STORAGE_CLASS to the organizer-confirmed class (not ci-validation-only).
Render outside Git or in the ignored directory. Keep the previous rendered release
privately for rollback. Do not apply the source JSON containing placeholders.

```bash
export SHA='<reviewed-full-40-character-git-sha>'
export STORAGE_CLASS='<organizer-confirmed-class>'
python3 infra/forge/render.py --sha "$SHA" --storage-class "$STORAGE_CLASS" --pull-secret regcred
kubectl -n team17 apply --dry-run=server -f infra/forge/rendered/foundation.json
kubectl -n team17 apply -f infra/forge/rendered/foundation.json
kubectl -n team17 apply --dry-run=server -f infra/forge/rendered/database.json
kubectl -n team17 apply -f infra/forge/rendered/database.json
kubectl -n team17 rollout status statefulset/db --timeout=300s
kubectl -n team17 get pvc bipme-postgres
# With WaitForFirstConsumer storage, binding occurs after the DB pod is scheduled.
kubectl -n team17 apply --dry-run=server -f infra/forge/rendered/migration.json
kubectl -n team17 apply -f infra/forge/rendered/migration.json
kubectl -n team17 wait --for=condition=complete "job/bipme-migrate-${SHA:0:12}" --timeout=600s
# Inspect sanitized migration status privately; stop on any failed condition.
kubectl -n team17 delete job "bipme-migrate-${SHA:0:12}" --wait=true
kubectl -n team17 apply --dry-run=server -f infra/forge/rendered/workloads.json
kubectl -n team17 apply -f infra/forge/rendered/workloads.json
kubectl -n team17 rollout status deployment/api --timeout=300s
kubectl -n team17 rollout status deployment/worker --timeout=300s
kubectl -n team17 rollout status deployment/app --timeout=300s
kubectl -n team17 get pods,svc,pvc
kubectl -n team17 describe resourcequota team-quota
curl --fail --silent --show-error https://team17.xtradot.co/healthz
curl --fail --silent --show-error https://team17.xtradot.co/api/health
```

Stop if dry-run, PVC binding, migration, readiness or rollout fails. Never continue
by suppressing a failed command. `kubectl logs deploy/api --tail=50`, `logs deploy/worker`
and `logs statefulset/db` are private troubleshooting only; redact before sharing.
`kubectl describe pod <name>` helps diagnose admission, pull or mount failures.
Do not dump process environments or enable verbose HTTP/SQL logs.

## Backup, upgrades, restore and rollback

Before the first demo activation, before every migration and before event closure,
stop app/API/worker (in that order), wait for their pods to terminate, then export
to encrypted operator storage outside the namespace. Never delete the PVC or use
`kubectl delete -f` on the foundation. A PVC is persistence, not an off-cluster backup.

```bash
kubectl -n team17 scale deployment/app deployment/api deployment/worker --replicas=0
kubectl -n team17 wait --for=delete pod -l app.kubernetes.io/name=app --timeout=180s
kubectl -n team17 wait --for=delete pod -l app.kubernetes.io/name=api --timeout=180s
kubectl -n team17 wait --for=delete pod -l app.kubernetes.io/name=worker --timeout=180s
umask 077
BACKUP="$HOME/forge-private/bipme-$(date -u +%Y%m%dT%H%M%SZ).dump"
kubectl -n team17 exec db-0 -- pg_dump -U bipme -d bipme_demo -Fc --no-owner --no-acl > "$BACKUP"
test -s "$BACKUP"
sha256sum "$BACKUP" > "$BACKUP.sha256"
```

Check the pg_dump command exit code, not just nonzero file length. Capture the old
image digests, Alembic revision (`SELECT version_num FROM alembic_version`), PostgreSQL
major version and rendered manifests in the private backup record. Keep exports
encrypted and access-controlled even though they contain synthetic data and session
hashes. A baseline before first migration can use the same pg_dump command on the
empty database. Rehearse restore **before trusting a backup**, using a disposable
local PostgreSQL 17/pgvector database and `pg_restore --exit-on-error --no-owner
--no-acl`. Verify extension, revision, table counts, session isolation and app read
smokes. Do not start a second PVC in Forge for a rehearsal.

For upgrades, publish a new SHA, stop/drain, back up, render the new release and
apply foundation. Keep DB image unchanged unless a separately reviewed PG17 patch
upgrade is intended; then stop DB cleanly, retain PVC and apply database. Run the
migration phase exactly as above, verify completion, delete the completed Job and
apply workloads. Record readiness, fresh login/CSRF tests and queue health. A
successful migration with an unchanged schema is a no-op; do not run two Jobs.

If the schema remains compatible, rollback all three Deployments to the recorded
previous revision, or apply the previous rendered workloads:

```bash
# Inspect rollout history first; choose the recorded matching release revisions.
kubectl -n team17 rollout history deployment/api
kubectl -n team17 rollout undo deployment/api --to-revision='<previous-api-revision>'
kubectl -n team17 rollout undo deployment/worker --to-revision='<previous-worker-revision>'
kubectl -n team17 rollout undo deployment/app --to-revision='<previous-app-revision>'
kubectl -n team17 scale deployment/api deployment/worker deployment/app --replicas=1
kubectl -n team17 rollout status deployment/api --timeout=300s
kubectl -n team17 rollout status deployment/worker --timeout=300s
kubectl -n team17 rollout status deployment/app --timeout=300s
```

Hashed ConfigMaps preserve prior release configuration; retain them while revisions
are rollback candidates. Secrets are not rolled back by Deployment undo. Readiness
requires the image's exact migration head; an older image against a newer schema
will intentionally remain unready even if someone believes it compatible. Prefer
rolling forward; never automatically `alembic downgrade` or downgrade PostgreSQL.

For an incompatible schema, keep app/API/worker stopped. Obtain separate explicit
approval for data replacement, verify the backup hash and successful rehearsal,
then use PG17 tools to recreate **only** `bipme_demo` and restore. The following
is destructive recovery, not part of normal rollout:

```bash
sha256sum -c "$BACKUP.sha256"
kubectl -n team17 exec db-0 -- dropdb -U bipme --force bipme_demo
kubectl -n team17 exec db-0 -- createdb -U bipme -O bipme bipme_demo
kubectl -n team17 exec -i db-0 -- pg_restore -U bipme -d bipme_demo \
  --exit-on-error --no-owner --no-acl < "$BACKUP"
```

Apply the backed-up workloads/configuration, invalidate restored sessions before
reopening access, verify revision/counts/health and test private login. Restore
does not recover writes after the backup; declare that loss before approval. Test
persistence after authorization by recording non-sensitive synthetic counts,
restarting DB cleanly with the same PVC, then comparing counts and readiness.

## Demo activation and inference boundary

COD-424 merged at `78d3fa0ac8b9f27015cdd6a1045c8ca1b55b8106`; its seeder and synthetic
embedding identity remain unchanged. COD-425's web walkthrough subsequently merged
in PR #62; it remains a separate implementation, incorporated from main without
changes here. Do not claim a complete demo from health alone.

Base configuration selects remote embeddings **without a URL/token**. The existing
dependency returns sanitized `503 embedding_unavailable`; it neither downloads a
local model nor invents a vector. Report synthesis is disabled and deterministic
report paths retain their existing permission checks. Brev/Tailscale reachability
is unverified, and local E5 previously measured ~1GiB working set on Windows, which
does not establish fit in this budget. No MaaS/bank key is injected. Enabling real
inference needs a separate reviewed private route, egress rule, TLS/auth, rights/cost
checks and cold/warm resource measurements; no public tunnel or silent CPU fallback.

After approved synthetic activation and COD-425 integration, back up and stop API/
worker. Run COD-424's CLI **on the operator machine**, from the matching checked-out
release and locked dependencies, through a loopback-only database port forward:

```bash
kubectl -n team17 port-forward --address 127.0.0.1 service/db 15432:5432
```

In another private terminal, secret-manager inject the same synthetic creator UUID
as both BIPME_CREATOR_ID and BIPME_SYNTHETIC_DEMO_CREATOR_ID, database password in
BIPME_DATABASE_URL with host **127.0.0.1**, port **15432**, database **bipme_demo**,
and set the following non-secret settings:

```bash
export BIPME_ENVIRONMENT=demo
export BIPME_SYNTHETIC_DEMO_ENABLED=true
export BIPME_EMBEDDING_PROVIDER=synthetic_demo
export BIPME_SYNTHETIC_DEMO_DATABASE_NAME=bipme_demo
cd apps/api
uv sync --locked --group dev
uv run python -m bipme.devtools.synthetic_demo --synthetic-demo \
  --archive '<operator-verified-synthetic-archive.zip>' \
  --scenarios '<operator-verified-synthetic-monitoring-scenarios.json>'
```

Stop the port forward immediately afterward. Never rewrite the loopback check or
run the seeder against `db` from a cluster Job. Do not fabricate missing fixture
files; obtain COD-424's actual validated synthetic inputs. Set API runtime to
`BIPME_ENVIRONMENT=demo`, the same three synthetic settings and synthetic UUID,
while **retaining** Secure cookies, public origin, private auth and all disabled X/
synthesis settings. Make this an explicitly reviewed release configuration change
to foundation.json, re-render (new ConfigMap hashes), and apply before restarting
workloads. `demo` is a data-source gate, not permission for insecure public auth.
Worker receives no demo/auth settings and remains live-X disabled.

Use the actual public browser flow: private login, session refresh, report, draft,
evidence, and simulated postmortem from COD-424/425. Check missing/wrong CSRF and
foreign Origin mutations are rejected, Secure/HttpOnly cookie attributes, logout
revocation, unauthenticated 401/403, and no provider requests. Keep secret values,
cookies and full browser/network captures private. A synthetic embedder is not E5
quality evidence. If activation conflicts with a safeguard, stop; never bypass it.

## Rotation and measurement record

For registry credentials, rotate the external read-only credential, update regcred
privately and test a pull before retiring the old one. For auth, stop access, rotate
the high-entropy login secret via the private secret mechanism, revoke existing
creator sessions (changing the login secret alone does not revoke them), restart
API and verify new login and old-cookie rejection. For DB password, stop/drain
consumers, change the actual database role password using an approved private
interactive administration session, update both fields of bipme-db, then restart
API/worker. Changing POSTGRES_PASSWORD alone **does not** alter an initialized DB.
Never print values in command arguments, SQL logs, CI logs or support messages.

Initial evidence (11 Nov 2026): CI passed strict Kubernetes 1.30 schema validation,
the real-image Forge proxy/header/cookie/CSRF-origin smoke, non-root PG17 startup,
repeat migrations, DB-aware readiness failure/recovery, dump/restore, persistence
across DB restart and worker registration. In the resource-limited Docker smoke,
one post-start snapshot was API 79.04MiB (0.09% CPU), worker 55.52MiB (34.82% CPU,
still starting), DB 17.9MiB (0.03% CPU). These are neither peaks nor steady-load
benchmarks; no inference ran. See [CI run 262](https://github.com/onerandomd3v/BipMe/actions/runs/43024448351)
and [Forge validation run 2](https://github.com/onerandomd3v/BipMe/actions/runs/43024892741).
Manifest budget and offline validations are automated. Local Docker
image builds on 11 Nov 2026 were blocked by upstream layer-download EOF/TLS timeouts;
CI runs the actual-image smoke tests independently. No Forge
runtime, PVC binding, gateway, network isolation, restart durability, inference or
quota consumption has been measured. Local Docker smoke measurements are useful
only as startup evidence; they do not establish Forge's p95/load behavior.
After authorization record `kubectl -n team17 top pods --containers` (if permitted),
quota used/hard, restarts/OOMKills, throttling, PVC capacity and cold/warm health +
authenticated synthetic latency. Measure at idle and under one bounded synthetic
walkthrough. Stop on OOM, sustained throttling, unready pods, failed drains or quota
rejection; adjust allocations only within the exact namespace ceiling or ask
organizers. Do not enable local ML to test fit on the public sandbox.

Technical references: [Kubernetes Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/),
[Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/),
[NGINX proxy URI and header behavior](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).
