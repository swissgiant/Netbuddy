import uuid

from pydantic import BaseModel
from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import Device, Host, Interface, LldpNeighbor, MacAddressEntry
from netbuddy.services.hosts import normalize_mac


class LocateResult(BaseModel):
    """Ein Treffer: ein (End-)Gerät, das an einem Switch-Port gesehen wurde."""

    kind: str  # "host" (Name/IP aufgelöst) | "mac" (MAC-Table) | "lldp" (LLDP-Nachbar)
    match: str  # der gematchte Wert (Name / IP / MAC / Chassis-ID)
    device_id: uuid.UUID  # der Switch, an dem es hängt
    device_hostname: str
    port: str  # lokaler Interface-Name
    vlan: int | None = None
    mac: str | None = None
    ip_address: str | None = None
    name: str | None = None
    system_name: str | None = None
    mgmt_address: str | None = None


# MACADDR-Spalte → kanonische 12-Hex-Form, damit der Join auf Host.mac trifft.
_MAC_CANON = func.replace(func.replace(cast(MacAddressEntry.mac_address, String), ":", ""), ".", "")


async def locate(session: AsyncSession, query: str, *, limit: int = 100) -> list[LocateResult]:
    """Sucht ein Endgerät per MAC / Name / IP und liefert Switch + Port, wo es hängt.

    Quellen: MAC-Address-Table (MAC) und LLDP-Nachbarn (System-Name, Chassis-ID, Mgmt-IP).
    Read-only; Suche ist case-insensitiv und als Teilstring.
    """
    pattern = f"%{query.strip()}%"
    results: list[LocateResult] = []

    # Namensauflösung: korrelierte Hosts (Name/IP aus ARP+DNS) → über die kanonische MAC auf
    # den Switch-Port, an dem die MAC gelernt wurde. So findet man ein Endgerät per Name.
    mac_query = normalize_mac(query)
    host_filters: list[ColumnElement[bool]] = [
        Host.name.ilike(pattern),
        Host.ip_address.ilike(pattern),
    ]
    if mac_query:
        host_filters.append(Host.mac == mac_query)
    host_stmt = (
        select(Host, Device.id, Device.hostname, Interface.name, MacAddressEntry.vlan_id)
        .join(MacAddressEntry, _MAC_CANON == Host.mac)
        .join(Device, Device.id == MacAddressEntry.device_id)
        .join(Interface, Interface.id == MacAddressEntry.interface_id)
        .where(or_(*host_filters))
        .limit(limit)
    )
    for host, dev_id, hostname, port, vlan in (await session.execute(host_stmt)).all():
        results.append(
            LocateResult(
                kind="host",
                match=host.name or host.ip_address or host.mac,
                device_id=dev_id,
                device_hostname=hostname,
                port=port,
                vlan=vlan,
                mac=host.mac,
                ip_address=host.ip_address,
                name=host.name,
            )
        )

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
