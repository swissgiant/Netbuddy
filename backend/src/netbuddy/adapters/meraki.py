from typing import Any, ClassVar, cast

from netbuddy.adapters.api_client import ApiClient
from netbuddy.adapters.base import AdapterError, CapabilityNotSupportedError
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import InterfaceData, LldpNeighborData, MacEntryData, SystemInfo
from netbuddy.adapters.registry import register_api_adapter
from netbuddy.db.models import AdminStatus, DeviceType


class MerakiDeviceNotFoundError(AdapterError):
    """Gerät nicht in der Org-Geräteliste (nach lanIp) gefunden."""


@register_api_adapter
class MerakiAdapter:
    """Read-only-Adapter für Cisco Meraki über die Dashboard-API (cloud, JSON).

    Org-scoped: findet das Gerät per Management-IP (`lanIp`) in
    `/organizations/{org}/devices`, danach Switch-Ports + LLDP/CDP über die Seriennummer.
    Keine standardisierte MAC-Table-API → `READ_MAC_TABLE` wird nicht angeboten.
    **Unvalidiert** — Feld-Mapping nach Doku, bis echter API-Key vorliegt.
    """

    adapter_id: ClassVar[str] = "meraki"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.READ_SYSTEM_INFO, Capability.READ_INTERFACES, Capability.READ_LLDP}
    )
    provenance: ClassVar[str] = "Cisco Meraki Dashboard-API — unvalidiert (kein API-Key)"

    def __init__(
        self, client: ApiClient, *, match_ip: str, options: dict[str, Any] | None = None
    ) -> None:
        self._client = client
        self._match_ip = match_ip
        self._org_id = str((options or {}).get("org_id", ""))
        self._device: dict[str, Any] | None = None

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def _dev(self) -> dict[str, Any]:
        if self._device is not None:
            return self._device
        devices = await self._client.get_json(f"/organizations/{self._org_id}/devices")
        for entry in devices:
            if entry.get("lanIp") == self._match_ip:
                self._device = cast(dict[str, Any], entry)
                return self._device
        raise MerakiDeviceNotFoundError(f"Kein Meraki-Gerät mit lanIp {self._match_ip}")

    async def get_system_info(self) -> SystemInfo:
        device = await self._dev()
        return SystemInfo(
            hostname=device.get("name") or "",
            vendor="cisco-meraki",
            model=device.get("model"),
            os_version=device.get("firmware"),
            serial_number=device.get("serial"),
            device_type=DeviceType.SWITCH,
        )

    async def get_interfaces(self) -> list[InterfaceData]:
        device = await self._dev()
        ports = await self._client.get_json(f"/devices/{device['serial']}/switch/ports")
        interfaces: list[InterfaceData] = []
        for port in ports:
            port_id = str(port.get("portId"))
            interfaces.append(
                InterfaceData(
                    name=port.get("name") or f"Port {port_id}",
                    description=port.get("name"),
                    admin_status=AdminStatus.UP if port.get("enabled") else AdminStatus.DOWN,
                    interface_type=port.get("type"),
                )
            )
        return interfaces

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        device = await self._dev()
        payload = await self._client.get_json(f"/devices/{device['serial']}/lldpCdp")
        neighbors: list[LldpNeighborData] = []
        for port_id, info in (
            payload.get("ports", {}) if isinstance(payload, dict) else {}
        ).items():
            lldp = info.get("lldp", {}) if isinstance(info, dict) else {}
            if not lldp:
                continue
            neighbors.append(
                LldpNeighborData(
                    local_interface=str(port_id),
                    remote_chassis_id=lldp.get("chassisId", ""),
                    remote_port_id=lldp.get("portId", ""),
                    remote_system_name=lldp.get("systemName"),
                    remote_system_description=lldp.get("systemDescription"),
                )
            )
        return neighbors

    async def get_mac_table(self) -> list[MacEntryData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_MAC_TABLE)
