import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import AuthSession, User

SESSION_TTL = timedelta(hours=12)
COOKIE_NAME = "nb_session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    # SSO-only-User haben kein lokales Passwort → kein Passwort-Login möglich.
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(session: AsyncSession, user: User) -> str:
    """Erzeugt einen opaken Login-Token; in der DB liegt nur sein SHA-256-Hash."""
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            expires_at=datetime.now(UTC) + SESSION_TTL,
        )
    )
    await session.flush()
    return token


async def resolve_token(session: AsyncSession, token: str) -> User | None:
    """Token → aktiver, nicht abgelaufener User (sonst None)."""
    stmt = (
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.expires_at > datetime.now(UTC),
            User.deleted_at.is_(None),
            User.enabled.is_(True),
        )
    )
    return (await session.execute(stmt)).scalars().first()


async def revoke_token(session: AsyncSession, token: str) -> None:
    await session.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))


async def any_user_exists(session: AsyncSession) -> bool:
    stmt = select(User.id).where(User.deleted_at.is_(None)).limit(1)
    return (await session.execute(stmt)).first() is not None
