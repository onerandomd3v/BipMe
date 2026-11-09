"""Private session and optional read-only X OAuth routes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.auth.config import AuthSettings, validate_return_path
from bipme.auth.crypto import TokenCipher, TokenEncryptionError, secret_digest
from bipme.auth.sessions import active_session_by_cookie, create_creator_session
from bipme.integrations.x_oauth import (
    READ_ONLY_X_SCOPES,
    HttpXOAuthProvider,
    XOAuthProvider,
    XOAuthProviderError,
    XOAuthTokens,
)
from bipme.persistence.models import (
    Creator,
    CreatorPlatformIdentity,
    CreatorSession,
    OAuthAuthorizationTransaction,
    XAccountConnection,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
OAUTH_TRANSACTION_TTL = 600
READ_ONLY_SCOPE_SET = frozenset(READ_ONLY_X_SCOPES)


class PrivateLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: str = Field(min_length=32, max_length=512)


class SessionResponse(BaseModel):
    authenticated: bool = True
    csrf_token: str


class XConnectionResponse(BaseModel):
    connected: bool
    state: str | None = None
    scopes: tuple[str, ...] = ()
    expires_at: datetime | None = None


def get_token_cipher() -> TokenCipher:
    """Build an authenticated cipher from server-only key configuration."""
    settings = AuthSettings.from_environment()
    if not settings.token_encryption_ready or settings.active_token_key_version is None:
        raise ApiError(503, "token_encryption_not_configured", "X token protection is unavailable.")
    try:
        return TokenCipher(settings.token_encryption_keys, settings.active_token_key_version)
    except TokenEncryptionError:
        raise ApiError(
            503, "token_encryption_not_configured", "X token protection is unavailable."
        ) from None


def get_x_oauth_provider() -> XOAuthProvider:
    """Return the configured X adapter; tests replace this dependency with a fake."""
    settings = AuthSettings.from_environment()
    if not settings.x_oauth_enabled or not settings.x_client_id or not settings.x_client_secret:
        raise ApiError(503, "x_oauth_not_configured", "X connection is not configured.")
    try:
        return HttpXOAuthProvider(
            client_id=settings.x_client_id,
            client_secret=settings.x_client_secret,
        )
    except XOAuthProviderError:
        raise ApiError(503, "x_oauth_not_configured", "X connection is not configured.") from None


def _require_oauth_settings(settings: AuthSettings) -> tuple[str, str, str, str]:
    if not settings.x_oauth_enabled:
        raise ApiError(503, "x_oauth_not_configured", "X connection is not configured.")
    if not settings.creator_id or not settings.x_allowed_user_id:
        raise ApiError(503, "x_oauth_not_configured", "X connection is not configured.")
    if not settings.x_redirect_uri or not settings.app_origin:
        raise ApiError(503, "x_oauth_not_configured", "X connection is not configured.")
    if not settings.active_token_key_version:
        raise ApiError(503, "x_oauth_not_configured", "X connection is not configured.")
    return (
        str(settings.creator_id),
        settings.x_allowed_user_id,
        settings.x_redirect_uri,
        settings.app_origin,
    )


def _set_session_cookie(
    response: Response, settings: AuthSettings, token: str, max_age: int
) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _browser_cookie_path(settings: AuthSettings) -> str:
    return "/" if settings.cookie_secure else "/api/auth/x/callback"


def _set_oauth_browser_cookie(response: Response, settings: AuthSettings, nonce: str) -> None:
    response.set_cookie(
        settings.oauth_cookie_name,
        nonce,
        max_age=OAUTH_TRANSACTION_TTL,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=_browser_cookie_path(settings),
    )


def _clear_oauth_browser_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(
        settings.oauth_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=_browser_cookie_path(settings),
    )


def _validate_read_only_scopes(scopes: tuple[str, ...] | None) -> bool:
    return scopes is not None and frozenset(scopes) == READ_ONLY_SCOPE_SET


def _revoke_best_effort(provider: XOAuthProvider, token: str | None, hint: str) -> None:
    if token is None:
        return
    try:
        provider.revoke(token, token_type_hint=hint)
    except XOAuthProviderError:
        pass


@router.post(
    "/private/session",
    response_model=SessionResponse,
    responses={401: {}, 503: {}},
    summary="Create the private archive-only BipMe session",
)
def create_private_session(
    payload: PrivateLoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
) -> SessionResponse:
    """Authenticate against the provisioned single-creator secret, without X OAuth."""
    settings = AuthSettings.from_environment()
    if not settings.private_login_ready or not settings.creator_id:
        raise ApiError(
            503,
            "private_session_not_configured",
            "Private account sign-in is unavailable until server configuration is complete.",
        )
    expected = settings.private_login_secret
    assert expected is not None
    if not hmac.compare_digest(payload.secret.encode("utf-8"), expected.encode("utf-8")):
        raise ApiError(
            401, "authentication_required", "The supplied sign-in credential is invalid."
        )
    now = datetime.now(UTC)
    try:
        issued = create_creator_session(
            db,
            creator_id=settings.creator_id,
            auth_method="private_secret",
            x_identity_id=None,
            settings=settings,
            now=now,
        )
        db.commit()
    except ValueError:
        db.rollback()
        raise ApiError(
            503, "private_session_not_configured", "Private account sign-in is unavailable."
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "authentication_unavailable", "Private sign-in is temporarily unavailable."
        ) from None
    _set_session_cookie(response, settings, issued.cookie_token, settings.session_lifetime_seconds)
    return SessionResponse(csrf_token=issued.csrf_token)


@router.get(
    "/session",
    response_model=SessionResponse,
    responses={401: {}, 503: {}},
    summary="Read the active private session and its CSRF token",
)
def read_private_session(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
) -> SessionResponse:
    """Return no creator-supplied identity; the session dependency is authoritative."""
    if creator.csrf_token is None:
        raise ApiError(401, "session_invalid", "The creator session is no longer valid.")
    return SessionResponse(csrf_token=creator.csrf_token)


@router.post(
    "/logout",
    status_code=204,
    responses={401: {}, 403: {}, 503: {}},
    summary="Revoke the current private session",
)
def logout(
    response: Response,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    """Revoke the server-side session and clear its cookie."""
    if creator.session_id is None:
        raise ApiError(401, "session_invalid", "The creator session is no longer valid.")
    record = db.get(CreatorSession, creator.session_id)
    if record is None or record.creator_id != creator.creator_id or record.revoked_at is not None:
        raise ApiError(401, "session_invalid", "The creator session is no longer valid.")
    record.revoked_at = datetime.now(UTC)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "authentication_unavailable", "Logout is temporarily unavailable."
        ) from None
    _clear_session_cookie(response, AuthSettings.from_environment())
    response.status_code = 204
    return response


@router.get(
    "/x/authorize",
    status_code=303,
    responses={400: {}, 503: {}},
    summary="Start X OAuth 2.0 Authorization Code with PKCE",
)
def start_x_authorization(
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[XOAuthProvider, Depends(get_x_oauth_provider)],
    cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
    return_to: Annotated[str, Query(min_length=1, max_length=2048)] = "/",
) -> Response:
    """Persist one-time state, then redirect the browser to X from the callback host."""
    settings = AuthSettings.from_environment()
    _creator_id_text, _allowed_id, redirect_uri, _app_origin = _require_oauth_settings(settings)
    try:
        return_path = validate_return_path(return_to)
    except ValueError:
        raise ApiError(
            422, "invalid_return_url", "The requested return location is invalid."
        ) from None

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge_bytes = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    challenge = challenge_bytes.rstrip(b"=").decode("ascii")
    browser_nonce = secrets.token_urlsafe(32)
    encrypted_verifier = cipher.encrypt(verifier)
    now = datetime.now(UTC)
    transaction = OAuthAuthorizationTransaction(
        id=uuid4(),
        creator_id=settings.creator_id,
        state_hash=secret_digest(state),
        browser_nonce_hash=secret_digest(browser_nonce),
        encrypted_verifier=encrypted_verifier.envelope,
        encryption_key_version=encrypted_verifier.key_version,
        return_path=return_path,
        redirect_uri=redirect_uri,
        created_at=now,
        expires_at=now + timedelta(seconds=OAUTH_TRANSACTION_TTL),
    )
    try:
        db.add(transaction)
        db.commit()
        authorization_url = provider.authorization_url(
            state=state,
            code_challenge=challenge,
            redirect_uri=redirect_uri,
        )
    except (SQLAlchemyError, XOAuthProviderError):
        db.rollback()
        raise ApiError(
            503, "x_oauth_unavailable", "X authorization is temporarily unavailable."
        ) from None
    redirect = RedirectResponse(authorization_url, status_code=303)
    _set_oauth_browser_cookie(redirect, settings, browser_nonce)
    return redirect


def _consume_oauth_transaction(
    db: Session,
    *,
    state: str,
    browser_nonce: str | None,
    now: datetime,
    settings: AuthSettings,
) -> OAuthAuthorizationTransaction:
    if not browser_nonce or len(state) > 500:
        raise ApiError(400, "oauth_callback_invalid", "X authorization could not be verified.")
    transaction = db.scalar(
        select(OAuthAuthorizationTransaction)
        .where(OAuthAuthorizationTransaction.state_hash == secret_digest(state))
        .with_for_update()
    )
    if (
        transaction is None
        or transaction.consumed_at is not None
        or transaction.expires_at <= now
        or not hmac.compare_digest(transaction.browser_nonce_hash, secret_digest(browser_nonce))
        or transaction.creator_id != settings.creator_id
        or transaction.redirect_uri != settings.x_redirect_uri
    ):
        raise ApiError(400, "oauth_callback_invalid", "X authorization could not be verified.")
    transaction.consumed_at = now
    db.commit()
    return transaction


def _create_or_load_x_identity(
    db: Session,
    *,
    creator_id: UUID,
    user_id: str,
    username: str | None,
) -> CreatorPlatformIdentity:
    identity = db.scalar(
        select(CreatorPlatformIdentity).where(
            CreatorPlatformIdentity.platform == "x",
            CreatorPlatformIdentity.external_creator_id == user_id,
        )
    )
    if identity is not None:
        if identity.creator_id != creator_id:
            raise ApiError(403, "x_account_not_allowed", "This X account is not authorized.")
        if username is not None:
            identity.handle = username
        return identity
    identity = CreatorPlatformIdentity(
        id=uuid4(),
        creator_id=creator_id,
        platform="x",
        external_creator_id=user_id,
        handle=username,
    )
    db.add(identity)
    db.flush()
    return identity


def _persist_x_connection(
    db: Session,
    *,
    creator_id: UUID,
    identity: CreatorPlatformIdentity,
    tokens: XOAuthTokens,
    cipher: TokenCipher,
    provider: XOAuthProvider,
    now: datetime,
) -> XAccountConnection:
    if not _validate_read_only_scopes(tokens.scopes) or tokens.refresh_token is None:
        _revoke_best_effort(provider, tokens.access_token, "access_token")
        _revoke_best_effort(provider, tokens.refresh_token, "refresh_token")
        raise ApiError(403, "x_scope_not_allowed", "X did not grant the required read-only access.")
    access_encrypted = cipher.encrypt(tokens.access_token)
    refresh_encrypted = cipher.encrypt(tokens.refresh_token)
    connection = db.scalar(
        select(XAccountConnection).where(
            XAccountConnection.creator_identity_id == identity.id,
            XAccountConnection.creator_id == creator_id,
            XAccountConnection.platform == "x",
        )
    )
    if connection is None:
        connection = XAccountConnection(
            id=uuid4(),
            creator_id=creator_id,
            creator_identity_id=identity.id,
            platform="x",
            state="connected",
            scopes=list(READ_ONLY_X_SCOPES),
            encrypted_access_token=access_encrypted.envelope,
            encrypted_refresh_token=refresh_encrypted.envelope,
            key_version=access_encrypted.key_version,
            access_token_expires_at=now + timedelta(seconds=tokens.expires_in),
            token_rotated_at=now,
            revoked_at=None,
        )
        db.add(connection)
    else:
        if connection.state == "connected":
            try:
                old_access = cipher.decrypt(
                    connection.encrypted_access_token or b"", connection.key_version
                )
                _revoke_best_effort(provider, old_access, "access_token")
                if connection.encrypted_refresh_token:
                    old_refresh = cipher.decrypt(
                        connection.encrypted_refresh_token, connection.key_version
                    )
                    _revoke_best_effort(provider, old_refresh, "refresh_token")
            except TokenEncryptionError:
                pass
        connection.state = "connected"
        connection.scopes = list(READ_ONLY_X_SCOPES)
        connection.encrypted_access_token = access_encrypted.envelope
        connection.encrypted_refresh_token = refresh_encrypted.envelope
        connection.key_version = access_encrypted.key_version
        connection.access_token_expires_at = now + timedelta(seconds=tokens.expires_in)
        connection.token_rotated_at = now
        connection.revoked_at = None
    return connection


@router.get(
    "/x/callback",
    responses={400: {}, 401: {}, 403: {}, 502: {}, 503: {}},
    summary="Complete X OAuth callback and establish a private session",
)
def complete_x_authorization(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[XOAuthProvider, Depends(get_x_oauth_provider)],
    cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
    state: Annotated[str, Query(min_length=1, max_length=500)],
    settings: Annotated[AuthSettings, Depends(AuthSettings.from_environment)],
    code: Annotated[str | None, Query(max_length=2048)] = None,
    error: Annotated[str | None, Query(max_length=128)] = None,
) -> Response:
    """Consume the callback state before any provider exchange, then allowlist X's user ID."""
    _creator_id_text, allowed_user_id, redirect_uri, app_origin = _require_oauth_settings(settings)
    now = datetime.now(UTC)
    try:
        transaction = _consume_oauth_transaction(
            db,
            state=state,
            browser_nonce=request.cookies.get(settings.oauth_cookie_name),
            now=now,
            settings=settings,
        )
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "x_oauth_unavailable", "X authorization is temporarily unavailable."
        ) from None

    tokens: XOAuthTokens | None = None
    try:
        if error is not None:
            if error == "access_denied":
                raise ApiError(403, "x_consent_denied", "X authorization was not granted.")
            raise ApiError(400, "oauth_callback_invalid", "X authorization could not be verified.")
        if not code:
            raise ApiError(400, "oauth_callback_invalid", "X authorization could not be verified.")
        verifier = cipher.decrypt(
            transaction.encrypted_verifier, transaction.encryption_key_version
        )
        tokens = provider.exchange_code(
            code=code,
            verifier=verifier,
            redirect_uri=redirect_uri,
        )
        if not _validate_read_only_scopes(tokens.scopes) or tokens.refresh_token is None:
            raise ApiError(
                403, "x_scope_not_allowed", "X did not grant the required read-only access."
            )
        user = provider.current_user(tokens.access_token)
        if user.user_id != allowed_user_id:
            raise ApiError(403, "x_account_not_allowed", "This X account is not authorized.")
        if settings.creator_id is None or db.get(Creator, settings.creator_id) is None:
            raise ApiError(
                503, "private_session_not_configured", "Private account sign-in is unavailable."
            )

        identity = _create_or_load_x_identity(
            db,
            creator_id=settings.creator_id,
            user_id=user.user_id,
            username=user.username,
        )
        _persist_x_connection(
            db,
            creator_id=settings.creator_id,
            identity=identity,
            tokens=tokens,
            cipher=cipher,
            provider=provider,
            now=now,
        )
        existing_cookie = request.cookies.get(settings.session_cookie_name)
        if existing_cookie:
            old_session = active_session_by_cookie(db, existing_cookie)
            if old_session and old_session.creator_id == settings.creator_id:
                old_session.revoked_at = now
        issued = create_creator_session(
            db,
            creator_id=settings.creator_id,
            auth_method="x_oauth",
            x_identity_id=identity.id,
            settings=settings,
            now=now,
        )
        db.commit()
    except ApiError:
        db.rollback()
        if tokens is not None:
            _revoke_best_effort(provider, tokens.access_token, "access_token")
            _revoke_best_effort(provider, tokens.refresh_token, "refresh_token")
        raise
    except TokenEncryptionError:
        db.rollback()
        if tokens is not None:
            _revoke_best_effort(provider, tokens.access_token, "access_token")
            _revoke_best_effort(provider, tokens.refresh_token, "refresh_token")
        raise ApiError(
            503, "token_protection_unavailable", "X authorization is temporarily unavailable."
        ) from None
    except XOAuthProviderError:
        db.rollback()
        if tokens is not None:
            _revoke_best_effort(provider, tokens.access_token, "access_token")
            _revoke_best_effort(provider, tokens.refresh_token, "refresh_token")
        raise ApiError(
            502, "x_oauth_unavailable", "X authorization could not be completed."
        ) from None
    except SQLAlchemyError:
        db.rollback()
        if tokens is not None:
            _revoke_best_effort(provider, tokens.access_token, "access_token")
            _revoke_best_effort(provider, tokens.refresh_token, "refresh_token")
        raise ApiError(
            503, "x_oauth_unavailable", "X authorization is temporarily unavailable."
        ) from None

    target = urlsplit(f"{app_origin}{transaction.return_path}")
    query = [
        (key, value)
        for key, value in parse_qsl(target.query, keep_blank_values=True)
        if key != "x_connection"
    ]
    query.append(("x_connection", "connected"))
    location = urlunsplit(
        (target.scheme, target.netloc, target.path, urlencode(query), target.fragment)
    )
    redirect = RedirectResponse(location, status_code=303)
    _set_session_cookie(redirect, settings, issued.cookie_token, settings.session_lifetime_seconds)
    _clear_oauth_browser_cookie(redirect, settings)
    return redirect


def refresh_connection_tokens(
    db: Session,
    *,
    creator_id: UUID,
    provider: XOAuthProvider,
    cipher: TokenCipher,
    now: datetime,
) -> XAccountConnection:
    """Rotate an authorized connection's token pair without exposing token values."""
    connection = db.scalar(
        select(XAccountConnection).where(
            XAccountConnection.creator_id == creator_id,
            XAccountConnection.platform == "x",
            XAccountConnection.state == "connected",
        )
    )
    if connection is None:
        raise ApiError(404, "x_connection_not_found", "No active X connection was found.")
    if connection.encrypted_refresh_token is None:
        connection.state = "reauth_required"
        connection.encrypted_access_token = None
        connection.access_token_expires_at = None
        db.commit()
        raise ApiError(
            401, "x_reauthorization_required", "The X connection must be authorized again."
        )
    try:
        old_refresh = cipher.decrypt(connection.encrypted_refresh_token, connection.key_version)
    except TokenEncryptionError:
        connection.state = "reauth_required"
        connection.encrypted_access_token = None
        connection.encrypted_refresh_token = None
        connection.access_token_expires_at = None
        db.commit()
        raise ApiError(
            401, "x_reauthorization_required", "The X connection must be authorized again."
        ) from None
    try:
        tokens = provider.refresh(old_refresh)
    except XOAuthProviderError as exc:
        if exc.reauth_required:
            connection.state = "reauth_required"
            connection.encrypted_access_token = None
            connection.encrypted_refresh_token = None
            connection.access_token_expires_at = None
            db.commit()
            raise ApiError(
                401, "x_reauthorization_required", "The X connection must be authorized again."
            ) from None
        raise ApiError(
            502, "x_refresh_unavailable", "The X connection could not be refreshed."
        ) from None
    if tokens.scopes is not None and not _validate_read_only_scopes(tokens.scopes):
        raise ApiError(
            403, "x_scope_not_allowed", "X did not preserve the required read-only access."
        )
    new_access = cipher.encrypt(tokens.access_token)
    new_refresh = cipher.encrypt(tokens.refresh_token or old_refresh)
    connection.encrypted_access_token = new_access.envelope
    connection.encrypted_refresh_token = new_refresh.envelope
    connection.key_version = new_access.key_version
    connection.scopes = list(READ_ONLY_X_SCOPES)
    connection.access_token_expires_at = now + timedelta(seconds=tokens.expires_in)
    connection.token_rotated_at = now
    db.commit()
    return connection


@router.post(
    "/x/refresh",
    response_model=XConnectionResponse,
    responses={401: {}, 403: {}, 404: {}, 502: {}, 503: {}},
    summary="Refresh the connected X credentials",
)
def refresh_x_connection(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[XOAuthProvider, Depends(get_x_oauth_provider)],
    cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
) -> XConnectionResponse:
    settings = AuthSettings.from_environment()
    _require_oauth_settings(settings)
    try:
        connection = refresh_connection_tokens(
            db,
            creator_id=creator.creator_id,
            provider=provider,
            cipher=cipher,
            now=datetime.now(UTC),
        )
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "x_refresh_unavailable", "The X connection could not be refreshed."
        ) from None
    return XConnectionResponse(
        connected=True,
        state=connection.state,
        scopes=tuple(connection.scopes),
        expires_at=connection.access_token_expires_at,
    )


@router.post(
    "/x/disconnect",
    status_code=204,
    responses={401: {}, 403: {}, 404: {}, 503: {}},
    summary="Revoke and disconnect the X account",
)
def disconnect_x_connection(
    response: Response,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[XOAuthProvider, Depends(get_x_oauth_provider)],
    cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
) -> Response:
    settings = AuthSettings.from_environment()
    _require_oauth_settings(settings)
    connection = db.scalar(
        select(XAccountConnection).where(
            XAccountConnection.creator_id == creator.creator_id,
            XAccountConnection.platform == "x",
            XAccountConnection.state != "revoked",
        )
    )
    if connection is None:
        raise ApiError(404, "x_connection_not_found", "No X connection was found.")
    try:
        if connection.encrypted_access_token:
            _revoke_best_effort(
                provider,
                cipher.decrypt(connection.encrypted_access_token, connection.key_version),
                "access_token",
            )
        if connection.encrypted_refresh_token:
            _revoke_best_effort(
                provider,
                cipher.decrypt(connection.encrypted_refresh_token, connection.key_version),
                "refresh_token",
            )
    except TokenEncryptionError:
        pass
    connection.state = "revoked"
    connection.encrypted_access_token = None
    connection.encrypted_refresh_token = None
    connection.access_token_expires_at = None
    connection.revoked_at = datetime.now(UTC)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            503, "x_disconnect_unavailable", "The X connection could not be disconnected."
        ) from None
    response.status_code = 204
    return response


@router.get(
    "/x/connection",
    response_model=XConnectionResponse,
    responses={401: {}, 503: {}},
    summary="Read X connection status without returning credentials",
)
def get_x_connection_status(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> XConnectionResponse:
    connection = db.scalar(
        select(XAccountConnection).where(
            XAccountConnection.creator_id == creator.creator_id,
            XAccountConnection.platform == "x",
        )
    )
    if connection is None or connection.state == "revoked":
        return XConnectionResponse(connected=False, state="revoked" if connection else None)
    return XConnectionResponse(
        connected=connection.state == "connected",
        state=connection.state,
        scopes=tuple(connection.scopes),
        expires_at=connection.access_token_expires_at,
    )


def rotate_connection_encryption_keys(db: Session, *, cipher: TokenCipher, now: datetime) -> int:
    """Re-encrypt all active X credentials under the cipher's active key version."""
    connections = list(
        db.scalars(
            select(XAccountConnection).where(
                XAccountConnection.state == "connected",
                XAccountConnection.platform == "x",
            )
        ).all()
    )
    rotated = 0
    for connection in connections:
        try:
            access = cipher.decrypt(
                connection.encrypted_access_token or b"", connection.key_version
            )
            refresh = (
                cipher.decrypt(connection.encrypted_refresh_token, connection.key_version)
                if connection.encrypted_refresh_token
                else None
            )
        except TokenEncryptionError:
            raise ApiError(
                503, "token_rotation_failed", "Stored X credentials could not be rotated."
            ) from None
        access_encrypted = cipher.encrypt(access)
        refresh_encrypted = cipher.encrypt(refresh) if refresh else None
        connection.encrypted_access_token = access_encrypted.envelope
        connection.encrypted_refresh_token = (
            refresh_encrypted.envelope if refresh_encrypted else None
        )
        connection.key_version = access_encrypted.key_version
        connection.token_rotated_at = now
        rotated += 1
    db.commit()
    return rotated
