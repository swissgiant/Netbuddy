from typing import Any

import pytest

from netbuddy.adapters import available_adapters
from netbuddy.adapters.unifi_cloud import DeviceNotFoundError, UnifiCloudAdapter
from netbuddy.db.models import DeviceType

# /v1/devices: nach Host gruppiert, mit Pagination über nextToken.
_PAGE1: dict[str, Any] = {
    "data": [
        {
            "hostId": "h1",
            "devices": [
                {
                    "name": "BLS-SW-68",
                    "model": "USW-Pro-48",
                    "mac": "ab:cd:ef:00:11:22",
                    "ip": "10.120.10.68",
                    "version": "7.0.50",
                    "type": "usw",
                },
                {
                    "name": "AP-Lobby",
                    "model": "U6-Pro",
                    "mac": "ab:cd:ef:00:11:33",
                    "ip": "10.120.10.70",
                    "version": "6.6.0",
                    "type": "uap",
                },
            ],
        }
    ],
    "nextToken": "p2",
}
_PAGE2: dict[str, Any] = {
    "data": [
        {
            "hostId": "h2",
            "devices": [
                {
                    "name": "UDM-Pro",
                    "model": "UDM-Pro",
                    "mac": "ab:cd:ef:00:11:44",
                    "ip": "10.121.10.2",
                    "version": "4.0.0",
                    "type": "ugw",
                },
            ],
        }
    ],
    "nextToken": None,
}


class _FakeClient:
    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return _PAGE2 if params and params.get("nextToken") == "p2" else _PAGE1


def _adapter(ip: str) -> UnifiCloudAdapter:
    return UnifiCloudAdapter(_FakeClient(), match_ip=ip)


async def test_system_info_switch() -> None:
    info = await _adapter("10.120.10.68").get_system_info()
    assert info.vendor == "ubiquiti"
    assert info.model == "USW-Pro-48"
    assert info.os_version == "7.0.50"
    assert info.serial_number == "ab:cd:ef:00:11:22"
    assert info.device_type is DeviceType.SWITCH


async def test_device_type_ap() -> None:
    info = await _adapter("10.120.10.70").get_system_info()
    assert info.device_type is DeviceType.AP


async def test_device_on_second_page_via_pagination() -> None:
    # Gerät liegt erst auf Seite 2 (nextToken) und ist ein Gateway → FIREWALL
    info = await _adapter("10.121.10.2").get_system_info()
    assert info.model == "UDM-Pro"
    assert info.device_type is DeviceType.FIREWALL


async def test_unknown_ip_raises() -> None:
    with pytest.raises(DeviceNotFoundError):
        await _adapter("10.99.99.99").get_system_info()


def test_cloud_deregistered_replaced_by_unifi_local() -> None:
    # `unifi_cloud` ist deregistriert — UniFi läuft jetzt über den lokalen Controller
    # (`unifi_local`). Cloud-Inventar bleibt über services.unifi_inventory (UnifiHost).
    catalogue = available_adapters()
    assert "unifi_cloud" not in catalogue
    assert "unifi_local" in catalogue
