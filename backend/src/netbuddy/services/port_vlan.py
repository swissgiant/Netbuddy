"""Access-Port einem VLAN zuweisen (autorisierter Schreibpfad, Feature #34).

Spiegelt das LLDP-Muster (siehe :mod:`netbuddy.services.lldp_control`): Backup vor dem
Schreiben, eng begrenzte Konfig-Sequenz aus dem Profil (``port_vlan_control``), Verifikation
per Re-Read. Schreibzugriff nur über den autorisierten Endpoint, nie read-only.
"""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.profile import PortVlanControlSpec
from netbuddy.db.models import Device, Interface
from netbuddy.services.backup import backup_device
from netbuddy.services.lldp_control import WriteTransport, is_physical


class PortVlanResult(BaseModel):
    """Ergebnis einer Port→VLAN-Zuweisung (Backup → schreiben → verifizieren)."""

    interface: str
    vlan_id: int
    backed_up: bool
    verified: bool | None  # True/False per Re-Read; None = Adapter liefert keine Port-VLAN


async def assign_port_vlan(
    session: AsyncSession,
    device: Device,
    adapter: SwitchAdapter,
    transport: WriteTransport,
    spec: PortVlanControlSpec,
    interface_name: str,
    vlan_id: int,
) -> PortVlanResult:
    """Setzt einen physischen Port auf Access-Mode + Access-VLAN (Backup vorher, Verify danach).

    ⚠️ Schreibzugriff auf echte Hardware. Aufrufer muss autorisiert sein; der Eingriff bleibt
    eng auf die VLAN-Zuweisung eines Ports begrenzt und wird im Audit-Log festgehalten.
    """
    if not is_physical(interface_name):
        raise ValueError(f"{interface_name!r} ist kein physischer Port")

    # 1) Backup vor dem Schreiben (Rollback-Anker).
    await backup_device(session, device, adapter)

    # 2) Konfig-Sequenz: enter → interface → set_access (mit {vlan}/{name}) → exit.
    lines: list[str] = [*spec.config_enter, spec.interface_enter.format(name=interface_name)]
    lines.extend(line.format(vlan=vlan_id, name=interface_name) for line in spec.set_access)
    lines.append(spec.interface_exit)
    lines.extend(spec.config_exit)
    await transport.send_config(lines)

    # 3) Verifikation per Re-Read (best effort — nicht jedes Profil liefert Port-VLANs).
    verified: bool | None = None
    try:
        for itf in await adapter.get_interfaces():
            if itf.name == interface_name:
                verified = itf.vlan_id == vlan_id if itf.vlan_id is not None else None
                break
    except Exception:
        verified = None

    # 4) Inventar sofort konsistent halten (Frontend zeigt das neue VLAN ohne Re-Discovery).
    row = (
        (
            await session.execute(
                select(Interface).where(
                    Interface.device_id == device.id, Interface.name == interface_name
                )
            )
        )
        .scalars()
        .first()
    )
    if row is not None:
        row.vlan_id = vlan_id

    return PortVlanResult(
        interface=interface_name, vlan_id=vlan_id, backed_up=True, verified=verified
    )
