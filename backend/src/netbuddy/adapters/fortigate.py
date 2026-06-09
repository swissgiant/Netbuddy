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
from netbuddy.db.models import AdminStatus, DeviceType, OperStatus


@register_api_adapter
class FortigateAdapter:
    """Read-only-Adapter für Fortinet FortiGate über die FortiOS-REST-API (JSON).

    Die API liegt **auf der Firewall selbst** (kein Controller) — `base_url` = die FortiGate.
    Firewall-Geräteklasse: bietet `system_info` + `interfaces`; LLDP/MAC sind hier nicht relevant.
    **Unvalidiert** — Feld-Mapping nach FortiOS-Doku, bis echter API-Token vorliegt.
    """

    adapter_id: ClassVar[str] = "fortigate"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.READ_SYSTEM_INFO, Capability.READ_INTERFACES}
    )
    provenance: ClassVar[str] = "FortiOS REST-API — unvalidiert (kein API-Token)"

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
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_LLDP)

    async def get_mac_table(self) -> list[MacEntryData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_MAC_TABLE)

    async def get_config(self) -> str:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_CONFIG)

    async def get_arp(self) -> list[ArpData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_ARP)
