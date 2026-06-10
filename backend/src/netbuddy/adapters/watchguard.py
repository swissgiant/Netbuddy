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
)
from netbuddy.adapters.registry import register_api_adapter


@register_api_adapter
class WatchGuardAdapter:
    """Platzhalter-Adapter für WatchGuard Firebox (Fireware) — Standort Italien.

    Bewusst (noch) ohne Capabilities: die Fireware-REST-API verlangt einen
    **Session-Login** (POST `/login` → Session-Token), den unser tokenbasierter
    `HttpxApiClient` nicht abbildet. Der Adapter registriert den Vendor trotzdem,
    damit Geräte angelegt/zugeordnet werden können — das Frontend graut alle
    Funktionen über die Capability-Detection aus.

    Nächster Schritt (wenn die Firebox drankommt): Login-Flow im Client ergänzen,
    dann `system_info`/`interfaces`/`arp` analog FortiGate.
    """

    adapter_id: ClassVar[str] = "watchguard"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset()
    provenance: ClassVar[str] = (
        "WatchGuard Fireware — Skeleton ohne Capabilities (Session-Login-API noch nicht angebunden)"
    )

    def __init__(
        self,
        client: ApiClient,
        *,
        match_ip: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self._client = client

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def get_system_info(self) -> SystemInfo:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_SYSTEM_INFO)

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
