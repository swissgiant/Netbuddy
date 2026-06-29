from typing import Any, ClassVar

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
from netbuddy.db.models import DeviceType


class DeviceNotFoundError(AdapterError):
    """Das Gerät wurde im Cloud-Inventar (nach IP) nicht gefunden."""


# Nicht mehr registriert: durch `unifi_local` (lokaler Controller) ersetzt. Klasse bleibt für
# Referenz/Tests; Cloud-Inventar läuft weiter über services.unifi_inventory (UnifiHost).
class UnifiCloudAdapter:
    """Read-only-Adapter für Ubiquiti über die **UniFi Site Manager Cloud-API** (`api.ui.com`).

    Anders als der lokale ``unifi``-Adapter (Controller direkt) geht dieser über die offizielle
    Cloud: **ein** API-Key (erstellt unter unifi.ui.com) deckt **alle Standorte** ab, die VM
    braucht nur Internet-Zugang. Auth per ``X-API-KEY``. Liefert Inventar (Hosts/Sites/Geräte:
    Modell, IP, MAC, Version); ein Gerät wird per Management-IP gefiltert.

    **Unvalidiert** — Feld-Mapping nach Ubiquiti-Doku, bis echter Cloud-Zugriff vorliegt.
    Tiefe Port-/LLDP-/MAC-Details bietet die Cloud-API nicht → nur ``READ_SYSTEM_INFO``.
    """

    adapter_id: ClassVar[str] = "unifi_cloud"
    capabilities_set: ClassVar[frozenset[Capability]] = frozenset({Capability.READ_SYSTEM_INFO})
    provenance: ClassVar[str] = "UniFi Site Manager Cloud-API (api.ui.com) — unvalidiert"

    def __init__(
        self, client: ApiClient, *, match_ip: str, options: dict[str, Any] | None = None
    ) -> None:
        self._client = client
        self._match_ip = match_ip
        # Pfad überschreibbar, falls Ubiquiti zwischen /v1 und /ea wechselt.
        self._devices_path = str((options or {}).get("devices_path", "/v1/devices"))
        self._cached: dict[str, Any] | None = None

    def capabilities(self) -> frozenset[Capability]:
        return self.capabilities_set

    async def _all_devices(self) -> list[dict[str, Any]]:
        """Flache Geräteliste über alle Hosts/Sites (mit Pagination)."""
        devices: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            params = {"nextToken": token} if token else None
            payload = await self._client.get_json(self._devices_path, params=params)
            data = payload.get("data", payload) if isinstance(payload, dict) else payload
            for entry in data or []:
                # /v1/devices gruppiert je Host: {"hostId":..., "devices":[...]}.
                # Robust: verschachtelte "devices" auflösen, sonst Eintrag selbst nehmen.
                nested = entry.get("devices") if isinstance(entry, dict) else None
                if isinstance(nested, list):
                    devices.extend(d for d in nested if isinstance(d, dict))
                elif isinstance(entry, dict):
                    devices.append(entry)
            token = payload.get("nextToken") if isinstance(payload, dict) else None
            if not token:
                break
        return devices

    async def _device(self) -> dict[str, Any]:
        if self._cached is not None:
            return self._cached
        for dev in await self._all_devices():
            ip = dev.get("ip") or dev.get("ipAddress")
            if ip == self._match_ip:
                self._cached = dev
                return self._cached
        raise DeviceNotFoundError(f"Kein UniFi-Cloud-Gerät mit IP {self._match_ip}")

    @staticmethod
    def _device_type(dev: dict[str, Any]) -> DeviceType:
        blob = " ".join(
            str(dev.get(k, "")) for k in ("type", "productLine", "model", "shortname")
        ).lower()
        if "gateway" in blob or "udm" in blob or "usg" in blob or "fw" in blob:
            return DeviceType.FIREWALL
        if "ap" in blob or "access point" in blob or "uap" in blob or "u6" in blob or "u7" in blob:
            return DeviceType.AP
        return DeviceType.SWITCH

    async def get_system_info(self) -> SystemInfo:
        dev = await self._device()
        return SystemInfo(
            hostname=dev.get("name") or dev.get("hostname") or "",
            vendor="ubiquiti",
            model=dev.get("model") or dev.get("shortname"),
            os_version=dev.get("version") or dev.get("firmwareVersion"),
            serial_number=dev.get("mac") or dev.get("serial"),
            device_type=self._device_type(dev),
        )

    async def get_interfaces(self) -> list[InterfaceData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_INTERFACES)

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_LLDP)

    async def get_mac_table(self) -> list[MacEntryData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_MAC_TABLE)

    async def get_arp(self) -> list[ArpData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_ARP)

    async def get_vpn_tunnels(self) -> list[VpnTunnelData]:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_VPN_TUNNELS)

    async def get_config(self) -> str:
        raise CapabilityNotSupportedError(self.adapter_id, Capability.READ_CONFIG)
