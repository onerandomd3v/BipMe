"""Fail-closed configuration for private sessions and optional X OAuth."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID


def _parse_bool(value: str | None, default: bool) -> bool | None:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _configured_creator_id(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return None


def _safe_origin(value: str | None, *, production: bool) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        port = parsed.port
        if (
            parsed.scheme not in ({"https"} if production else {"https", "http"})
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
            or (parsed.scheme == "http" and (production or not loopback))
        ):
            return None
        return f"{parsed.scheme}://{parsed.netloc}"
    except ValueError:
        return None


def _safe_callback_uri(value: str | None, *, production: bool) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        port = parsed.port
        if (
            parsed.scheme not in ({"https"} if production else {"https", "http"})
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.startswith("/")
            or parsed.path.startswith("//")
            or parsed.query
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
            or (parsed.scheme == "http" and (production or not loopback))
        ):
            return None
        return value
    except ValueError:
        return None


@dataclass(frozen=True)
class AuthSettings:
    """Runtime configuration; secrets are read only from server environment."""

    environment: str
    creator_id: UUID | None
    private_login_secret: str | None
    session_lifetime_seconds: int
    cookie_secure: bool
    app_origin: str | None
    x_oauth_enabled: bool
    x_client_id: str | None
    x_client_secret: str | None
    x_redirect_uri: str | None
    x_allowed_user_id: str | None
    token_encryption_keys: Mapping[str, str]
    active_token_key_version: str | None

    @property
    def session_storage_ready(self) -> bool:
        return bool(
            self.creator_id
            and self.session_lifetime_seconds > 0
            and (self.environment != "production" or self.cookie_secure)
        )

    @property
    def private_login_ready(self) -> bool:
        return bool(
            self.session_storage_ready
            and self.private_login_secret
            and len(self.private_login_secret.encode("utf-8")) >= 32
        )

    @property
    def token_encryption_ready(self) -> bool:
        return bool(
            self.active_token_key_version
            and self.active_token_key_version in self.token_encryption_keys
        )

    @classmethod
    def from_environment(cls) -> AuthSettings:
        environment = os.getenv("BIPME_ENVIRONMENT", "development").strip().lower()
        production = environment == "production"
        secure_setting = _parse_bool(os.getenv("BIPME_AUTH_COOKIE_SECURE"), production)
        cookie_secure = secure_setting is True
        private_secret = os.getenv("BIPME_PRIVATE_LOGIN_SECRET")

        keys: dict[str, str] = {}
        raw_keys = os.getenv("BIPME_TOKEN_ENCRYPTION_KEYS")
        if raw_keys:
            try:
                parsed: object = json.loads(raw_keys)
                if isinstance(parsed, dict) and all(
                    isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
                ):
                    keys = parsed
            except (json.JSONDecodeError, TypeError):
                keys = {}

        allowed_id = os.getenv("BIPME_X_ALLOWED_USER_ID")
        if allowed_id and not allowed_id.isdigit():
            allowed_id = None

        redirect_uri = _safe_callback_uri(os.getenv("BIPME_X_REDIRECT_URI"), production=production)
        app_origin = _safe_origin(os.getenv("BIPME_APP_ORIGIN"), production=production)
        requested_oauth = _parse_bool(os.getenv("BIPME_X_OAUTH_ENABLED"), False) is True
        client_id = os.getenv("BIPME_X_CLIENT_ID") or None
        client_secret = os.getenv("BIPME_X_CLIENT_SECRET") or None
        active_key_version = os.getenv("BIPME_ACTIVE_TOKEN_KEY_VERSION") or None

        oauth_ready = bool(
            requested_oauth
            and client_id
            and client_secret
            and redirect_uri
            and app_origin
            and allowed_id
            and active_key_version
            and active_key_version in keys
            and _configured_creator_id(os.getenv("BIPME_CREATOR_ID"))
            and (not production or cookie_secure)
        )

        ttl_value = os.getenv("BIPME_SESSION_LIFETIME_SECONDS", "43200")
        try:
            lifetime = int(ttl_value)
        except ValueError:
            lifetime = 0
        if not 300 <= lifetime <= 2_592_000:
            lifetime = 0

        return cls(
            environment=environment,
            creator_id=_configured_creator_id(os.getenv("BIPME_CREATOR_ID")),
            private_login_secret=private_secret,
            session_lifetime_seconds=lifetime,
            cookie_secure=cookie_secure,
            app_origin=app_origin,
            x_oauth_enabled=oauth_ready,
            x_client_id=client_id,
            x_client_secret=client_secret,
            x_redirect_uri=redirect_uri,
            x_allowed_user_id=allowed_id,
            token_encryption_keys=keys,
            active_token_key_version=active_key_version,
        )

    @property
    def session_cookie_name(self) -> str:
        return "__Host-bipme_session" if self.cookie_secure else "bipme_session"

    @property
    def oauth_cookie_name(self) -> str:
        return "__Host-bipme_oauth_browser" if self.cookie_secure else "bipme_oauth_browser"


def validate_return_path(value: str, *, max_length: int = 2048) -> str:
    """Accept only a same-origin absolute path; reject ambiguous/open redirects."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_length
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError("invalid return path")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path.startswith("//"):
        raise ValueError("invalid return path")
    return value
