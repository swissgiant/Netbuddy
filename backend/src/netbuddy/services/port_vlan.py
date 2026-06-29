"""Access-Port einem VLAN zuweisen bzw. zurücksetzen (autorisierter Schreibpfad, Feature #34).

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


async def _write_port_vlan(
    session: AsyncSession,
    device: Device,
    adapter: SwitchAdapter,
    transport: WriteTransport,
    spec: PortVlanControlSpec,
    interface_name: str,
    body: list[str],
    result_vlan: int,
) -> PortVlanResult:
    """Gemeinsamer Schreibpfad: Backup → enter → interface → `body` → exit → Verify → Inventar.

    ⚠️ Schreibzugriff auf echte Hardware. Eng auf einen Port begrenzt, Audit beim Endpoint.
    """
    if not is_physical(interface_name):
        raise ValueError(f"{interface_name!r} ist kein physischer Port")

    await backup_device(session, device, adapter)  # Rollback-Anker

    lines: list[str] = [*spec.config_enter, spec.interface_enter.format(name=interface_name)]
    lines.extend(body)
    lines.append(spec.interface_exit)
    lines.extend(spec.config_exit)
    await transport.send_config(lines)

    # Verifikation per Re-Read (best effort — nicht jedes Profil liefert Port-VLANs).
    verified: bool | None = None
    try:
        for itf in await adapter.get_interfaces():
            if itf.name == interface_name:
                verified = itf.vlan_id == result_vlan if itf.vlan_id is not None else None
                break
    except Exception:
        verified = None

    # Inventar sofort konsistent halten (Frontend zeigt das neue VLAN ohne Re-Discovery).
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
        row.vlan_id = result_vlan

    return PortVlanResult(
        interface=interface_name, vlan_id=result_vlan, backed_up=True, verified=verified
    )


async def assign_port_vlan(
    session: AsyncSession,
    device: Device,
    adapter: SwitchAdapter,
    transport: WriteTransport,
    spec: PortVlanControlSpec,
    interface_name: str,
    vlan_id: int,
) -> PortVlanResult:
    """Setzt einen physischen Port auf Access-Mode + Access-VLAN (Backup vorher, Verify danach)."""
    body = [line.format(vlan=vlan_id, name=interface_name) for line in spec.set_access]
    return await _write_port_vlan(
        session, device, adapter, transport, spec, interface_name, body, vlan_id
    )


async def reset_port_vlan(
    session: AsyncSession,
    device: Device,
    adapter: SwitchAdapter,
    transport: WriteTransport,
    spec: PortVlanControlSpec,
    interface_name: str,
) -> PortVlanResult:
    """Setzt einen Port auf das Default-VLAN 1 zurück (nimmt eine Test-VLAN-Zuweisung weg)."""
    body = [line.format(vlan=1, name=interface_name) for line in spec.reset_access]
    return await _write_port_vlan(
        session, device, adapter, transport, spec, interface_name, body, 1
    )
