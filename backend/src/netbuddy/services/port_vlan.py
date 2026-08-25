"""Access-Port einem VLAN zuweisen bzw. zurücksetzen (autorisierter Schreibpfad, Feature #34).

Spiegelt das LLDP-Muster (siehe :mod:`netbuddy.services.lldp_control`): Backup vor dem
Schreiben, eng begrenzte Konfig-Sequenz aus dem Profil (``port_vlan_control``), danach
**persistentes Save** (running → startup, Profil-``save``-Sequenz) und **Verifikation** über
ein gezieltes Show-Kommando (``verify_command``/``verify_pattern``) — zuverlässiger als der
frühere Re-Read über ``get_interfaces`` (viele Profile parsen kein Port-VLAN).
Schreibzugriff nur über den autorisierten Endpoint, nie read-only.
"""

import re

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.profile import PortVlanControlSpec
from netbuddy.db.models import Device, Interface
from netbuddy.services.backup import backup_device
from netbuddy.services.lldp_control import WriteTransport, is_physical


class PortVlanResult(BaseModel):
    """Ergebnis einer Port→VLAN-Zuweisung (Backup → schreiben → speichern → verifizieren)."""

    interface: str
    vlan_id: int
    backed_up: bool
    saved: bool | None = None  # startup-config geschrieben; None = Profil kennt kein Save
    verified: bool | None = None  # True/False per Show-Verify; None = nicht verifizierbar


async def _save_config(transport: WriteTransport, spec: PortVlanControlSpec) -> bool | None:
    """Running-Config persistieren (Profil-``save``-Sequenz inkl. Confirm-Zeilen)."""
    if not spec.save:
        return None
    output = await transport.send_config(list(spec.save))
    if spec.save_marker:
        return spec.save_marker.lower() in output.lower()
    return True


async def _verify_vlan(
    adapter: SwitchAdapter,
    transport: WriteTransport,
    spec: PortVlanControlSpec,
    interface_name: str,
    vlan_id: int,
    *,
    is_reset: bool,
) -> bool | None:
    """Gezielter Show-Verify; Fallback = Re-Read über den Adapter (falls der VLANs liefert)."""
    if spec.verify_command and spec.verify_pattern:
        output = await transport.send_command(spec.verify_command.format(name=interface_name))
        pattern = spec.verify_pattern.replace("{vlan}", str(vlan_id))
        if re.search(pattern, output, re.IGNORECASE):
            return True
        if is_reset:
            # Reset auf Default: viele Vendor entfernen die access-vlan-Zeile komplett —
            # „keine explizite VLAN-Konfig mehr" ist dann ebenfalls ein bestandener Verify.
            return not re.search(r"switchport access vlan \d+", output, re.IGNORECASE)
        return False
    try:
        for itf in await adapter.get_interfaces():
            if itf.name == interface_name:
                return itf.vlan_id == vlan_id if itf.vlan_id is not None else None
    except Exception:
        return None
    return None


async def _write_port_vlan(
    session: AsyncSession,
    device: Device,
    adapter: SwitchAdapter,
    transport: WriteTransport,
    spec: PortVlanControlSpec,
    interface_name: str,
    body: list[str],
    result_vlan: int,
    *,
    is_reset: bool,
) -> PortVlanResult:
    """Gemeinsamer Schreibpfad: Backup → Konfig → Save → Verify → Inventar-Update.

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

    saved = await _save_config(transport, spec)
    verified = await _verify_vlan(
        adapter, transport, spec, interface_name, result_vlan, is_reset=is_reset
    )

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
        interface=interface_name,
        vlan_id=result_vlan,
        backed_up=True,
        saved=saved,
        verified=verified,
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
    """Setzt einen physischen Port auf Access-Mode + Access-VLAN (Backup/Save/Verify)."""
    body = [line.format(vlan=vlan_id, name=interface_name) for line in spec.set_access]
    return await _write_port_vlan(
        session, device, adapter, transport, spec, interface_name, body, vlan_id, is_reset=False
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
        session, device, adapter, transport, spec, interface_name, body, 1, is_reset=True
    )
