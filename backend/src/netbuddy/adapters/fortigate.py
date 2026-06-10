from typing import Any, ClassVar

from netbuddy.adapters.api_client import ApiClient
from netbuddy.adapters.base import CapabilityNotSupportedError
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
from netbuddy.db.models import AdminStatus, DeviceType, OperStatus


@register_api_adapter
class FortigateAdapter:
    """Read-only-Adapter für Fortinet FortiGate über die FortiOS-REST-API (JSON).

    Die API liegt **auf der Firewall selbst** (kein Controller) — `base_url` = die FortiGate.
    Bietet `system_info`, `interfaces`, `arp` (Gateway = beste ARP-Quelle des Standorts für
    die Namensauflösung!) und `lldp` (FortiOS ≥ 7.0). MAC-Table ist hier nicht relevant.
    Live-validiert gegen FG200F / FortiOS 7.4.12 (BLS-FW1): system_info, interfaces (31),
    arp (273), vpn-tunnels (10 inkl. Selektoren); lldp lieferte dort 0 Zeilen (LLDP aus).
    """

    adapter_id: ClassVar[str] = "fortigate"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.READ_SYSTEM_INFO,
            Capability.READ_INTERFACES,
            Capability.READ_ARP,
            Capability.READ_LLDP,
            Capability.READ_VPN_TUNNELS,
        }
    )
    provenance: ClassVar[str] = (
        "FortiOS REST-API — live-validated (FG200F 7.4.12): sysinfo/interfaces/arp/vpn"
    )

    def __init__(
        self,
        client: ApiClient,
        *,
        match_ip: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self._client = client

    async def get_system_info(self) -> SystemInfo:
        status = await self._client.get_json("/api/v2/monitor/system/status")
        results = status.get("results", status) if isinstance(status, dict) else {}
        return SystemInfo(
            hostname=status.get("hostname") or results.get("hostname") or "",
            vendor="fortinet",
            model=results.get("model") or status.get("model"),
            os_version=status.get("version"),
            serial_number=status.get("serial"),
            device_type=DeviceType.FIREWALL,
        )

    async def get_interfaces(self) -> list[InterfaceData]:
        payload = await self._client.get_json("/api/v2/monitor/system/interface")
        results = payload.get("results", {}) if isinstance(payload, dict) else {}
        # FortiOS liefert ein Dict {ifname: {...}} oder eine Liste.
        rows = results.values() if isinstance(results, dict) else results
        interfaces: list[InterfaceData] = []
        for row in rows:
            interfaces.append(
                InterfaceData(
                    name=row.get("name") or row.get("id") or "",
                    description=row.get("alias") or None,
                    admin_status=AdminStatus.UP
                    if row.get("admin_status", row.get("status")) in ("up", "enable", True)
                    else AdminStatus.DOWN,
                    oper_status=OperStatus.UP if row.get("link") else OperStatus.DOWN,
                    speed_mbps=int(row["speed"]) if str(row.get("speed", "")).isdigit() else None,
                    mac_address=row.get("mac") or None,
                )
            )
        return interfaces

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        """LLDP-Nachbarn der Firewall (FortiOS ≥ 7.0: `monitor/network/lldp/neighbors`)."""
        payload = await self._client.get_json("/api/v2/monitor/network/lldp/neighbors")
        results = payload.get("results", []) if isinstance(payload, dict) else payload
        neighbors: list[LldpNeighborData] = []
        for row in results or []:
            neighbors.append(
                LldpNeighborData(
                    local_interface=row.get("port") or row.get("interface") or "",
                    remote_chassis_id=row.get("chassis_id", ""),
                    remote_port_id=row.get("port_id", ""),
                    remote_port_description=row.get("port_description") or None,
                    remote_system_name=row.get("system_name") or None,
                    remote_system_description=row.get("system_description") or None,
                    mgmt_address=row.get("mgmt_address") or row.get("mgmt_ip") or None,
                )
            )
        return neighbors

    async def get_mac_table(self) -> list[MacEntryData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_MAC_TABLE)

    async def get_config(self) -> str:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_CONFIG)

    async def get_arp(self) -> list[ArpData]:
        """ARP-Tabelle der Firewall — als Gateway kennt sie die IPs des ganzen Segments.

        Schließt die größte Lücke der Namensauflösung: L2-Switches haben (fast) kein ARP,
        die Firewall hat alles (`monitor/network/arp`).
        """
        payload = await self._client.get_json("/api/v2/monitor/network/arp")
        results = payload.get("results", []) if isinstance(payload, dict) else payload
        entries: list[ArpData] = []
        for row in results or []:
            ip = row.get("ip")
            mac = row.get("mac")
            if not ip or not mac:
                continue
            entries.append(
                ArpData(
                    ip_address=str(ip),
                    mac_address=str(mac),
                    interface=row.get("interface") or None,
                )
            )
        return entries

    async def get_vpn_tunnels(self) -> list[VpnTunnelData]:
        """IPsec-Tunnel inkl. Selektoren (`monitor/vpn/ipsec`) — Basis der Site-zu-Site-Kanten.

        FortiOS liefert je Phase-1 die Phase-2-Selektoren (proxyid) mit Quell-/Ziel-Subnetzen
        und Status; ein Tunnel gilt als up, wenn mindestens eine Phase 2 up ist.
        """
        payload = await self._client.get_json("/api/v2/monitor/vpn/ipsec")
        results = payload.get("results", []) if isinstance(payload, dict) else payload
        tunnels: list[VpnTunnelData] = []
        for row in results or []:
            proxy = row.get("proxyid") or []
            local: list[str] = []
            remote: list[str] = []
            any_up = False
            for p2 in proxy:
                any_up = any_up or p2.get("status") == "up"
                for src in p2.get("proxy_src") or []:
                    if src.get("subnet"):
                        local.append(str(src["subnet"]))
                for dst in p2.get("proxy_dst") or []:
                    if dst.get("subnet"):
                        remote.append(str(dst["subnet"]))
            tunnels.append(
                VpnTunnelData(
                    name=str(row.get("name") or row.get("p1name") or "?"),
                    remote_gateway=row.get("rgwy") or None,
                    is_up=any_up,
                    local_subnets=sorted(set(local)),
                    remote_subnets=sorted(set(remote)),
                )
            )
        return tunnels
