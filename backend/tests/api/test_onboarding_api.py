from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import AsyncClient

from netbuddy.adapters import MockTransport
from netbuddy.adapters.transport import CommandTransport
from netbuddy.api.deps import get_onboarding_transport
from netbuddy.api.main import app
from netbuddy.db.models import Credential, Device

_RESPONSES = {
    "show ?": "  version  status\n  interface  ports\n  lldp  neighbors\n  mac  table\n",
    "show version": "Model X v1",
    "show interface": "Gi0/1 up",
    "show lldp": "neighbor core",
    "show mac": "vlan 1 aabb.ccdd.eeff Gi0/1",
}


def _fake_transport_factory() -> object:
    @asynccontextmanager
    async def _cm(device: Device, credential: Credential) -> AsyncIterator[CommandTransport]:
        yield MockTransport(_RESPONSES)

    return _cm


async def test_suggest_profile_endpoint(api_client: AsyncClient) -> None:
    cred = await api_client.post(
        "/credentials", json={"name": "svc", "username": "u", "password": "p"}
    )
    device = await api_client.post(
        "/devices",
        json={
            "hostname": "new-sw",
            "mgmt_ip": "10.9.9.9",
            "vendor": "unknown",
            "adapter_id": "cisco_ios",
            "credential_id": cred.json()["id"],
        },
    )
    device_id = device.json()["id"]

    app.dependency_overrides[get_onboarding_transport] = _fake_transport_factory
    try:
        resp = await api_client.post(f"/devices/{device_id}/suggest-profile")
    finally:
        app.dependency_overrides.pop(get_onboarding_transport, None)

    assert resp.status_code == 200
    caps = {c["capability"]: c for c in resp.json()["capabilities"]}
    assert caps["read_system_info"]["command"] == "show version"
    assert caps["read_system_info"]["raw_excerpt"] == "Model X v1"
