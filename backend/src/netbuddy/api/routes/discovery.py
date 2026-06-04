from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Device, Interface, LldpNeighbor

router = APIRouter(prefix="/discovery", tags=["discovery"])


class SuggestedDevice(BaseModel):
    """Ein über LLDP gesehener Nachbar, der noch nicht im Inventar ist (Add-Vorschlag)."""

    system_name: str | None
    chassis_id: str
    remote_port_id: str
    system_description: str | None
    seen_on: list[str]  # "<hostname> / <local-interface>"


@router.get("/suggestions", response_model=list[SuggestedDevice])
async def list_suggestions(session: SessionDep) -> list[SuggestedDevice]:
    """Schlägt naheliegende Geräte vor: LLDP-Nachbarn bekannter Geräte, die selbst noch
    nicht als `Device` erfasst sind (gematcht über `remote_system_name == hostname`)."""
    devices = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )
    known_hostnames = {d.hostname for d in devices}
    device_by_id = {d.id: d for d in devices}
    iface_by_id = {i.id: i for i in (await session.execute(select(Interface))).scalars()}

    by_chassis: dict[str, SuggestedDevice] = {}
    for n in (await session.execute(select(LldpNeighbor))).scalars():
        if n.remote_system_name and n.remote_system_name in known_hostnames:
            continue  # schon im Inventar
        local_dev = device_by_id.get(n.local_device_id)
        local_iface = iface_by_id.get(n.local_interface_id)
        seen = (
            f"{local_dev.hostname if local_dev else '?'} / "
            f"{local_iface.name if local_iface else '?'}"
        )
        existing = by_chassis.get(n.remote_chassis_id)
        if existing is None:
            by_chassis[n.remote_chassis_id] = SuggestedDevice(
                system_name=n.remote_system_name,
                chassis_id=n.remote_chassis_id,
                remote_port_id=n.remote_port_id,
                system_description=n.remote_system_description,
                seen_on=[seen],
            )
        elif seen not in existing.seen_on:
            existing.seen_on.append(seen)

    return list(by_chassis.values())
