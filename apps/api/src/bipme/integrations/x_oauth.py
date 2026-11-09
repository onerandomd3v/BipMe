"""Replaceable, read-only X OAuth provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

X_AUTHORIZE_ENDPOINT = "https://x.com/i/oauth2/authorize"
X_TOKEN_ENDPOINT = "https://api.x.com/2/oauth2/token"
X_REVOKE_ENDPOINT = "https://api.x.com/2/oauth2/revoke"
X_CURRENT_USER_ENDPOINT = "https://api.x.com/2/users/me"
READ_ONLY_X_SCOPES = ("tweet.read", "users.read", "offline.access")


class XOAuthProviderError(Exception):
    """Provider failure whose message never contains request/response credentials."""

    def __init__(self, message: str, *, reauth_required: bool = False) -> None:
        super().__init__(message)
        self.reauth_required = reauth_required


@dataclass(frozen=True)
class XOAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scopes: tuple[str, ...] | None


@dataclass(frozen=True)
class XUser:
    user_id: str
    username: str | None


class XOAuthProvider(Protocol):
    """Operations required by PKCE login and connection lifecycle."""

    def authorization_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str: ...

    def exchange_code(self, *, code: str, verifier: str, redirect_uri: str) -> XOAuthTokens: ...

    def current_user(self, access_token: str) -> XUser: ...

    def refresh(self, refresh_token: str) -> XOAuthTokens: ...

    def revoke(self, token: str, *, token_type_hint: str) -> None: ...


class HttpXOAuthProvider:
    """HTTP adapter for X OAuth; callers may inject a fake provider in tests."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise XOAuthProviderError("X OAuth is not configured")
        self._client_id = client_id
        self._client_secret = client_secret
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=10.0, follow_redirects=False)

    def authorization_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(READ_ONLY_X_SCOPES),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{X_AUTHORIZE_ENDPOINT}?{query}"

    def exchange_code(self, *, code: str, verifier: str, redirect_uri: str) -> XOAuthTokens:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            }
        )

    def refresh(self, refresh_token: str) -> XOAuthTokens:
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def current_user(self, access_token: str) -> XUser:
        try:
            response = self._http.get(
                X_CURRENT_USER_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            payload: object = response.json()
            if not isinstance(payload, dict):
                raise XOAuthProviderError("X identity lookup failed")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise XOAuthProviderError("X identity lookup failed")
            user_id = data.get("id")
            username = data.get("username")
            if not isinstance(user_id, str) or not user_id.isdigit():
                raise XOAuthProviderError("X identity lookup failed")
            if username is not None and not isinstance(username, str):
                username = None
            return XUser(user_id=user_id, username=username)
        except (httpx.HTTPError, ValueError, TypeError):
            raise XOAuthProviderError("X identity lookup failed") from None

    def revoke(self, token: str, *, token_type_hint: str) -> None:
        if token_type_hint not in {"access_token", "refresh_token"}:
            raise XOAuthProviderError("X token revocation failed")
        try:
            response = self._http.post(
                X_REVOKE_ENDPOINT,
                data={
                    "token": token,
                    "token_type_hint": token_type_hint,
                    "client_id": self._client_id,
                },
                auth=(self._client_id, self._client_secret),
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise XOAuthProviderError("X token revocation failed") from None

    def close(self) -> None:
        """Close the HTTP connection pool when this adapter owns it."""
        if self._owns_client:
            self._http.close()

    def _token_request(self, form: dict[str, str]) -> XOAuthTokens:
        try:
            response = self._http.post(
                X_TOKEN_ENDPOINT,
                data={**form, "client_id": self._client_id},
                auth=(self._client_id, self._client_secret),
            )
            if response.status_code in {400, 401}:
                raise XOAuthProviderError("X token exchange failed", reauth_required=True)
            response.raise_for_status()
            payload: object = response.json()
            if not isinstance(payload, dict):
                raise XOAuthProviderError("X token exchange failed")
            access_token = payload.get("access_token")
            refresh_token = payload.get("refresh_token")
            expires_in = payload.get("expires_in")
            raw_scopes = payload.get("scope")
            if (
                not isinstance(access_token, str)
                or not access_token
                or len(access_token) > 8192
                or (
                    refresh_token is not None
                    and (not isinstance(refresh_token, str) or len(refresh_token) > 8192)
                )
                or isinstance(expires_in, bool)
                or not isinstance(expires_in, int)
                or not 1 <= expires_in <= 15_552_000
            ):
                raise XOAuthProviderError("X token exchange failed")
            scopes = None
            if raw_scopes is not None:
                if not isinstance(raw_scopes, str):
                    raise XOAuthProviderError("X token exchange failed")
                scopes = tuple(sorted(set(raw_scopes.split())))
            return XOAuthTokens(access_token, refresh_token, expires_in, scopes)
        except XOAuthProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise XOAuthProviderError("X token exchange failed") from None
