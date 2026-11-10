"""Check that service environment examples cover owned settings safely."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_EXAMPLE = ROOT / "apps/api/.env.example"
WEB_EXAMPLE = ROOT / "apps/web/.env.example"
BREV_EXAMPLE = ROOT / "infra/brev-embedding/.env.example"
ENV_NAME = re.compile(r"\b(?:BIPME_[A-Z0-9_]+|GROQ_API_KEY)\b")
ASSIGNMENT = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=")
VITE_REFERENCE = re.compile(r"import\.meta\.env\.(VITE_[A-Z0-9_]+)")
WEB_SECRET = re.compile(
    r"(?:DATABASE|DB_URL|SECRET|TOKEN|CREDENTIAL|GROQ|X_CLIENT)",
    re.IGNORECASE,
)


def names_in_example(path: Path) -> set[str]:
    """Return environment variable assignments from a service example."""
    return {
        match.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := ASSIGNMENT.match(line))
    }


def main() -> int:
    """Validate ownership and safety rules for service environment examples."""
    errors: list[str] = []
    if (ROOT / ".env.example").exists():
        errors.append("Remove the root .env.example; configuration belongs to a service.")
    for local_file in ("apps/api/.env", "infra/brev-embedding/.env"):
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", local_file],
            cwd=ROOT,
            check=False,
        )
        if ignored.returncode != 0:
            errors.append(f"Local environment file is not ignored by Git: {local_file}")

    for required in (API_EXAMPLE, BREV_EXAMPLE):
        if not required.is_file():
            errors.append(f"Missing service example: {required.relative_to(ROOT)}")
    if errors:
        return fail(errors)

    api_names = names_in_example(API_EXAMPLE)
    runtime_names: set[str] = set()
    for base in (ROOT / "apps/api/src", ROOT / "apps/api/alembic"):
        for source in base.rglob("*.py"):
            runtime_names.update(ENV_NAME.findall(source.read_text(encoding="utf-8")))
    missing_api = sorted(runtime_names - api_names)
    if missing_api:
        errors.append("API example is missing consumed settings: " + ", ".join(missing_api))

    web_sources = (ROOT / "apps/web/src", ROOT / "apps/web")
    web_names: set[str] = set()
    for base in web_sources:
        for source in (*base.rglob("*.ts"), *base.rglob("*.tsx")):
            if "node_modules" not in source.parts and "dist" not in source.parts:
                web_names.update(VITE_REFERENCE.findall(source.read_text(encoding="utf-8")))
    if WEB_EXAMPLE.exists():
        web_example_text = WEB_EXAMPLE.read_text(encoding="utf-8")
        web_example_names = names_in_example(WEB_EXAMPLE)
        if WEB_SECRET.search(web_example_text):
            errors.append("Web example contains a server-side secret or credential name.")
        if web_names != web_example_names:
            errors.append(
                "Web example variables must match consumed VITE_ settings; "
                f"consumed={sorted(web_names)}, documented={sorted(web_example_names)}"
            )
    elif web_names:
        errors.append("Web consumes VITE_ settings but apps/web/.env.example is missing.")

    brev_names = names_in_example(BREV_EXAMPLE)
    allowed_brev_names = {"BIPME_EMBEDDING_TOKEN", "LOG_LEVEL"}
    missing_brev = sorted(allowed_brev_names - brev_names)
    if missing_brev:
        errors.append("Brev example is missing settings: " + ", ".join(missing_brev))
    unexpected_brev = sorted(brev_names - allowed_brev_names)
    if unexpected_brev:
        errors.append("Brev example has unowned settings: " + ", ".join(unexpected_brev))
    brev_compose = (ROOT / "infra/brev-embedding/compose.yaml").read_text(encoding="utf-8")
    if "BIPME_EMBEDDING_TOKEN: ${BIPME_EMBEDDING_TOKEN:?" not in brev_compose:
        errors.append("Brev Compose must require the private inference token.")
    if "LOG_LEVEL: ${LOG_LEVEL:-WARNING}" not in brev_compose:
        errors.append("Brev Compose must pass the documented LOG_LEVEL default.")

    if errors:
        return fail(errors)
    print(
        "Environment boundaries valid: "
        f"{len(api_names)} API settings, {len(web_names)} web settings, "
        f"{len(brev_names)} Brev settings."
    )
    return 0


def fail(errors: list[str]) -> int:
    """Print validation errors and return a failing process status."""
    print("Environment boundary check failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
