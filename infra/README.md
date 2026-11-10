# Infrastructure

The repository-root `compose.yaml` runs local PostgreSQL/pgvector. Its database settings are local development values and are not a production deployment configuration.

`brev-embedding/` is the standalone private GPU inference service. Its configuration belongs to `brev-embedding/.env.example`; create a private `.env` on the Brev host and use that directory's Compose file. Keep its `BIPME_EMBEDDING_TOKEN` in the Brev host's secret store and provision the matching API credential separately. See `docs/development.md` for local API setup, remote embedding boundaries, and deployment checks.

On the Linux Brev host, after copying this directory and provisioning the placeholder from a private secret store:

```bash
cd infra/brev-embedding
umask 077
cp .env.example .env
# Replace BIPME_EMBEDDING_TOKEN in .env using a secure editor or secret injection.
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Compose reads this `.env` for interpolation and passes only the declared service variables into the container. `LOG_LEVEL` defaults to `WARNING`; the model identity and inference settings remain pinned in `app.py`.
