# BipMe API and worker containers

The FastAPI application and Procrastinate worker use the same Python image and the existing `apps/api/src/bipme` package. Compose manages them as separate processes: each can be started, stopped, restarted, logged, and scaled independently. The worker receives the database URL plus only the settings needed to register and run the existing metric snapshot handler; it does not receive API session, OAuth client, remote embedding, or Groq synthesis settings. It has no published or exposed HTTP port. The root `compose.yaml` remains the local-development database workflow.

## Configure and start

From the repository root, create the deployment settings file and replace the placeholder password with a strong URL-safe secret. Keep the file private and out of version control.

```bash
cp infra/api-worker/.env.example infra/api-worker/.env
chmod 600 infra/api-worker/.env
```

The API may also load API-specific runtime settings from `apps/api/.env`. Compose treats that file as optional and overrides its database URL with the deployment URL. The narrowly scoped metric snapshot settings in `infra/api-worker/.env` go to both the API producer and worker handler; all other API-only settings stay out of the worker environment. Leave X handler settings disabled and blank unless its access, processing rights, current pricing, and cost limits have been verified. Supply optional API secrets through its service env file or a deployment secret manager; never add them to the image.

Apply migrations before starting the API or worker:

```bash
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml build api
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml up -d db
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml run --rm api alembic upgrade head
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml up -d api worker
```

The PostgreSQL container uses the existing pgvector-enabled `pgvector/pgvector:pg17` image and a persistent named volume. Its port is not published to the host. For a managed/external PostgreSQL service, provide its reachable psycopg URL as `BIPME_DATABASE_URL` and use an appropriate Compose override that omits the `db` service and dependency. Back up the PostgreSQL volume or managed database independently.

## Independent lifecycle

```bash
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml logs -f api
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml logs -f worker
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml restart worker
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml stop worker
docker compose --env-file infra/api-worker/.env -f infra/api-worker/compose.yaml start worker
```

Both services use `restart: unless-stopped`. Docker Compose sends SIGTERM and allows up to two minutes for graceful process shutdown before SIGKILL. The worker entrypoint handles SIGTERM, drains its active handler according to the existing worker supervision contract, and then closes its database engine. Uvicorn handles API shutdown. `docker compose down` stops the processes while retaining the database volume; `docker compose down -v` deletes that data and should only be used deliberately.

The worker command is `python -m bipme.jobs`; the API command is `uvicorn bipme.api.app:app --host 0.0.0.0 --port 8000`. The API is bound to host loopback by default for a local reverse proxy. Put TLS, access controls, and production secret injection at the host/control-plane layer before external use. No production deployment is performed by this configuration.
