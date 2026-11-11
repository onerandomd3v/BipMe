"""Disposable Docker smoke of the real frontend image with Forge configuration."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
STUB = '''
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"path": self.path, "headers": dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "__Host-bipme_session=synthetic; Secure; HttpOnly; Path=/; SameSite=Lax")
        self.send_header("Cache-Control", "public")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
    do_POST = do_GET
HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
'''


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True).stdout.strip()


def main():
    suffix = uuid.uuid4().hex[:10]
    network, api, web = (f"forge-{name}-{suffix}" for name in ("net", "api", "web"))
    image = os.getenv("BIPME_WEB_SMOKE_IMAGE", "bipme-forge-web:test")
    with tempfile.TemporaryDirectory() as directory:
        stub = Path(directory) / "stub.py"
        stub.write_text(STUB)
        try:
            docker("network", "create", network)
            docker("run", "-d", "--name", api, "--network", network,
                   "--network-alias", "api.team17.svc.cluster.local",
                   "--mount", f"type=bind,src={stub},dst=/stub.py,readonly",
                   "python:3.13-alpine", "python", "/stub.py")
            docker("run", "-d", "--name", web, "--network", network,
                   "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                   "--memory=96m", "--cpus=0.2",
                   "--tmpfs", "/tmp:uid=101,gid=101,size=16777216",
                   "--tmpfs", "/etc/nginx/conf.d:uid=101,gid=101,size=8388608",
                   "-p", "127.0.0.1::8080", "-e", "BIPME_API_UPSTREAM=http://api:8000",
                   "--mount", f"type=bind,src={ROOT / 'nginx.conf'},dst=/etc/nginx/templates/default.conf.template,readonly",
                   "--mount", f"type=bind,src={ROOT / 'proxy.conf'},dst=/etc/nginx/templates/bipme-api-proxy.conf.template,readonly",
                   image)
            port = docker("port", web, "8080/tcp").rsplit(":", 1)[1]
            base = f"http://127.0.0.1:{port}"
            for attempt in range(60):
                try:
                    with urllib.request.urlopen(base + "/healthz", timeout=2) as response:
                        assert response.read() == b"ok\n"
                    break
                except (urllib.error.URLError, TimeoutError):
                    if attempt == 59:
                        raise
                    time.sleep(1)
            for path in ("/api", "/api/health", "/api/example?value=one%20two"):
                request = urllib.request.Request(base + path, headers={
                    "Host": "untrusted.example:9999", "X-Forwarded-Host": "evil.example",
                    "X-Forwarded-Proto": "http", "X-Forwarded-Port": "9999",
                    "X-Forwarded-For": "203.0.113.99", "Forwarded": "host=evil.example;proto=http",
                    "Cookie": "__Host-bipme_session=synthetic", "X-CSRF-Token": "synthetic-csrf",
                    "Origin": "https://team17.xtradot.co",
                })
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.load(response)
                    assert response.headers["Cache-Control"] == "private, no-store"
                    assert "Secure; HttpOnly; Path=/; SameSite=Lax" in response.headers["Set-Cookie"]
                    assert response.headers.get("X-Content-Type-Options") == "nosniff"
                assert payload["path"] == path
                headers = {k.lower(): v for k, v in payload["headers"].items()}
                assert headers["host"] == headers["x-forwarded-host"] == "team17.xtradot.co"
                assert headers["x-forwarded-proto"] == "https"
                assert headers["x-forwarded-port"] == "443"
                assert headers["x-forwarded-for"] != "203.0.113.99"
                assert "forwarded" not in headers
                assert headers["cookie"] == "__Host-bipme_session=synthetic"
                assert headers["x-csrf-token"] == "synthetic-csrf"
                assert headers["origin"] == "https://team17.xtradot.co"
            # Read origins are preserved; mutations require the exact configured origin.
            with urllib.request.urlopen(urllib.request.Request(base + "/api/health", headers={"Origin": "https://evil.example"})) as response:
                assert json.load(response)["headers"]["Origin"] == "https://evil.example"
            for origin in ("https://evil.example", "null", ""):
                request = urllib.request.Request(base + "/api/auth/logout", data=b"{}", headers={"Origin": origin})
                try:
                    urllib.request.urlopen(request)
                    raise AssertionError("foreign or missing Origin accepted")
                except urllib.error.HTTPError as error:
                    assert error.code == 403
            with urllib.request.urlopen(urllib.request.Request(base + "/api/auth/logout", data=b"{}", headers={"Origin": "https://team17.xtradot.co"})) as response:
                assert response.status == 200
            with urllib.request.urlopen(base + "/deep/link") as response:
                assert b"<html" in response.read().lower()
            print("Forge proxy smoke passed: DNS, URI, spoofed headers, cookies, CSRF, origin, SPA.")
            print(docker("stats", "--no-stream", "--format", "{{.CPUPerc}} {{.MemUsage}}", web))
        finally:
            docker("rm", "-f", web, api, check=False)
            docker("network", "rm", network, check=False)


if __name__ == "__main__":
    main()
