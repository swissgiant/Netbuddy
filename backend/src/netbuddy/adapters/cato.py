from typing import Any, ClassVar

from netbuddy.adapters.api_client import GraphqlApiClient
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
from netbuddy.db.models import DeviceType

# Cato-GraphQL: Socket-/Site-Stammdaten aus dem accountSnapshot.
_QUERY_SNAPSHOT = """
query snapshot($accountID: ID!) {
  accountSnapshot(accountID: $accountID) {
    sites { id info { name } devices { id name serial version socketInfo { model } } }
  }
}
"""


class SiteNotFoundError(AdapterError):
    """Die konfigurierte Cato-Site wurde im Account-Snapshot nicht gefunden."""


@register_api_adapter
class CatoAdapter:
    """Read-only-Adapter für Cato Networks (Cloud-SASE) über die GraphQL-API.

    Cloud-API (`base_url` = https://api.catonetworks.com, Endpoint `/api/v1/graphql2`),
    Auth-Header `x-api-key`. Pflicht in `extra`: `account_id`. Die Site wird über
    `extra.site_name` gewählt, sonst über die Socket-LAN-IP (= `device.mgmt_ip`, so legt
    `services.cato_inventory.sync_sites` die Socket-Devices an). Cato-Sockets liefern keine
    Interface-/ARP-/LLDP-Sicht über die API — nur Stammdaten; Netze/Geräte-Inventar kommen
    über `services.cato_inventory`.
    """

    adapter_id: ClassVar[str] = "cato"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset({Capability.READ_SYSTEM_INFO})
    provenance: ClassVar[str] = "Cato GraphQL-API (accountSnapshot) — Socket-Stammdaten"

    def __init__(
        self,
        client: GraphqlApiClient,
        *,
        match_ip: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        opts = options or {}
        self._account_id = str(opts.get("account_id", ""))
        self._site_name = str(opts.get("site_name", ""))
        self._match_ip = match_ip

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def get_system_info(self) -> SystemInfo:
        if not self._account_id or not (self._site_name or self._match_ip):
            raise AdapterError(
                "Cato braucht extra.account_id (und extra.site_name oder eine Socket-IP)"
            )
        payload = await self._client.post_json(
            "/api/v1/graphql2",
            {"query": _QUERY_SNAPSHOT, "variables": {"accountID": self._account_id}},
        )
        sites = (
            payload.get("data", {}).get("accountSnapshot", {}).get("sites", [])
            if isinstance(payload, dict)
            else []
        )
        for site in sites:
            name = (site.get("info") or {}).get("name")
            devices = site.get("devices") or []
            socket: dict[str, Any] | None = None
            if self._site_name:
                if name == self._site_name:
                    socket = devices[0] if devices else {}
            else:
                socket = next((d for d in devices if d.get("internalIP") == self._match_ip), None)
            if socket is None:
                continue
            info = socket.get("socketInfo") or {}
            return SystemInfo(
                hostname=socket.get("name") or name or "",
                vendor="cato",
                model=info.get("platform") or "Cato Socket",
                os_version=socket.get("version") or info.get("version"),
                serial_number=info.get("serial"),
                device_type=DeviceType.FIREWALL,
            )
        wanted = self._site_name or f"Socket {self._match_ip}"
        raise SiteNotFoundError(f"Cato-Site {wanted!r} nicht im Account-Snapshot")

    async def get_interfaces(self) -> list[InterfaceData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_INTERFACES)

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_LLDP)

    async def get_mac_table(self) -> list[MacEntryData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_MAC_TABLE)

    async def get_arp(self) -> list[ArpData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_ARP)

    async def get_config(self) -> str:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_CONFIG)

    async def get_vpn_tunnels(self) -> list[VpnTunnelData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_VPN_TUNNELS)
