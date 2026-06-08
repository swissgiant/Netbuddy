from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import AuditLog, User


async def audit(
    session: AsyncSession,
    actor: User | None,
    action: str,
    target: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """Schreibt einen Audit-Eintrag (verändernde Aktion). `actor` = eingeloggter User."""
    session.add(
        AuditLog(
            actor=actor.username if actor else None,
            action=action,
            target=target,
            detail=detail or {},
        )
    )
