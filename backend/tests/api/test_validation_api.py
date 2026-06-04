from httpx import AsyncClient

from netbuddy.adapters.capabilities import Capability
from netbuddy.api.deps import get_device_validator
from netbuddy.api.main import app
from netbuddy.db.models import Credential, Device
from netbuddy.services.validation import (
    CapabilityReport,
    CapabilityStatus,
    DeviceValidationReport,
)


def _fake_validator() -> object:
    async def validate(
        device: Device, credential: Credential
    ) -> tuple[DeviceValidationReport, dict[str, str]]:
        report = DeviceValidationReport(
            adapter_id=device.adapter_id,
            healthy=True,
            capabilities=[
                CapabilityReport(
                    capability=Capability.READ_SYSTEM_INFO,
                    status=CapabilityStatus.OK,
                    row_count=1,
                    coverage={"model": 1.0, "hostname": 0.0},
                ),
                CapabilityReport(
                    capability=Capability.READ_INTERFACES,
                    status=CapabilityStatus.EMPTY,
                    row_count=0,
                    coverage={},
                ),
            ],
        )
        raw = {"show version": "OS Version: 10.5.2.6", "show interface status": ""}
        return report, raw

    return validate


async def _make_device_with_credential(api_client: AsyncClient) -> str:
    cred = await api_client.post(
        "/credentials",
        json={"name": "lab-svc", "username": "svc", "password": "x", "ssh_port": 22},
    )
    assert cred.status_code == 201
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
    assert device.status_code == 201
    return str(device.json()["id"])


async def test_validate_persists_status_and_returns_report(api_client: AsyncClient) -> None:
    device_id = await _make_device_with_credential(api_client)
    app.dependency_overrides[get_device_validator] = _fake_validator
    try:
        resp = await api_client.post(f"/devices/{device_id}/validate")
    finally:
        app.dependency_overrides.pop(get_device_validator, None)
    assert resp.status_code == 200
    body = resp.json()
    assert body["healthy"] is True
    assert {c["capability"] for c in body["capabilities"]} == {
        "read_system_info",
        "read_interfaces",
    }

    # persistiert + lesbar
    saved = await api_client.get(f"/devices/{device_id}/validation")
    assert saved.status_code == 200
    rows = {r["capability"]: r for r in saved.json()}
    assert rows["read_system_info"]["status"] == "ok"
    assert rows["read_interfaces"]["status"] == "empty"
    # system_info hat zwei Quellen → beide Befehle im command-Feld
    assert "show license status" in rows["read_system_info"]["command"]
    assert rows["read_system_info"]["raw_excerpt"] is not None


async def test_validate_without_credential_is_400(api_client: AsyncClient) -> None:
    device = await api_client.post(
        "/devices",
        json={
            "hostname": "nocred",
            "mgmt_ip": "10.0.0.9",
            "vendor": "dell",
            "adapter_id": "dell_os10",
        },
    )
    device_id = device.json()["id"]
    resp = await api_client.post(f"/devices/{device_id}/validate")
    assert resp.status_code == 400


async def test_adapters_endpoint_reports_validation_status(api_client: AsyncClient) -> None:
    device_id = await _make_device_with_credential(api_client)
    app.dependency_overrides[get_device_validator] = _fake_validator
    try:
        await api_client.post(f"/devices/{device_id}/validate")
    finally:
        app.dependency_overrides.pop(get_device_validator, None)

    resp = await api_client.get("/adapters")
    assert resp.status_code == 200
    dell = next(a for a in resp.json() if a["adapter_id"] == "dell_os10")
    assert dell["provenance"] is not None
    caps = {c["capability"]: c for c in dell["capabilities"]}
    assert caps["read_system_info"]["validated"] is True
    assert caps["read_system_info"]["devices_checked"] == 1
    # nie geprüfte Capability bleibt unvalidiert
    assert caps["read_lldp"]["validated"] is False


async def test_import_devices_bulk(api_client: AsyncClient) -> None:
    payload = [
        {"hostname": f"sw-{i}", "mgmt_ip": f"10.0.1.{i}", "vendor": "fs", "adapter_id": "fs_centec"}
        for i in range(3)
    ]
    resp = await api_client.post("/devices/import", json=payload)
    assert resp.status_code == 201
    assert resp.json()["created"] == 3
