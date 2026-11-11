"""Exercise a built frontend image against a local mock API."""

from __future__ import annotations

import http.server
import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
IMAGE = os.environ.get("BIPME_WEB_SMOKE_IMAGE", "bipme-web:ci")


class MockApi(http.server.BaseHTTPRequestHandler):
    """Capture proxy requests and provide response cases for the smoke test."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self.respond()

    def do_POST(self) -> None:
        self.respond()

    def do_PUT(self) -> None:
        self.respond()

    def do_PATCH(self) -> None:
        self.respond()

    def do_DELETE(self) -> None:
        self.respond()

    def respond(self) -> None:
        if self.path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk in (b"first", b"second"):
                self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
                self.wfile.flush()
                time.sleep(1)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return

        body_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(body_length)
        payload = json.dumps(
            {
                "method": self.command,
                "path": self.path,
                "body": body.decode("utf-8"),
                "cookie": self.headers.get("Cookie"),
                "csrf": self.headers.get("X-CSRF-Token"),
                "authorization": self.headers.get("Authorization"),
                "origin": self.headers.get("Origin"),
                "forwarded_proto": self.headers.get("X-Forwarded-Proto"),
            }
        ).encode()
        status = 401 if self.path.startswith("/api/unauthorized") else 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Set-Cookie", "bipme_session=mock; HttpOnly; SameSite=Lax; Path=/")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )
    return result.stdout.strip() if capture else ""


def fetch(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None):
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        return urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as response:
        return response


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def print_container_logs(container_name: str) -> None:
    result = subprocess.run(
        ["docker", "logs", container_name],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(f"{container_name} stdout:\n{result.stdout}")
    if result.stderr:
        print(f"{container_name} stderr:\n{result.stderr}")


def main() -> None:
    with socket.socket() as socket_probe:
        socket_probe.bind(("127.0.0.1", 0))
        web_port = socket_probe.getsockname()[1]

    container_name = f"bipme-web-smoke-{os.getpid()}"
    api_name = f"{container_name}-api"
    network_name = f"{container_name}-network"
    completed = False
    try:
        user = run("docker", "image", "inspect", "--format", "{{.Config.User}}", IMAGE, capture=True)
        require(user not in ("", "0", "root"), f"Image does not run as a non-root user: {user!r}")
        environment = run(
            "docker", "image", "inspect", "--format", "{{json .Config.Env}}", IMAGE, capture=True
        )
        require(
            not re.search(r"(?i)(DATABASE_URL|GROQ_API_KEY|TOKEN_ENCRYPTION|X_CLIENT_SECRET)", environment),
            "A backend secret setting is present in the image environment.",
        )
        require(
            not re.search(r"(?:^|[\", ])BIPME_API_UPSTREAM=", environment),
            "The runtime API upstream was baked into the image.",
        )
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        require("**/.env" in dockerignore and "**/.env.*" in dockerignore, "Docker build context does not exclude service environment files.")

        run("docker", "network", "create", network_name)
        run(
            "docker",
            "run",
            "--detach",
            "--name",
            api_name,
            "--network",
            network_name,
            "--network-alias",
            "bipme-mock-api",
            "python:3.13-alpine",
            "sleep",
            "300",
        )
        run("docker", "cp", str(Path(__file__)), f"{api_name}:/tmp/container-smoke.py")
        run(
            "docker",
            "exec",
            "--detach",
            "--env",
            "BIPME_CONTAINER_MOCK_API=1",
            api_name,
            "python",
            "/tmp/container-smoke.py",
        )
        run(
            "docker",
            "run",
            "--detach",
            "--name",
            container_name,
            "--network",
            network_name,
            "--publish",
            f"127.0.0.1:{web_port}:8080",
            "--env",
            "BIPME_API_UPSTREAM=http://bipme-mock-api:8000",
            IMAGE,
        )
        base = f"http://127.0.0.1:{web_port}"
        health_ready = False
        for _ in range(40):
            try:
                response = fetch(f"{base}/healthz")
            except (urllib.error.URLError, TimeoutError, ConnectionResetError):
                time.sleep(0.25)
                continue
            if response.status == 200:
                health_ready = True
                break
            time.sleep(0.25)
        require(health_ready, "Health endpoint did not respond successfully.")
        require(response.read() == b"ok\n", "Health endpoint body was unexpected.")
        for _ in range(20):
            health = run(
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                container_name,
                capture=True,
            )
            if health == "healthy":
                break
            time.sleep(0.25)
        require(health == "healthy", "Docker health check did not become healthy.")

        for _ in range(40):
            api_ready = fetch(f"{base}/api/ready")
            if api_ready.status == 200:
                break
            time.sleep(0.25)
        require(api_ready.status == 200, "The API mock was not reachable through the shared Docker network.")

        root = fetch(base)
        html = root.read()
        require(root.status == 200 and b'<div id="root"></div>' in html, "Frontend root did not render the Vite shell.")
        require("no-store" in root.headers.get("Cache-Control", ""), "index.html can be cached aggressively.")
        require(root.headers.get("X-Content-Type-Options") == "nosniff", "Static security headers are missing.")
        deep_link = fetch(f"{base}/creator/history")
        require(deep_link.status == 200 and deep_link.read() == html, "SPA deep-link refresh did not return index.html.")

        asset = re.search(rb"(?:src|href)=\"(/assets/[^\"]+\.(?:js|css))\"", html)
        require(asset is not None, "Built HTML did not reference a Vite static asset.")
        asset_response = fetch(base + asset.group(1).decode())
        require(asset_response.status == 200, "A built static asset was not delivered.")
        require("immutable" in asset_response.headers.get("Cache-Control", ""), "Hashed assets lack immutable caching.")
        asset_content = asset_response.read()
        require(
            not re.search(rb"(GROQ_API_KEY|BIPME_X_CLIENT_SECRET|BIPME_DATABASE_URL|BIPME_TOKEN_ENCRYPTION_KEYS)", html + asset_content),
            "A backend secret setting was included in the browser bundle.",
        )

        headers = {
            "Authorization": "Bearer mock-value",
            "Cookie": "bipme_session=request-cookie",
            "Content-Type": "application/json",
            "Origin": "https://bipme.example",
            "X-CSRF-Token": "mock-csrf-value",
            "X-Forwarded-Proto": "https",
        }
        api = fetch(
            f"{base}/api/echo?cursor=next%2Fitem&limit=2",
            method="POST",
            headers=headers,
            data=b'{"message":"hello"}',
        )
        api_data = json.loads(api.read())
        require(api.status == 200, "API proxy changed a successful status.")
        require(api_data["method"] == "POST", "API proxy changed the request method.")
        require(api_data["path"] == "/api/echo?cursor=next%2Fitem&limit=2", "API proxy changed path or query string.")
        require(api_data["body"] == '{"message":"hello"}', "API proxy changed the request body.")
        require(api_data["cookie"] == headers["Cookie"], "API proxy did not forward the session cookie.")
        require(api_data["csrf"] == headers["X-CSRF-Token"], "API proxy did not forward the CSRF header.")
        require(api_data["authorization"] == headers["Authorization"], "API proxy did not forward Authorization.")
        require(api_data["origin"] == headers["Origin"], "API proxy did not forward Origin for CSRF checks.")
        require(api_data["forwarded_proto"] == "https", "API proxy did not preserve the trusted public HTTPS scheme.")
        require(api.headers.get("Set-Cookie", "").startswith("bipme_session=mock;"), "API Set-Cookie was not preserved.")
        require("no-store" in api.headers.get("Cache-Control", ""), "API responses are not marked non-cacheable.")

        put = fetch(f"{base}/api/echo?method=put", method="PUT", headers=headers, data=b"put-body")
        patch = fetch(f"{base}/api/echo?method=patch", method="PATCH", headers=headers, data=b"patch-body")
        delete = fetch(f"{base}/api/echo?method=delete", method="DELETE", headers=headers, data=b"delete-body")
        require([json.loads(result.read())["method"] for result in (put, patch, delete)] == ["PUT", "PATCH", "DELETE"], "API proxy changed an HTTP method.")

        unauthorized = fetch(f"{base}/api/unauthorized")
        require(unauthorized.status == 401, "API authentication status was not preserved.")
        require("no-store" in unauthorized.headers.get("Cache-Control", ""), "Authenticated API errors can be cached.")

        stream = fetch(f"{base}/api/stream")
        started = time.perf_counter()
        first_chunk = stream.read(5)
        elapsed = time.perf_counter() - started
        require(first_chunk == b"first" and elapsed < 0.8, "API streaming response was buffered by the proxy.")

        print("Frontend container smoke checks passed.")
        completed = True
    finally:
        if not completed:
            print_container_logs(container_name)
            print_container_logs(api_name)
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["docker", "rm", "--force", api_name],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["docker", "network", "rm", network_name],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    if os.environ.get("BIPME_CONTAINER_MOCK_API") == "1":
        http.server.ThreadingHTTPServer(("0.0.0.0", 8000), MockApi).serve_forever()
    else:
        main()
