from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import AsyncClient

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.api.deps import get_live_adapter
from netbuddy.api.main import app
from netbuddy.db.models import Credential, Device

_CONFIG_V1 = "hostname sw1\ninterface eth1\n description uplink\n"
_CONFIG_V2 = "hostname sw1\ninterface eth1\n description UPLINK-CORE\n"


class _FakeAdapter:
    adapter_id = "fake"

    def __init__(self, config: str) -> None:
        self._config = config

    async def get_config(self) -> str:
        return self._config


def _provider(config: str):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def cm(device: Device, credential: Credential) -> AsyncIterator[SwitchAdapter]:
        yield _FakeAdapter(config)  # type: ignore[misc]

    return cm


async def _device_with_cred(api_client: AsyncClient) -> str:
    cred = await api_client.post("/credentials", json={"name": "svc", "username": "u"})
    dev = await api_client.post(
        "/devices",
        json={
            "hostname": "sw1",
            "mgmt_ip": "10.0.0.1",
            "vendor": "dell",
            "adapter_id": "dell_os10",
            "credential_id": cred.json()["id"],
        },
    )
    return str(dev.json()["id"])


async def test_backup_dedupe_and_diff(api_client: AsyncClient) -> None:
    device_id = await _device_with_cred(api_client)

    app.dependency_overrides[get_live_adapter] = lambda: _provider(_CONFIG_V1)
    try:
        first = await api_client.post(f"/devices/{device_id}/backup")
        # identische Konfig → nicht erneut gespeichert
        again = await api_client.post(f"/devices/{device_id}/backup")
    finally:
        app.dependency_overrides.pop(get_live_adapter, None)
    assert first.json()["changed"] is True
    assert again.json()["changed"] is False

    # geänderte Konfig → neue Sicherung
    app.dependency_overrides[get_live_adapter] = lambda: _provider(_CONFIG_V2)
    try:
        changed = await api_client.post(f"/devices/{device_id}/backup")
    finally:
        app.dependency_overrides.pop(get_live_adapter, None)
    assert changed.json()["changed"] is True

    backups = await api_client.get(f"/devices/{device_id}/backups")
    assert len(backups.json()) == 2

    diff = (await api_client.get(f"/devices/{device_id}/config-diff")).json()["diff"]
    assert "UPLINK-CORE" in diff
    assert diff.startswith("---")


async def test_backup_without_credential_400(api_client: AsyncClient) -> None:
    dev = await api_client.post(
        "/devices",
        json={"hostname": "nc", "mgmt_ip": "10.0.0.9", "vendor": "dell", "adapter_id": "dell_os10"},
    )
    resp = await api_client.post(f"/devices/{dev.json()['id']}/backup")
    assert resp.status_code == 400
