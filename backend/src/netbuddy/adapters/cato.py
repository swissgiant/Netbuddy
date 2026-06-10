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

    Cloud-API (`base_url` = https://api.catonetworks.com), Auth-Header `x-api-key`
    (Credential: `extra.auth_header` auf `x-api-key`). Pflicht in `extra`:
    `account_id` und `site_name` (welche Site dieses „Gerät" repräsentiert).
    Cato-Sockets liefern keine Interface-/ARP-/LLDP-Sicht über die API —
    nur Stammdaten. **Unvalidiert** (kein Account im Lab).
    """

    adapter_id: ClassVar[str] = "cato"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset({Capability.READ_SYSTEM_INFO})
    provenance: ClassVar[str] = "Cato GraphQL-API — unvalidiert (kein Account im Lab)"

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

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def get_system_info(self) -> SystemInfo:
        if not self._account_id or not self._site_name:
            raise AdapterError(
                "Cato braucht extra.account_id und extra.site_name in der Credential"
            )
        payload = await self._client.post_json(
            "/api/v1/graphql",
            {"query": _QUERY_SNAPSHOT, "variables": {"accountID": self._account_id}},
        )
        sites = (
            payload.get("data", {}).get("accountSnapshot", {}).get("sites", [])
            if isinstance(payload, dict)
            else []
        )
        for site in sites:
            name = (site.get("info") or {}).get("name")
            if name != self._site_name:
                continue
            devices = site.get("devices") or []
            socket = devices[0] if devices else {}
            return SystemInfo(
                hostname=name or "",
                vendor="cato",
                model=((socket.get("socketInfo") or {}).get("model")) or "Cato Socket",
                os_version=socket.get("version"),
                serial_number=socket.get("serial"),
                device_type=DeviceType.FIREWALL,
            )
        raise SiteNotFoundError(f"Cato-Site {self._site_name!r} nicht im Account-Snapshot")

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
