import uuid

from pydantic import BaseModel
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import Device, Interface, LldpNeighbor, MacAddressEntry


class LocateResult(BaseModel):
    """Ein Treffer: ein (End-)Gerät, das an einem Switch-Port gesehen wurde."""

    kind: str  # "mac" (aus der MAC-Table) | "lldp" (LLDP-Nachbar)
    match: str  # der gematchte Wert (MAC / System-Name / Chassis-ID)
    device_id: uuid.UUID  # der Switch, an dem es hängt
    device_hostname: str
    port: str  # lokaler Interface-Name
    vlan: int | None = None
    mac: str | None = None
    system_name: str | None = None
    mgmt_address: str | None = None


async def locate(session: AsyncSession, query: str, *, limit: int = 100) -> list[LocateResult]:
    """Sucht ein Endgerät per MAC / Name / IP und liefert Switch + Port, wo es hängt.

    Quellen: MAC-Address-Table (MAC) und LLDP-Nachbarn (System-Name, Chassis-ID, Mgmt-IP).
    Read-only; Suche ist case-insensitiv und als Teilstring.
    """
    pattern = f"%{query.strip()}%"
    results: list[LocateResult] = []

    mac_stmt = (
        select(MacAddressEntry, Device.hostname, Interface.name)
        .join(Device, Device.id == MacAddressEntry.device_id)
        .join(Interface, Interface.id == MacAddressEntry.interface_id)
        .where(cast(MacAddressEntry.mac_address, String).ilike(pattern))
        .limit(limit)
    )
    for entry, hostname, port in (await session.execute(mac_stmt)).all():
        results.append(
            LocateResult(
                kind="mac",
                match=entry.mac_address,
                device_id=entry.device_id,
                device_hostname=hostname,
                port=port,
                vlan=entry.vlan_id,
                mac=entry.mac_address,
            )
        )

    lldp_stmt = (
        select(LldpNeighbor, Device.hostname, Interface.name)
        .join(Device, Device.id == LldpNeighbor.local_device_id)
        .join(Interface, Interface.id == LldpNeighbor.local_interface_id)
        .where(
            or_(
                LldpNeighbor.remote_system_name.ilike(pattern),
                LldpNeighbor.remote_chassis_id.ilike(pattern),
                LldpNeighbor.remote_mgmt_address.ilike(pattern),
            )
        )
        .limit(limit)
    )
    for neighbor, hostname, port in (await session.execute(lldp_stmt)).all():
        results.append(
            LocateResult(
                kind="lldp",
                match=neighbor.remote_system_name or neighbor.remote_chassis_id,
                device_id=neighbor.local_device_id,
                device_hostname=hostname,
                port=port,
                system_name=neighbor.remote_system_name,
                mac=neighbor.remote_chassis_id,
                mgmt_address=neighbor.remote_mgmt_address,
            )
        )

    return results
