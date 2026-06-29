"""UniFi-Adapter über den **lokalen Controller** (`unifi_local`).

Ersetzt `unifi_cloud` (nur System-Info über die Cloud) und den toten `unifi`-API-Adapter
(Token-Auth, der den cookie-basierten Controller nicht erreicht). Datenbasis ist der lokale
UniFi-OS-Controller via :class:`netbuddy.services.unifi_local.UnifiConsole` (Cookie-Login,
``verify=False``): System-Info, Ports (``port_table`` inkl. Speed/VLAN) und MAC-Tabelle
(verkabelte Clients pro Port).

Konstruktion/Live-Zugriff laufen über den Controller-Pfad (Site → Konsolen-IP + ``UnifiLocal``-
Credential), **nicht** über ``connect()``/``HttpxApiClient`` — die Endpoints bauen den Adapter
mit einer offenen ``UnifiConsole``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

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
from netbuddy.db.models import DeviceType, MacEntryType

if TYPE_CHECKING:  # nur Typ — Laufzeit-Import in den Methoden, sonst zirkulär (services↔adapters)
    from netbuddy.services.unifi_local import UnifiConsole


@register_api_adapter
class UnifiLocalAdapter:
    """Read-only-Adapter für einen UniFi-Switch/-AP über den lokalen Controller."""

    adapter_id: str = "unifi_local"  # Instanz-kompatibel (SwitchAdapter-Protokoll), nicht ClassVar
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.READ_SYSTEM_INFO, Capability.READ_INTERFACES, Capability.READ_MAC_TABLE}
    )
    provenance: ClassVar[str] = "UniFi lokaler Controller (Cookie-Login) — live"

    def __init__(self, console: UnifiConsole, switch_ip: str, unifi_site: str = "default") -> None:
        self._con = console
        self._ip = switch_ip
        self._site = unifi_site
        self._dev: dict[str, Any] | None = None

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def _device(self) -> dict[str, Any]:
        if self._dev is None:
            dev = await self._con.device_by_ip(self._ip, self._site)
            if dev is None:
                raise AdapterError(f"UniFi-Gerät {self._ip} nicht auf dem Controller gefunden")
            self._dev = dev
        return self._dev

    async def get_system_info(self) -> SystemInfo:
        dev = await self._device()
        dtype = DeviceType.AP if str(dev.get("type")) == "uap" else DeviceType.SWITCH
        return SystemInfo(
            hostname=str(dev.get("name") or ""),
            vendor="ubiquiti",
            model=dev.get("model"),
            os_version=dev.get("version"),
            serial_number=dev.get("mac"),
            device_type=dtype,
        )

    async def get_interfaces(self) -> list[InterfaceData]:
        from netbuddy.services.unifi_local import ports_to_interfaces

        vlan_by_nc = {n.id: n.vlan for n in await self._con.networks(self._site)}
        return ports_to_interfaces(await self._device(), vlan_by_nc)

    async def get_mac_table(self) -> list[MacEntryData]:
        dev = await self._device()
        sw_mac = str(dev.get("mac") or "").lower()
        out: list[MacEntryData] = []
        for c in await self._con.clients(self._site):
            if not c.get("is_wired") or str(c.get("sw_mac") or "").lower() != sw_mac:
                continue
            port = c.get("sw_port")
            out.append(
                MacEntryData(
                    mac_address=str(c.get("mac") or ""),
                    interface=f"Port {port}" if port is not None else "",
                    vlan_id=c.get("vlan"),
                    entry_type=MacEntryType.DYNAMIC,
                )
            )
        return out

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        # Der Controller liefert LLDP-Nachbarn nicht zuverlässig pro Switch → leer (nicht „Fehler").
        return []

    async def get_arp(self) -> list[ArpData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_ARP)

    async def get_vpn_tunnels(self) -> list[VpnTunnelData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_VPN_TUNNELS)

    async def get_config(self) -> str:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_CONFIG)
