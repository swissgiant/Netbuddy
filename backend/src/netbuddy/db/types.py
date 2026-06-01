import enum

from cryptography.fernet import Fernet
from sqlalchemy import String
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

from netbuddy.core.config import get_settings


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """`values_callable` for SQLAlchemy `Enum` columns.

    Forces the DB enum values to use the Python enum value (e.g. ``"switch"``)
    instead of the member name (``"SWITCH"``). Required for our StrEnum models
    so that server-side defaults like ``'unknown'`` match the type.
    """
    return [str(member.value) for member in enum_cls]


def _fernet() -> Fernet:
    settings = get_settings()
    return Fernet(settings.fernet_key.get_secret_value().encode())


class EncryptedString(TypeDecorator[str]):
    """String column transparently encrypted at rest with Fernet."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return _fernet().decrypt(value.encode()).decode()
