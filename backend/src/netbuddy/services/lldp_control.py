import re
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.profile import LldpControlSpec
from netbuddy.db.models import Device
from netbuddy.services.backup import backup_device

# Logische/virtuelle Interfaces bekommen kein `lldp enable` (nur physische Ports).
_LOGICAL = re.compile(
    r"^(vlan|vl|lo|loopback|po|port-?channel|null|tun|mgmt|stack|cpu|bundle)", re.IGNORECASE
)


def is_physical(name: str) -> bool:
    return not _LOGICAL.match(name.strip())


class WriteTransport(Protocol):
    """Transport, der lesen UND (autorisiert) schreiben kann — vom LLDP-Endpoint genutzt."""

    async def send_command(self, command: str) -> str: ...
    async def send_config(self, lines: list[str]) -> str: ...


class LldpEnableResult(BaseModel):
    """Ergebnis eines LLDP-Aktivierungslaufs (Backup → schreiben → verifizieren)."""

    was_enabled: bool  # LLDP-Status vor dem Eingriff
    backed_up: bool  # eine Konfig-Sicherung wurde angelegt
    interfaces_configured: int  # Anzahl physischer Ports, die `lldp enable` bekamen
    enabled_after: bool  # LLDP-Status nach dem Eingriff (Verifikation)


async def read_lldp_enabled(transport: WriteTransport, spec: LldpControlSpec) -> bool:
    """Liest read-only den globalen LLDP-Status (True = aktiv)."""
    output = await transport.send_command(spec.status_command)
    return re.search(spec.enabled_marker, output, re.IGNORECASE) is not None


async def enable_lldp(
    session: AsyncSession,
    device: Device,
    adapter: SwitchAdapter,
    transport: WriteTransport,
    spec: LldpControlSpec,
) -> LldpEnableResult:
    """Aktiviert LLDP global + pro physischem Port. Sichert vorher die Konfig, verifiziert danach.

    ⚠️ Schreibzugriff auf echte Hardware. Aufrufer muss autorisiert sein; der Eingriff bleibt
    eng auf LLDP begrenzt und wird im Audit-Log festgehalten (durch den Endpoint).
    """
    was_enabled = await read_lldp_enabled(transport, spec)

    # 1) Backup vor dem Schreiben (Rollback-Anker).
    backup = await backup_device(session, device, adapter)
    backed_up = backup.changed or True  # eine Sicherung existiert jetzt in jedem Fall

    # 2) Konfig-Zeilen: global + je physischem Interface.
    physical = [i.name for i in await adapter.get_interfaces() if is_physical(i.name)]
    lines: list[str] = list(spec.enable_global)
    for name in physical:
        lines.append(spec.interface_enter.format(name=name))
        lines.extend(spec.enable_interface)
        lines.append(spec.interface_exit)
    if lines:
        await transport.send_config(lines)

    # 3) Verifikation.
    enabled_after = await read_lldp_enabled(transport, spec)
    return LldpEnableResult(
        was_enabled=was_enabled,
        backed_up=backed_up,
        interfaces_configured=len(physical),
        enabled_after=enabled_after,
    )
