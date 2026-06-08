from typing import Any, ClassVar, cast

from netbuddy.adapters.api_client import ApiClient
from netbuddy.adapters.base import AdapterError, CapabilityNotSupportedError
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
)
from netbuddy.adapters.registry import register_api_adapter
from netbuddy.db.models import AdminStatus, DeviceType, MacEntryType, OperStatus


class DeviceNotFoundError(AdapterError):
    """Das Gerät wurde im Controller-Inventar (nach IP) nicht gefunden."""


@register_api_adapter
class UnifiAdapter:
    """Read-only-Adapter für Ubiquiti UniFi über die Network-Controller-API (JSON).

    Andere Klasse als die CLI-Adapter: kein `CommandTransport`/TextFSM, sondern ein
    :class:`~netbuddy.adapters.api_client.ApiClient`. Ein Controller verwaltet viele Geräte;
    dieser Adapter filtert per Management-IP auf das eine Gerät. **Unvalidiert** — Feld-Mapping
    nach öffentlicher Doku, bis echter Controller-Zugriff vorliegt.
    """

    adapter_id: ClassVar[str] = "unifi"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.READ_SYSTEM_INFO,
            Capability.READ_INTERFACES,
            Capability.READ_LLDP,
            Capability.READ_MAC_TABLE,
        }
    )
    provenance: ClassVar[str] = "UniFi Controller-API — unvalidiert (kein Controller-Zugriff)"

    def __init__(
        self, client: ApiClient, *, match_ip: str, options: dict[str, Any] | None = None
    ) -> None:
        self._client = client
        self._site = str((options or {}).get("site", "default"))
        self._match_ip = match_ip
        self._cached: dict[str, Any] | None = None

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def _device(self) -> dict[str, Any]:
        if self._cached is not None:
            return self._cached
        payload = await self._client.get_json(f"/proxy/network/api/s/{self._site}/stat/device")
        devices = payload.get("data", []) if isinstance(payload, dict) else payload
        for entry in devices:
            if entry.get("ip") == self._match_ip:
                self._cached = cast(dict[str, Any], entry)
                return self._cached
        raise DeviceNotFoundError(f"Kein UniFi-Gerät mit IP {self._match_ip} in Site {self._site}")

    async def get_system_info(self) -> SystemInfo:
        device = await self._device()
        return SystemInfo(
            hostname=device.get("name") or "",
            vendor="ubiquiti",
            model=device.get("model"),
            os_version=device.get("version"),
            serial_number=device.get("serial"),
            device_type=DeviceType.SWITCH,
        )

    async def get_interfaces(self) -> list[InterfaceData]:
        device = await self._device()
        interfaces: list[InterfaceData] = []
        for port in device.get("port_table", []):
            interfaces.append(
                InterfaceData(
                    name=port.get("name") or f"Port {port.get('port_idx')}",
                    description=port.get("name"),
                    admin_status=AdminStatus.UP if port.get("enable") else AdminStatus.DOWN,
                    oper_status=OperStatus.UP if port.get("up") else OperStatus.DOWN,
                    speed_mbps=port.get("speed") or None,
                    interface_type=port.get("media"),
                )
            )
        return interfaces

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        device = await self._device()
        neighbors: list[LldpNeighborData] = []
        for entry in device.get("lldp_table", []):
            local = entry.get("local_port_name") or f"Port {entry.get('local_port_idx')}"
            neighbors.append(
                LldpNeighborData(
                    local_interface=local,
                    remote_chassis_id=entry.get("chassis_id", ""),
                    remote_port_id=entry.get("port_id", ""),
                    remote_port_description=entry.get("port_descr"),
                    remote_system_name=entry.get("system_name"),
                    remote_system_description=entry.get("system_descr"),
                )
            )
        return neighbors

    async def get_mac_table(self) -> list[MacEntryData]:
        device = await self._device()
        entries: list[MacEntryData] = []
        # UniFi liefert gelernte MACs typ. pro Port unter "mac_table" (falls vorhanden).
        for row in device.get("mac_table", []):
            mac = row.get("mac")
            port = row.get("port_name") or row.get("port")
            if not mac or not port:
                continue
            entries.append(
                MacEntryData(
                    mac_address=mac,
                    interface=str(port),
                    vlan_id=row.get("vlan"),
                    entry_type=MacEntryType.DYNAMIC,
                )
            )
        return entries

    async def get_config(self) -> str:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_CONFIG)
