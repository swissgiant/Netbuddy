from typing import Any, ClassVar, cast

from netbuddy.adapters.api_client import ApiClient
from netbuddy.adapters.base import AdapterError, CapabilityNotSupportedError
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    ArpData,
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
    VpnTunnelData,
)
from netbuddy.adapters.registry import register_api_adapter
from netbuddy.db.models import AdminStatus, DeviceType


class MerakiDeviceNotFoundError(AdapterError):
    """Gerät nicht in der Org-Geräteliste (nach lanIp) gefunden."""


def _meraki_neighbor_name(name: str | None) -> str | None:
    """``"Meraki MS225-48FP - S00NSW104"`` → ``"S00NSW104"``; andere Namen unverändert."""
    if not name:
        return None
    if name.startswith("Meraki ") and " - " in name:
        return name.split(" - ", 1)[1].strip() or None
    return name


def _device_type_for(model: str | None) -> DeviceType:
    """Meraki-Modellpräfix → Gerätetyp (MR = AP, MX = Firewall, MS/sonst = Switch)."""
    prefix = (model or "")[:2].upper()
    if prefix == "MR":
        return DeviceType.AP
    if prefix == "MX":
        return DeviceType.FIREWALL
    return DeviceType.SWITCH


@register_api_adapter
class MerakiAdapter:
    """Read-only-Adapter für Cisco Meraki über die Dashboard-API (cloud, JSON).

    Org-scoped: findet das Gerät per Management-IP (`lanIp`) in
    `/organizations/{org}/devices`, danach Switch-Ports + LLDP/CDP über die Seriennummer.
    Keine standardisierte MAC-Table-API → `READ_MAC_TABLE` wird nicht angeboten.
    Live-validiert gegen die Steelco-Org (Okt 2026): Geräteliste, Switch-Ports, lldpCdp.
    """

    adapter_id: ClassVar[str] = "meraki"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.READ_SYSTEM_INFO, Capability.READ_INTERFACES, Capability.READ_LLDP}
    )
    provenance: ClassVar[str] = (
        "Cisco Meraki Dashboard-API — live-validiert (Steelco-Org, MS225/MS425/MS150/MR): "
        "sysinfo/ports/lldpCdp"
    )

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
            device_type=_device_type_for(device.get("model")),
        )

    async def get_interfaces(self) -> list[InterfaceData]:
        device = await self._dev()
        if _device_type_for(device.get("model")) is not DeviceType.SWITCH:
            return []  # APs/MX haben keine Switch-Port-API (/switch/ports → 404)
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
        """LLDP-Nachbarn je Port; Ports mit nur CDP (Meraki↔Meraki) werden aus CDP ergänzt.

        Live-Format (S00, Okt 2026): Meraki-Nachbarn melden ``systemName`` als
        ``"Meraki MS225-48FP - S00NSW104"`` → der Gerätename hinter `` - `` wird als
        ``remote_system_name`` geliefert (Topologie-Match per Hostname), die Management-IP
        kommt aus ``lldp.managementAddress`` oder ``cdp.address``.
        """
        device = await self._dev()
        payload = await self._client.get_json(f"/devices/{device['serial']}/lldpCdp")
        neighbors: list[LldpNeighborData] = []
        for port_id, info in (
            payload.get("ports", {}) if isinstance(payload, dict) else {}
        ).items():
            lldp = info.get("lldp") or {} if isinstance(info, dict) else {}
            cdp = info.get("cdp") or {} if isinstance(info, dict) else {}
            if not lldp and not cdp:
                continue
            name = lldp.get("systemName") or cdp.get("deviceId")
            neighbors.append(
                LldpNeighborData(
                    local_interface=str(port_id),
                    remote_chassis_id=lldp.get("chassisId") or cdp.get("deviceId", ""),
                    remote_port_id=lldp.get("portId") or cdp.get("portId", ""),
                    remote_port_description=lldp.get("portDescription"),
                    remote_system_name=_meraki_neighbor_name(name),
                    remote_system_description=lldp.get("systemDescription") or cdp.get("platform"),
                    mgmt_address=lldp.get("managementAddress") or cdp.get("address"),
                )
            )
        return neighbors

    async def get_mac_table(self) -> list[MacEntryData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_MAC_TABLE)

    async def get_config(self) -> str:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_CONFIG)

    async def get_arp(self) -> list[ArpData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_ARP)

    async def get_vpn_tunnels(self) -> list[VpnTunnelData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_VPN_TUNNELS)
