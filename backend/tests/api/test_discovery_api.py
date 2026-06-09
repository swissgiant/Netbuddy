from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from httpx import AsyncClient

from netbuddy.adapters import MockTransport, SwitchAdapter, build_adapter
from netbuddy.api.deps import get_live_adapter
from netbuddy.api.main import app
from netbuddy.db.models import Credential, Device

_FIXTURES = Path(__file__).parent.parent / "adapters" / "fixtures" / "dell_os10"
_COMMANDS = {
    "show version": "show_version.txt",
    "show license status": "show_license_status.txt",
    "show interface status": "show_interface_status.txt",
    "show lldp neighbors detail": "show_lldp_neighbors_detail.txt",
    "show mac address-table": "show_mac_address-table.txt",
    "show ip arp": "show_ip_arp.txt",
}


def _fake_live_adapter() -> object:
    @asynccontextmanager
    async def _cm(device: Device, credential: Credential) -> AsyncIterator[SwitchAdapter]:
        responses = {cmd: (_FIXTURES / f).read_text() for cmd, f in _COMMANDS.items()}
        yield build_adapter(device.adapter_id, MockTransport(responses))

    return _cm


async def _device_with_cred(api_client: AsyncClient) -> str:
    cred = await api_client.post(
        "/credentials", json={"name": "svc", "username": "u", "password": "p"}
    )
    device = await api_client.post(
        "/devices",
        json={
            "hostname": "SW2",
            "mgmt_ip": "10.123.40.3",
            "vendor": "dell",
            "adapter_id": "dell_os10",
            "credential_id": cred.json()["id"],
        },
    )
    return str(device.json()["id"])


async def test_discover_persists_and_aggregates_readable(api_client: AsyncClient) -> None:
    device_id = await _device_with_cred(api_client)
    app.dependency_overrides[get_live_adapter] = _fake_live_adapter
    try:
        resp = await api_client.post(f"/devices/{device_id}/discover")
    finally:
        app.dependency_overrides.pop(get_live_adapter, None)

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["devices_found"] == 1

    interfaces = await api_client.get(f"/devices/{device_id}/interfaces")
    assert interfaces.status_code == 200
    assert any(i["name"] == "Eth 1/1/1" for i in interfaces.json())

    lldp = await api_client.get(f"/devices/{device_id}/lldp-neighbors")
    assert len(lldp.json()) == 2

    macs = await api_client.get(f"/devices/{device_id}/mac-table")
    assert len(macs.json()) == 4

    arp = await api_client.get(f"/devices/{device_id}/arp")
    assert arp.status_code == 200
    assert len(arp.json()) == 4
    assert all(len(a["mac"]) == 12 for a in arp.json())  # kanonisch


async def test_discover_without_credential_is_400(api_client: AsyncClient) -> None:
    device = await api_client.post(
        "/devices",
        json={
            "hostname": "nocred",
            "mgmt_ip": "10.0.0.9",
            "vendor": "dell",
            "adapter_id": "dell_os10",
        },
    )
    resp = await api_client.post(f"/devices/{device.json()['id']}/discover")
    assert resp.status_code == 400
