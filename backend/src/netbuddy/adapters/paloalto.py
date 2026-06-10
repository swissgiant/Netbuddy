import xml.etree.ElementTree as ET
from typing import Any, ClassVar

from netbuddy.adapters.api_client import TextApiClient
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
from netbuddy.db.models import DeviceType, OperStatus

# PAN-OS-Op-Kommandos (XML-API, `/api/?type=op&cmd=…`); Key als Header `X-PAN-KEY`.
_CMD_SYSTEM_INFO = "<show><system><info></info></system></show>"
_CMD_ARP = "<show><arp><entry name = 'all'/></arp></show>"
_CMD_INTERFACES = "<show><interface>all</interface></show>"


def _text(node: ET.Element | None, tag: str) -> str | None:
    child = node.find(tag) if node is not None else None
    return child.text.strip() if child is not None and child.text else None


@register_api_adapter
class PaloAltoAdapter:
    """Read-only-Adapter für Palo Alto (PAN-OS) über die XML-API der Firewall.

    Auth: API-Key als Header `X-PAN-KEY` (Credential: `api_token`, `extra.auth_header`
    auf `X-PAN-KEY` setzen). **Unvalidiert** — Feld-Mapping nach PAN-OS-Doku, bis ein
    echtes Gerät vorliegt (Wunsch-Vendor laut Fleet-Plan).
    """

    adapter_id: ClassVar[str] = "paloalto"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.READ_SYSTEM_INFO, Capability.READ_INTERFACES, Capability.READ_ARP}
    )
    provenance: ClassVar[str] = "PAN-OS XML-API — unvalidiert (kein Gerät im Lab)"

    def __init__(
        self,
        client: TextApiClient,
        *,
        match_ip: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self._client = client

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def _op(self, cmd: str) -> ET.Element:
        raw = await self._client.get_text("/api/", params={"type": "op", "cmd": cmd})
        root = ET.fromstring(raw)
        if root.get("status") != "success":
            raise RuntimeError(f"PAN-OS-API-Fehler: {raw[:200]}")
        result = root.find("result")
        if result is None:
            raise RuntimeError("PAN-OS-Antwort ohne <result>")
        return result

    async def get_system_info(self) -> SystemInfo:
        system = (await self._op(_CMD_SYSTEM_INFO)).find("system")
        return SystemInfo(
            hostname=_text(system, "hostname") or "",
            vendor="paloalto",
            model=_text(system, "model"),
            os_version=_text(system, "sw-version"),
            serial_number=_text(system, "serial"),
            device_type=DeviceType.FIREWALL,
        )

    async def get_interfaces(self) -> list[InterfaceData]:
        result = await self._op(_CMD_INTERFACES)
        interfaces: list[InterfaceData] = []
        for entry in result.findall("./hw/entry"):
            name = _text(entry, "name")
            if not name:
                continue
            state = (_text(entry, "state") or "").lower()
            speed = _text(entry, "speed")
            interfaces.append(
                InterfaceData(
                    name=name,
                    oper_status=OperStatus.UP if state == "up" else OperStatus.DOWN,
                    mac_address=_text(entry, "mac"),
                    speed_mbps=int(speed) if speed and speed.isdigit() else None,
                )
            )
        return interfaces

    async def get_arp(self) -> list[ArpData]:
        result = await self._op(_CMD_ARP)
        entries: list[ArpData] = []
        for entry in result.findall("./entries/entry"):
            ip = _text(entry, "ip")
            mac = _text(entry, "mac")
            if not ip or not mac:
                continue
            entries.append(
                ArpData(ip_address=ip, mac_address=mac, interface=_text(entry, "interface"))
            )
        return entries

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_LLDP)

    async def get_mac_table(self) -> list[MacEntryData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_MAC_TABLE)

    async def get_config(self) -> str:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_CONFIG)

    async def get_vpn_tunnels(self) -> list[VpnTunnelData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_VPN_TUNNELS)
