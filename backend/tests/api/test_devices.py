from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import Device, DeviceType


def _make_device(hostname: str, mgmt_ip: str) -> Device:
    return Device(
        hostname=hostname,
        mgmt_ip=mgmt_ip,
        vendor="cisco",
        device_type=DeviceType.SWITCH,
        adapter_id="cisco_ios",
    )


async def test_list_devices_empty(api_client: AsyncClient) -> None:
    response = await api_client.get("/devices")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_devices_returns_active_sorted(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_device("sw-zulu", "10.0.0.2"),
            _make_device("sw-alpha", "10.0.0.1"),
        ]
    )
    await db_session.flush()

    response = await api_client.get("/devices")
    assert response.status_code == 200
    body = response.json()
    assert [d["hostname"] for d in body] == ["sw-alpha", "sw-zulu"]
    assert body[0]["device_type"] == "switch"
    assert body[0]["capabilities"] == []
    assert body[0]["enabled"] is True


async def test_list_devices_excludes_soft_deleted(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    active = _make_device("sw-active", "10.0.0.1")
    deleted = _make_device("sw-deleted", "10.0.0.2")
    deleted.deleted_at = datetime.now(UTC)
    db_session.add_all([active, deleted])
    await db_session.flush()

    response = await api_client.get("/devices")
    assert response.status_code == 200
    hostnames = [d["hostname"] for d in response.json()]
    assert hostnames == ["sw-active"]


async def test_get_device_by_id(api_client: AsyncClient, db_session: AsyncSession) -> None:
    device = _make_device("sw1", "10.0.0.1")
    db_session.add(device)
    await db_session.flush()

    response = await api_client.get(f"/devices/{device.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(device.id)
    assert response.json()["hostname"] == "sw1"


async def test_get_device_not_found(api_client: AsyncClient) -> None:
    response = await api_client.get("/devices/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_get_soft_deleted_device_returns_404(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    device = _make_device("sw-gone", "10.0.0.1")
    device.deleted_at = datetime.now(UTC)
    db_session.add(device)
    await db_session.flush()

    response = await api_client.get(f"/devices/{device.id}")
    assert response.status_code == 404
