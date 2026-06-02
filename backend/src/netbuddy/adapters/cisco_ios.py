import re
from typing import Any, ClassVar, cast

from ntc_templates.parse import parse_output

from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
)
from netbuddy.adapters.registry import register_adapter
from netbuddy.adapters.transport import CommandTransport
from netbuddy.db.models import AdminStatus, DeviceType, MacEntryType, OperStatus

_PLATFORM = "cisco_ios"

# Vendor-Status-Strings → unsere Enums. Unbekanntes fällt auf UNKNOWN/DYNAMIC zurück,
# damit unerwarteter CLI-Output nie crasht.
_ADMIN_STATUS = {
    "up": AdminStatus.UP,
    "down": AdminStatus.DOWN,
    "administratively down": AdminStatus.DOWN,
}
_OPER_STATUS = {
    "up": OperStatus.UP,
    "down": OperStatus.DOWN,
    "testing": OperStatus.TESTING,
}


def _or_none(value: str | None) -> str | None:
    """Leerstrings (typisch für ntc-templates) auf ``None`` normalisieren."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _first(value: Any) -> str | None:
    """Erstes Element einer ntc-Liste bzw. den String selbst, leer → ``None``."""
    if isinstance(value, list):
        return _or_none(value[0]) if value else None
    return _or_none(value)


def _int_or_none(value: str | None) -> int | None:
    value = _or_none(value)
    if value is None or not value.isdigit():
        return None
    return int(value)


def _admin_status(link_status: str) -> AdminStatus:
    return _ADMIN_STATUS.get(link_status.strip().lower(), AdminStatus.UNKNOWN)


def _oper_status(protocol_status: str) -> OperStatus:
    # protocol_status sieht aus wie "up (connected)" — nur das erste Wort zählt.
    first_word = protocol_status.strip().lower().split(maxsplit=1)[0] if protocol_status else ""
    return _OPER_STATUS.get(first_word, OperStatus.UNKNOWN)


def _speed_mbps(bandwidth: str | None) -> int | None:
    """``"1000000 Kbit"`` → 1000 (Mbit/s). Nur das Kbit-Format wird erwartet."""
    bandwidth = _or_none(bandwidth)
    if bandwidth is None:
        return None
    match = re.match(r"(\d+)\s*Kbit", bandwidth, re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1)) // 1000


def _entry_type(raw: str) -> MacEntryType:
    try:
        return MacEntryType(raw.strip().lower())
    except ValueError:
        return MacEntryType.DYNAMIC


@register_adapter
class CiscoIosAdapter:
    """Read-only-Adapter für Cisco IOS / IOS-XE, geparst via ntc-templates.

    Der Adapter spricht selbst kein SSH — er bekommt einen
    :class:`~netbuddy.adapters.transport.CommandTransport` injiziert und ist so
    ohne echte Hardware testbar.
    """

    adapter_id: ClassVar[str] = "cisco_ios"

    def __init__(self, transport: CommandTransport) -> None:
        self._transport = transport

    @classmethod
    def capabilities(cls) -> frozenset[Capability]:
        return frozenset(
            {
                Capability.READ_SYSTEM_INFO,
                Capability.READ_INTERFACES,
                Capability.READ_LLDP,
                Capability.READ_MAC_TABLE,
            }
        )

    async def _parse(self, command: str) -> list[dict[str, Any]]:
        raw = await self._transport.send_command(command)
        parsed = parse_output(platform=_PLATFORM, command=command, data=raw)
        return cast(list[dict[str, Any]], parsed)

    async def get_system_info(self) -> SystemInfo:
        rows = await self._parse("show version")
        row = rows[0] if rows else {}
        return SystemInfo(
            hostname=_or_none(row.get("hostname")) or "",
            vendor="cisco",
            model=_first(row.get("hardware")),
            os_version=_or_none(row.get("version")),
            serial_number=_first(row.get("serial")),
            device_type=DeviceType.SWITCH,
        )

    async def get_interfaces(self) -> list[InterfaceData]:
        rows = await self._parse("show interfaces")
        return [
            InterfaceData(
                name=row["interface"],
                description=_or_none(row.get("description")),
                admin_status=_admin_status(row.get("link_status", "")),
                oper_status=_oper_status(row.get("protocol_status", "")),
                mac_address=_or_none(row.get("mac_address")),
                speed_mbps=_speed_mbps(row.get("bandwidth")),
                mtu=_int_or_none(row.get("mtu")),
                interface_type=_or_none(row.get("hardware_type")),
            )
            for row in rows
        ]

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        rows = await self._parse("show lldp neighbors detail")
        return [
            LldpNeighborData(
                local_interface=row["local_interface"],
                remote_chassis_id=row.get("chassis_id", ""),
                remote_port_id=row.get("neighbor_port_id", ""),
                remote_port_description=_or_none(row.get("neighbor_interface")),
                remote_system_name=_or_none(row.get("neighbor_name")),
                remote_system_description=_or_none(row.get("neighbor_description")),
            )
            for row in rows
        ]

    async def get_mac_table(self) -> list[MacEntryData]:
        rows = await self._parse("show mac address-table")
        entries: list[MacEntryData] = []
        for row in rows:
            interface = _first(row.get("destination_port"))
            if interface is None:
                continue
            entries.append(
                MacEntryData(
                    mac_address=row["destination_address"],
                    interface=interface,
                    vlan_id=_int_or_none(row.get("vlan_id")),
                    entry_type=_entry_type(row.get("type", "")),
                )
            )
        return entries
