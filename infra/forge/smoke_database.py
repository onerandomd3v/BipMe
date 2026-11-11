"""Synthetic local Docker test: non-root PG, migrations, readiness, backup and restart."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent


def docker(*args, check=True, binary=False, data=None):
    result = subprocess.run(["docker", *args], capture_output=True, text=not binary, input=data)
    if check and result.returncode:
        raise RuntimeError(f"Docker {args[0]} failed (details withheld to protect environment)")
    return result


def wait_for(command, tries=90):
    for _ in range(tries):
        if docker(*command, check=False).returncode == 0:
            return
        time.sleep(1)
    raise AssertionError("Container readiness deadline exceeded")


def main():
    suffix = uuid.uuid4().hex[:10]
    network, db, api, worker, volume = (f"forge-{n}-{suffix}" for n in ("net", "db", "api", "worker", "data"))
    image = os.getenv("BIPME_API_SMOKE_IMAGE", "bipme-api:local")
    with tempfile.TemporaryDirectory() as directory:
        db_env = Path(directory) / "db.env"
        api_env = Path(directory) / "api.env"
        password = secrets.token_urlsafe(32)
        db_env.write_text(f"POSTGRES_USER=bipme\nPOSTGRES_DB=bipme_demo\nPOSTGRES_PASSWORD={password}\nPGDATA=/var/lib/postgresql/data/pgdata\n")
        api_env.write_text(f"BIPME_DATABASE_URL=postgresql+psycopg://bipme:{password}@{db}:5432/bipme_demo\nBIPME_ENVIRONMENT=production\nBIPME_AUTH_COOKIE_SECURE=true\nBIPME_APP_ORIGIN=https://team17.xtradot.co\nBIPME_EMBEDDING_PROVIDER=remote\n")
        common = ["--network", network, "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", "10001:10001", "--tmpfs", "/tmp:uid=10001,gid=10001,size=33554432", "--env-file", str(api_env), "--mount", f"type=bind,src={ROOT / 'check_db.py'},dst=/opt/forge/check_db.py,readonly"]
        try:
            docker("network", "create", network)
            docker("volume", "create", volume)
            docker("run", "-d", "--name", db, "--network", network,
                   "--user", "999:999", "--read-only", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges", "--memory=640m", "--cpus=0.6",
                   "--env-file", str(db_env), "-v", f"{volume}:/var/lib/postgresql/data",
                   "--tmpfs", "/var/run/postgresql:uid=999,gid=999,size=8388608",
                   "--tmpfs", "/tmp:uid=999,gid=999,size=33554432",
                   "pgvector/pgvector:pg17", "postgres", "-c", "shared_buffers=64MB", "-c", "max_connections=30")
            wait_for(["exec", db, "pg_isready", "-U", "bipme", "-d", "bipme_demo"])
            assert docker("run", "--rm", *common, image, "python", "/opt/forge/check_db.py", check=False).returncode != 0
            for _ in range(2):
                docker("run", "--rm", *common, "--memory=192m", "--cpus=0.2", image, "alembic", "upgrade", "head")
            docker("run", "--rm", *common, image, "python", "/opt/forge/check_db.py")
            marker = str(uuid.uuid4())
            docker("exec", db, "psql", "-U", "bipme", "-d", "bipme_demo", "-v", "ON_ERROR_STOP=1", "-c", f"INSERT INTO creators (id, created_at, updated_at) VALUES ('{marker}', now(), now())")
            dump = docker("exec", db, "pg_dump", "-U", "bipme", "-d", "bipme_demo", "-Fc", "--no-owner", "--no-acl", binary=True).stdout
            assert len(dump) > 0
            docker("exec", db, "createdb", "-U", "bipme", "restore_check")
            docker("exec", "-i", db, "pg_restore", "-U", "bipme", "-d", "restore_check", "--exit-on-error", "--no-owner", "--no-acl", binary=True, data=dump)
            query = ["psql", "-U", "bipme", "-Atqc", "SELECT count(*) FROM creators"]
            assert docker("exec", db, *query, "restore_check").stdout.strip() == "1"
            docker("restart", "-t", "120", db)
            wait_for(["exec", db, "pg_isready", "-U", "bipme", "-d", "bipme_demo"])
            assert docker("exec", db, *query, "bipme_demo").stdout.strip() == "1"
            docker("run", "-d", "--name", api, *common, "--memory=640m", "--cpus=0.65", image, "uvicorn", "bipme.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log")
            docker("run", "-d", "--name", worker, *common, "--memory=384m", "--cpus=0.35", image, "python", "-m", "bipme.jobs")
            wait_for(["exec", api, "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"])
            docker("exec", api, "python", "/opt/forge/check_db.py")
            wait_for(["exec", db, "psql", "-U", "bipme", "-d", "bipme_demo", "-v", "ON_ERROR_STOP=1", "-c", "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM procrastinate_workers) THEN RAISE EXCEPTION 'worker pending'; END IF; END $$;"])
            # DB failure must fail readiness, while cheap API liveness remains healthy.
            docker("stop", "-t", "120", worker)
            docker("stop", "-t", "120", db)
            assert docker("exec", api, "python", "/opt/forge/check_db.py", check=False).returncode != 0
            docker("exec", api, "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')")
            docker("start", db)
            wait_for(["exec", api, "python", "/opt/forge/check_db.py"])
            docker("start", worker)
            print("Forge database smoke passed: non-root PG17, repeated migration, readiness, backup/restore, persistence, worker registration.")
            print(docker("stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}} {{.MemUsage}}", api, worker, db).stdout)
        finally:
            docker("rm", "-f", api, worker, db, check=False)
            docker("volume", "rm", volume, check=False)
            docker("network", "rm", network, check=False)


if __name__ == "__main__":
    main()
