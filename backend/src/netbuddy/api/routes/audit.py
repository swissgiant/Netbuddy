import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])  # via RBAC nur für admin


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor: str | None
    action: str
    target: str
    detail: dict[str, Any]
    created_at: datetime


@router.get("", response_model=list[AuditRead])
async def list_audit(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> Sequence[AuditLog]:
    """Letzte Audit-Einträge (neueste zuerst)."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    return (await session.execute(stmt)).scalars().all()
