from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import AsyncClient

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.dto import InterfaceData
from netbuddy.adapters.scrapli_transport import ScrapliTransport
from netbuddy.api.deps import get_live_connection
from netbuddy.api.main import app
from netbuddy.db.models import Credential, Device


class _FakeAdapter:
    adapter_id = "fs_centec"

    async def get_interfaces(self) -> list[InterfaceData]:
        return [InterfaceData(name="eth-0-1"), InterfaceData(name="vlan10")]

    async def get_config(self) -> str:
        return "hostname x\n"


class _FakeTransport:
    def __init__(self) -> None:
        self.enabled = False
        self.config_calls: list[list[str]] = []

    async def send_command(self, command: str) -> str:
        return f"LLDP function global enabled : {'YES' if self.enabled else 'NO'}\n"

    async def send_config(self, lines: list[str]) -> str:
        self.config_calls.append(lines)
        self.enabled = True
        return "ok"


def _override(transport: _FakeTransport):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def cm(
        device: Device, credential: Credential
    ) -> AsyncIterator[tuple[SwitchAdapter, ScrapliTransport]]:
        yield _FakeAdapter(), transport  # type: ignore[misc]

    return lambda: cm


async def _device_with_cred(api_client: AsyncClient) -> str:
    cred = await api_client.post("/credentials", json={"name": "fs", "username": "admin"})
    dev = await api_client.post(
        "/devices",
        json={
            "hostname": "bls-sw-53",
            "mgmt_ip": "10.120.10.53",
            "vendor": "fs",
            "adapter_id": "fs_centec",
        },
    )
    did = str(dev.json()["id"])
    await api_client.post(f"/devices/{did}/credentials", json={"credential_id": cred.json()["id"]})
    return did


async def test_lldp_status_then_enable(api_client: AsyncClient) -> None:
    did = await _device_with_cred(api_client)
    transport = _FakeTransport()
    app.dependency_overrides[get_live_connection] = _override(transport)
    try:
        status = (await api_client.post(f"/devices/{did}/lldp/status")).json()
        assert status == {"supported": True, "enabled": False}

        result = (await api_client.post(f"/devices/{did}/lldp/enable")).json()
        assert result["was_enabled"] is False
        assert result["enabled_after"] is True
        assert result["interfaces_configured"] == 1  # nur eth-0-1, nicht vlan10
        assert result["backed_up"] is True

        after = (await api_client.post(f"/devices/{did}/lldp/status")).json()
        assert after["enabled"] is True
    finally:
        app.dependency_overrides.pop(get_live_connection, None)
    # global + interface-Konfig wurde gesendet
    assert any("lldp enable" in c for c in transport.config_calls)


async def test_lldp_enable_requires_credential(api_client: AsyncClient) -> None:
    dev = await api_client.post(
        "/devices",
        json={
            "hostname": "nocred",
            "mgmt_ip": "10.0.0.9",
            "vendor": "fs",
            "adapter_id": "fs_centec",
        },
    )
    resp = await api_client.post(f"/devices/{dev.json()['id']}/lldp/enable")
    assert resp.status_code == 400
