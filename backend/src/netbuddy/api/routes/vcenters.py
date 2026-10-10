"""Kategorie „vCenter" — Liste der vCenter mit Hosts/Clustern (read-only).

Befüllt über :mod:`netbuddy.services.vcenter_inventory`. Die Detail-Infos je Host/VM liegen in
den Kategorien physische/virtuelle Server und lassen sich über ``cluster``/``esxi_host``/``vcenter``
dort wieder herausfiltern.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Vcenter

router = APIRouter(prefix="/vcenters", tags=["vcenters"])


class VcenterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    host: str | None
    version: str | None
    build: str | None
    full_name: str | None
    api_type: str | None
    datacenters: list[str]
    clusters: list[dict[str, object]]
    hosts: list[dict[str, object]]
    host_count: int | None
    vm_count: int | None
    source: str | None
    last_seen: datetime | None
    notes: str | None
    created_at: datetime


@router.get("", response_model=list[VcenterRead])
async def list_vcenters(session: SessionDep) -> list[VcenterRead]:
    rows = (
        (
            await session.execute(
                select(Vcenter).where(Vcenter.deleted_at.is_(None)).order_by(Vcenter.name)
            )
        )
        .scalars()
        .all()
    )
    return [VcenterRead.model_validate(r) for r in rows]
