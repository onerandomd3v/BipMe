"""Mock-backed tests for private sessions and the optional X OAuth lifecycle."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bipme.api.app import create_app
from bipme.api.auth import get_token_cipher, get_x_oauth_provider, rotate_connection_encryption_keys
from bipme.api.dependencies import get_db_session
from bipme.auth.crypto import TokenCipher, secret_digest
from bipme.integrations.x_oauth import (
    READ_ONLY_X_SCOPES,
    HttpXOAuthProvider,
    XOAuthProviderError,
    XOAuthTokens,
    XUser,
)
from bipme.persistence.base import Base, EncryptedTokenEnvelope
from bipme.persistence.models import (
    Creator,
    CreatorPlatformIdentity,
    CreatorSession,
    OAuthAuthorizationTransaction,
    XAccountConnection,
)

CREATOR_ID = UUID("11111111-1111-4111-8111-111111111111")
LOGIN_SECRET = "synthetic-private-login-secret-with-entropy"
FERNET_KEY = Fernet.generate_key().decode("ascii")


class FakeXOAuthProvider:
    def __init__(self) -> None:
        self.user_id = "987654321"
        self.username = "synthetic_creator"
        self.tokens = XOAuthTokens(
            access_token="synthetic-access-token",
            refresh_token="synthetic-refresh-token",
            expires_in=7200,
            scopes=READ_ONLY_X_SCOPES,
        )
        self.refreshed = XOAuthTokens(
            access_token="synthetic-refreshed-access",
            refresh_token="synthetic-refreshed-refresh",
            expires_in=7200,
            scopes=READ_ONLY_X_SCOPES,
        )
        self.exchange_calls: list[tuple[str, str, str]] = []
        self.refresh_calls: list[str] = []
        self.revocations: list[tuple[str, str]] = []
        self.refresh_error: XOAuthProviderError | None = None

    def authorization_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        return "https://x.com/i/oauth2/authorize?" + urlencode(
            {
                "response_type": "code",
                "client_id": "synthetic-client-id",
                "redirect_uri": redirect_uri,
                "scope": " ".join(READ_ONLY_X_SCOPES),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )

    def exchange_code(self, *, code: str, verifier: str, redirect_uri: str) -> XOAuthTokens:
        self.exchange_calls.append((code, verifier, redirect_uri))
        return self.tokens

    def current_user(self, _access_token: str) -> XUser:
        return XUser(self.user_id, self.username)

    def refresh(self, refresh_token: str) -> XOAuthTokens:
        self.refresh_calls.append(refresh_token)
        if self.refresh_error is not None:
            raise self.refresh_error
        return self.refreshed

    def revoke(self, token: str, *, token_type_hint: str) -> None:
        self.revocations.append((token, token_type_hint))


@pytest.fixture
def auth_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BIPME_ENVIRONMENT", "test")
    monkeypatch.setenv("BIPME_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_PRIVATE_LOGIN_SECRET", LOGIN_SECRET)
    monkeypatch.setenv("BIPME_SESSION_LIFETIME_SECONDS", "3600")
    monkeypatch.setenv("BIPME_AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("BIPME_APP_ORIGIN", "http://127.0.0.1:5173")
    monkeypatch.setenv("BIPME_X_OAUTH_ENABLED", "true")
    monkeypatch.setenv("BIPME_X_CLIENT_ID", "synthetic-client-id")
    monkeypatch.setenv("BIPME_X_CLIENT_SECRET", "synthetic-client-secret")
    monkeypatch.setenv("BIPME_X_ALLOWED_USER_ID", "987654321")
    monkeypatch.setenv("BIPME_X_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/x/callback")
    monkeypatch.setenv("BIPME_TOKEN_ENCRYPTION_KEYS", json.dumps({"v1": FERNET_KEY}))
    monkeypatch.setenv("BIPME_ACTIVE_TOKEN_KEY_VERSION", "v1")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def register_postgres_check_functions(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function(
            "decode",
            2,
            lambda value, encoding: bytes.fromhex(value) if encoding == "hex" else b"",
        )
        dbapi_connection.create_function(
            "substring",
            3,
            lambda value, start, length: value[start - 1 : start - 1 + length],
        )
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    relevant_tables = [
        Creator.__table__,
        CreatorPlatformIdentity.__table__,
        XAccountConnection.__table__,
        CreatorSession.__table__,
        OAuthAuthorizationTransaction.__table__,
    ]
    pg_only_constraints: list[tuple[object, CheckConstraint]] = []
    for table in relevant_tables:
        for constraint in list(table.constraints):
            if isinstance(constraint, CheckConstraint) and "substring(" in str(constraint.sqltext):
                pg_only_constraints.append((table, constraint))
                table.constraints.remove(constraint)
    try:
        Base.metadata.create_all(engine, tables=relevant_tables)
    finally:
        for table, constraint in pg_only_constraints:
            table.constraints.add(constraint)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(Creator(id=CREATOR_ID))
        db.commit()

    app = create_app()
    app.state.auth_session_factory = factory

    def db_dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = db_dependency
    provider = FakeXOAuthProvider()
    cipher = TokenCipher({"v1": FERNET_KEY}, "v1")
    app.dependency_overrides[get_x_oauth_provider] = lambda: provider
    app.dependency_overrides[get_token_cipher] = lambda: cipher
    return TestClient(app, follow_redirects=False), factory, provider, cipher, engine


def start_authorization(
    client: TestClient, return_to: str = "/settings?tab=account"
) -> dict[str, str]:
    response = client.get("/api/auth/x/authorize", params={"return_to": return_to})
    assert response.status_code == 303
    authorization_url = response.headers["location"]
    query = parse_qs(urlsplit(authorization_url).query)
    return {key: values[0] for key, values in query.items()}


def complete_authorization(client: TestClient, query: dict[str, str]):
    return client.get(
        "/api/auth/x/callback",
        params={"state": query["state"], "code": "synthetic-code"},
    )


def test_successful_pkce_allowlisted_x_login_sets_server_session(auth_runtime) -> None:
    client, factory, provider, cipher, _engine = auth_runtime
    query = start_authorization(client)
    state = query["state"]
    assert len(state) >= 40
    assert query["code_challenge_method"] == "S256"
    assert query["scope"] == "tweet.read users.read offline.access"
    response = complete_authorization(client, query)
    assert response.status_code == 303
    assert response.headers["location"] == (
        "http://127.0.0.1:5173/settings?tab=account&x_connection=connected"
    )
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(cookie for cookie in cookies if "bipme_session=" in cookie)
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert provider.exchange_calls[0][0] == "synthetic-code"
    assert provider.exchange_calls[0][2] == "http://127.0.0.1:8000/api/auth/x/callback"
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(provider.exchange_calls[0][1].encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert query["code_challenge"] == expected_challenge

    with factory() as db:
        connection = db.scalar(select(XAccountConnection))
        session_record = db.scalar(select(CreatorSession))
        transaction = db.scalar(select(OAuthAuthorizationTransaction))
        assert connection is not None
        assert connection.state == "connected"
        assert connection.encrypted_access_token is not None
        assert connection.encrypted_access_token.startswith(EncryptedTokenEnvelope.prefix)
        assert cipher.decrypt(connection.encrypted_access_token, connection.key_version) == (
            "synthetic-access-token"
        )
        assert session_record is not None
        assert session_record.creator_id == CREATOR_ID
        assert session_record.auth_method == "x_oauth"
        assert session_record.token_hash not in response.headers["set-cookie"]
        assert transaction is not None and transaction.consumed_at is not None

    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["csrf_token"]


def test_invalid_and_replayed_state_are_rejected_before_provider_exchange(auth_runtime) -> None:
    client, _factory, provider, _cipher, _engine = auth_runtime
    query = start_authorization(client)
    invalid = client.get(
        "/api/auth/x/callback", params={"state": "wrong-state", "code": "synthetic-code"}
    )
    assert invalid.status_code == 400
    assert provider.exchange_calls == []

    first = complete_authorization(client, query)
    assert first.status_code == 303
    replay = complete_authorization(client, query)
    assert replay.status_code == 400
    assert len(provider.exchange_calls) == 1


def test_expired_state_and_wrong_browser_binding_are_rejected(auth_runtime) -> None:
    client, factory, provider, _cipher, _engine = auth_runtime
    query = start_authorization(client)
    with factory() as db:
        record = db.scalar(select(OAuthAuthorizationTransaction))
        assert record is not None
        record.created_at = datetime.now(UTC) - timedelta(minutes=11)
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    expired = complete_authorization(client, query)
    assert expired.status_code == 400
    assert provider.exchange_calls == []

    second_query = start_authorization(client)
    client.cookies.clear()
    client.cookies.set("bipme_oauth_browser", "wrong-browser", path="/api/auth/x/callback")
    mismatch = complete_authorization(client, second_query)
    assert mismatch.status_code == 400
    assert provider.exchange_calls == []


def test_wrong_account_is_rejected_and_received_tokens_are_revoked(auth_runtime) -> None:
    client, factory, provider, _cipher, _engine = auth_runtime
    provider.user_id = "123456789"
    query = start_authorization(client)
    response = complete_authorization(client, query)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "x_account_not_allowed"
    assert provider.revocations == [
        ("synthetic-access-token", "access_token"),
        ("synthetic-refresh-token", "refresh_token"),
    ]
    with factory() as db:
        assert db.scalar(select(CreatorPlatformIdentity)) is None
        assert db.scalar(select(XAccountConnection)) is None
        assert db.scalar(select(CreatorSession)) is None


def test_denied_consent_consumes_state_without_exchanging_code(auth_runtime) -> None:
    client, factory, provider, _cipher, _engine = auth_runtime
    query = start_authorization(client)
    response = client.get(
        "/api/auth/x/callback",
        params={"state": query["state"], "error": "access_denied"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "x_consent_denied"
    assert provider.exchange_calls == []
    with factory() as db:
        transaction = db.scalar(select(OAuthAuthorizationTransaction))
        assert transaction is not None and transaction.consumed_at is not None


@pytest.mark.parametrize(
    "return_to", ["//attacker.example", "https://attacker.example", r"/\\evil"]
)
def test_external_and_ambiguous_return_locations_are_rejected(auth_runtime, return_to: str) -> None:
    client, _factory, provider, _cipher, _engine = auth_runtime
    response = client.get("/api/auth/x/authorize", params={"return_to": return_to})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_return_url"
    assert provider.exchange_calls == []


def test_private_archive_session_does_not_require_x_oauth(auth_runtime, monkeypatch) -> None:
    client, factory, _provider, _cipher, _engine = auth_runtime
    monkeypatch.setenv("BIPME_X_OAUTH_ENABLED", "false")
    response = client.post("/api/auth/private/session", json={"secret": LOGIN_SECRET})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.json()["csrf_token"]
    assert client.get("/api/auth/session").status_code == 200
    assert client.get("/api/auth/x/connection").json() == {
        "connected": False,
        "state": None,
        "scopes": [],
        "expires_at": None,
    }
    with factory() as db:
        record = db.scalar(select(CreatorSession))
        assert record is not None and record.auth_method == "private_secret"


def test_session_expiry_revocation_and_csrf_protection(auth_runtime) -> None:
    client, factory, _provider, _cipher, _engine = auth_runtime
    login = client.post("/api/auth/private/session", json={"secret": LOGIN_SECRET})
    assert login.status_code == 200
    csrf_token = client.get("/api/auth/session").json()["csrf_token"]
    missing_csrf = client.post("/api/auth/logout")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_validation_failed"

    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert logout.status_code == 204
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert client.get("/api/auth/session").status_code == 401

    login_again = client.post("/api/auth/private/session", json={"secret": LOGIN_SECRET})
    assert login_again.status_code == 200
    with factory() as db:
        record = db.scalar(select(CreatorSession).where(CreatorSession.revoked_at.is_(None)))
        assert record is not None
        record.created_at = datetime.now(UTC) - timedelta(hours=2)
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/auth/session").status_code == 401


def test_analysis_mutations_require_csrf_even_with_a_valid_session(auth_runtime) -> None:
    client, _factory, _provider, _cipher, _engine = auth_runtime
    assert (
        client.post("/api/auth/private/session", json={"secret": LOGIN_SECRET}).status_code == 200
    )
    response = client.post(
        "/api/v1/creators/me/draft-assessments",
        headers={"Idempotency-Key": "synthetic-assessment"},
        json={"text": "A synthetic draft for auth coverage."},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_validation_failed"


def test_refresh_and_disconnect_never_return_tokens(auth_runtime) -> None:
    client, factory, provider, cipher, _engine = auth_runtime
    query = start_authorization(client)
    assert complete_authorization(client, query).status_code == 303
    csrf_token = client.get("/api/auth/session").json()["csrf_token"]
    refreshed = client.post("/api/auth/x/refresh", headers={"X-CSRF-Token": csrf_token})
    assert refreshed.status_code == 200
    assert "synthetic-refreshed-access" not in refreshed.text
    assert "synthetic-refreshed-refresh" not in refreshed.text
    assert provider.refresh_calls == ["synthetic-refresh-token"]

    with factory() as db:
        connection = db.scalar(select(XAccountConnection))
        assert connection is not None
        assert cipher.decrypt(connection.encrypted_access_token, connection.key_version) == (
            "synthetic-refreshed-access"
        )

    disconnected = client.post("/api/auth/x/disconnect", headers={"X-CSRF-Token": csrf_token})
    assert disconnected.status_code == 204
    assert "synthetic-" not in disconnected.text
    with factory() as db:
        connection = db.scalar(select(XAccountConnection))
        assert connection is not None
        assert connection.state == "revoked"
        assert connection.encrypted_access_token is None
        assert connection.encrypted_refresh_token is None


def test_revoked_refresh_token_requires_reauthorization_and_clears_secrets(auth_runtime) -> None:
    client, factory, provider, _cipher, _engine = auth_runtime
    query = start_authorization(client)
    assert complete_authorization(client, query).status_code == 303
    csrf_token = client.get("/api/auth/session").json()["csrf_token"]
    provider.refresh_error = XOAuthProviderError("synthetic", reauth_required=True)
    response = client.post("/api/auth/x/refresh", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "x_reauthorization_required"
    with factory() as db:
        connection = db.scalar(select(XAccountConnection))
        assert connection is not None
        assert connection.state == "reauth_required"
        assert connection.encrypted_access_token is None
        assert connection.encrypted_refresh_token is None


def test_encryption_key_rotation_rewraps_active_connections(auth_runtime, monkeypatch) -> None:
    client, factory, _provider, _old_cipher, _engine = auth_runtime
    query = start_authorization(client)
    assert complete_authorization(client, query).status_code == 303
    second_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv(
        "BIPME_TOKEN_ENCRYPTION_KEYS", json.dumps({"v1": FERNET_KEY, "v2": second_key})
    )
    monkeypatch.setenv("BIPME_ACTIVE_TOKEN_KEY_VERSION", "v2")
    rotated_cipher = TokenCipher({"v1": FERNET_KEY, "v2": second_key}, "v2")
    with factory() as db:
        count = rotate_connection_encryption_keys(db, cipher=rotated_cipher, now=datetime.now(UTC))
        connection = db.scalar(select(XAccountConnection))
        assert count == 1
        assert connection is not None and connection.key_version == "v2"
        assert rotated_cipher.decrypt(connection.encrypted_access_token, "v2") == (
            "synthetic-access-token"
        )


def test_production_cookie_misconfiguration_fails_closed(auth_runtime, monkeypatch) -> None:
    client, _factory, _provider, _cipher, _engine = auth_runtime
    monkeypatch.setenv("BIPME_ENVIRONMENT", "production")
    monkeypatch.setenv("BIPME_AUTH_COOKIE_SECURE", "false")
    response = client.get("/api/auth/session")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_not_configured"


def test_private_login_wrong_secret_does_not_issue_cookie(auth_runtime) -> None:
    client, _factory, _provider, _cipher, _engine = auth_runtime
    response = client.post(
        "/api/auth/private/session", json={"secret": "wrong-private-login-secret-value"}
    )
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_session_token_hash_is_one_way() -> None:
    assert secret_digest("synthetic-cookie") != "synthetic-cookie"
    assert len(secret_digest("synthetic-cookie")) == 64


def test_http_x_oauth_adapter_uses_documented_endpoints_and_never_calls_live_x() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/2/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-access",
                    "refresh_token": "synthetic-refresh",
                    "expires_in": 7200,
                    "scope": "tweet.read users.read offline.access",
                    "token_type": "bearer",
                },
            )
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": "987654321", "username": "test"}})
        if request.url.path == "/2/oauth2/revoke":
            return httpx.Response(200, json={"revoked": True})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    provider = HttpXOAuthProvider(
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
        http_client=client,
    )
    authorization_url = provider.authorization_url(
        state="synthetic-state",
        code_challenge="synthetic-challenge",
        redirect_uri="https://app.test/callback",
    )
    params = parse_qs(urlsplit(authorization_url).query)
    assert params["scope"] == ["tweet.read users.read offline.access"]
    assert params["code_challenge_method"] == ["S256"]

    tokens = provider.exchange_code(
        code="synthetic-code",
        verifier="synthetic-verifier",
        redirect_uri="https://app.test/callback",
    )
    user = provider.current_user(tokens.access_token)
    provider.refresh(tokens.refresh_token or "")
    provider.revoke(tokens.access_token, token_type_hint="access_token")
    assert user == XUser("987654321", "test")
    assert requests[0].url.host == "api.x.com"
    assert requests[0].url.path == "/2/oauth2/token"
    assert b"code_verifier=synthetic-verifier" in requests[0].content
    assert requests[0].headers["authorization"].startswith("Basic ")
    assert requests[1].url.path == "/2/users/me"
    assert requests[1].headers["authorization"] == "Bearer synthetic-access"
    assert requests[2].url.path == "/2/oauth2/token"
    assert b"grant_type=refresh_token" in requests[2].content
    assert requests[3].url.path == "/2/oauth2/revoke"
    assert all(request.url.host == "api.x.com" for request in requests)
    client.close()
