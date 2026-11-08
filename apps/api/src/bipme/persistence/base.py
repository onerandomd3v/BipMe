"""Declarative base and shared timestamp type for SQLAlchemy models."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, LargeBinary, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Require aware datetimes and normalize all application values to UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("database timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class EncryptedTokenEnvelope(TypeDecorator[bytes]):
    """Opaque encrypted-token bytes marked with a non-plaintext envelope prefix."""

    impl = LargeBinary
    cache_ok = True
    prefix = b"BIPME-ENC\x01"

    def process_bind_param(self, value: bytes | None, dialect: Any) -> bytes | None:
        if value is None:
            return None
        if not isinstance(value, bytes) or not value.startswith(self.prefix):
            raise ValueError("token values must be encrypted BIPME-ENC v1 envelopes")
        return value


class Base(DeclarativeBase):
    """Shared base with deterministic constraint names for migrations."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
