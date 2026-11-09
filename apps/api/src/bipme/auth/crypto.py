"""Token encryption and one-way digests used by authentication flows."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from bipme.persistence.base import EncryptedTokenEnvelope


class TokenEncryptionError(Exception):
    """Raised without revealing the key, envelope, or plaintext token."""


@dataclass(frozen=True)
class EncryptedSecret:
    envelope: bytes
    key_version: str


class TokenCipher:
    """Authenticated encryption with explicit key versions and server-side key material."""

    def __init__(self, keys: Mapping[str, str], active_key_version: str) -> None:
        if not active_key_version or active_key_version not in keys:
            raise TokenEncryptionError("token encryption is not configured")
        try:
            self._keys = {version: Fernet(key.encode("ascii")) for version, key in keys.items()}
        except (ValueError, UnicodeEncodeError):
            raise TokenEncryptionError("token encryption is not configured") from None
        self.active_key_version = active_key_version

    def encrypt(self, value: str) -> EncryptedSecret:
        if not isinstance(value, str) or not value:
            raise TokenEncryptionError("token encryption failed")
        try:
            ciphertext = self._keys[self.active_key_version].encrypt(value.encode("utf-8"))
        except Exception:
            raise TokenEncryptionError("token encryption failed") from None
        return EncryptedSecret(
            envelope=EncryptedTokenEnvelope.prefix + ciphertext,
            key_version=self.active_key_version,
        )

    def decrypt(self, envelope: bytes, key_version: str) -> str:
        if (
            not isinstance(envelope, bytes)
            or not envelope.startswith(EncryptedTokenEnvelope.prefix)
            or key_version not in self._keys
        ):
            raise TokenEncryptionError("token decryption failed")
        try:
            plaintext = self._keys[key_version].decrypt(
                envelope[len(EncryptedTokenEnvelope.prefix) :]
            )
            return plaintext.decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError):
            raise TokenEncryptionError("token decryption failed") from None


def secret_digest(value: str) -> str:
    """Hash a high-entropy bearer value before storing it in the database."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_digest(value: str, expected: str) -> bool:
    return hmac.compare_digest(secret_digest(value), expected)


def csrf_token_for(session_token: str) -> str:
    """Derive a synchronizer token bound to an unguessable server session cookie."""
    return hmac.new(session_token.encode("utf-8"), b"bipme-csrf-v1", hashlib.sha256).hexdigest()
