from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.scrapli_transport import ScrapliTransport
from netbuddy.api.deps import get_live_connection
from netbuddy.api.main import app
from netbuddy.db.models import (
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DeviceType,
    Interface,
    LldpNeighbor,
    PoeEvent,
    Site,
)
from netbuddy.services import endpoint_location

_POWER = """\
Port      Powered Device   State Priority Status     Class           Power[mW]
--------- ---------------- ----- -------- ---------- --------------- ---------
Gi1/0/7                    auto  Low      Fault      Unknown/Unknown
"""
_LINK = """\
Port      Description  Duplex Speed Neg  Link  Flow
Gi1/0/7                N/A    Unkn  Auto Down  Off
"""


class _FakeTransport:
    async def send_command(self, command: str) -> str:
        return _POWER if "power" in command else _LINK

    async def send_config(self, lines: list[str]) -> str:  # pragma: no cover
        return ""


def _override(transport: Any = None) -> Any:
    tx = transport or _FakeTransport()

    @asynccontextmanager
    async def cm(
        device: Device, credential: Credential
    ) -> AsyncIterator[tuple[SwitchAdapter, ScrapliTransport]]:
        yield object(), tx  # type: ignore[misc]

    return lambda: cm


class _RecoverTransport:
    """Stateful: liefert Fault/Link-down, bis ein `no shutdown`-Bounce kam → dann On/Link-up."""

    def __init__(self) -> None:
        self.recovered = False
        self.configs: list[list[str]] = []

    async def send_command(self, command: str) -> str:
        if "power" in command:
            if self.recovered:
                return "Gi1/0/7  auto  Low  On     4/4  7000\n"
            return "Gi1/0/7  auto  Low  Fault  Unknown/Unknown\n"
        link = "Up" if self.recovered else "Down"
        return f"Gi1/0/7  N/A 100 Auto {link} On\n"

    async def send_config(self, lines: list[str]) -> str:
        self.configs.append(lines)
        if any("no shutdown" in line for line in lines):
            self.recovered = True
        return "ok"


async def _seed(session: AsyncSession) -> Device:
    site = Site(name="Cusano", code="CU")
    session.add(site)
    await session.flush()
    sw = Device(
        hostname="BLS-SW-CU",
        mgmt_ip="10.121.10.7",
        vendor="dell",
        adapter_id="dell_os6",
        device_type=DeviceType.SWITCH,
        site_id=site.id,
    )
    session.add(sw)
    await session.flush()
    iface = Interface(device_id=sw.id, name="Gi1/0/7")
    session.add(iface)
    await session.flush()
    session.add(
        LldpNeighbor(
            local_device_id=sw.id,
            local_interface_id=iface.id,
            remote_chassis_id="d0:21:f9:60:00:07",
            remote_port_id="eth0",
            remote_system_name="BLS-AP-7",
        )
    )
    ssh = Credential(name="dell-ssh", username="admin")
    cloud = Credential(name="cloud", base_url="https://api.ui.com")
    session.add_all([ssh, cloud])
    await session.flush()
    session.add(
        DeviceCredential(device_id=sw.id, credential_id=ssh.id, protocol=CredentialProtocol.SSH)
    )
    await session.commit()
    return sw


def _groups_ap_offline() -> list[dict[str, Any]]:
    return [
        {
            "hostId": "h",
            "hostName": "c",
            "devices": [
                {
                    "name": "BLS-AP-7",
                    "mac": "d021f9600007",
                    "model": "U7 Pro",
                    "productLine": "network",
                    "status": "offline",
                    "ip": "",
                }
            ],
        }
    ]


async def test_poe_device_status(api_client: AsyncClient, db_session: AsyncSession) -> None:
    sw = await _seed(db_session)
    app.dependency_overrides[get_live_connection] = _override()
    try:
        resp = await api_client.get(f"/poe/devices/{sw.id}")
    finally:
        app.dependency_overrides.pop(get_live_connection, None)
    assert resp.status_code == 200
    ports = {p["port"]: p for p in resp.json()}
    assert ports["Gi1/0/7"]["poe_status"] == "Fault"
    assert ports["Gi1/0/7"]["link_up"] is False


async def test_endpoints_aps_and_stuck(
    api_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(db_session)
    monkeypatch.setattr(
        endpoint_location, "fetch_device_groups", lambda _c: _async(_groups_ap_offline())
    )
    app.dependency_overrides[get_live_connection] = _override()
    try:
        aps = (await api_client.get("/endpoints/aps?refresh=true")).json()
        assert any(a["ap_name"] == "BLS-AP-7" and a["port"] == "Gi1/0/7" for a in aps)

        stuck = (await api_client.get("/poe/stuck")).json()
    finally:
        app.dependency_overrides.pop(get_live_connection, None)
    assert len(stuck) == 1
    assert stuck[0]["hostname"] == "BLS-SW-CU"
    assert stuck[0]["port"] == "Gi1/0/7"
    assert stuck[0]["ap_name"] == "BLS-AP-7"


async def _async(value: Any) -> Any:
    return value


async def _nosleep(_seconds: float) -> None:
    return None


async def test_recover_one_bounces_port(
    api_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sw = await _seed(db_session)
    monkeypatch.setattr("netbuddy.services.poe.asyncio.sleep", _nosleep)
    tx = _RecoverTransport()
    app.dependency_overrides[get_live_connection] = _override(tx)
    try:
        resp = await api_client.post(f"/poe/devices/{sw.id}/recover", json={"port": "Gi1/0/7"})
    finally:
        app.dependency_overrides.pop(get_live_connection, None)
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "recovered"
    assert body["status_before"] == "Fault" and body["status_after"] == "On"
    # shutdown UND no shutdown wurden gesendet
    flat = [line for cfg in tx.configs for line in cfg]
    assert "shutdown" in flat and "no shutdown" in flat
    # ein PoeEvent persistiert
    events = (await db_session.execute(select(PoeEvent))).scalars().all()
    assert len(events) == 1 and events[0].action == "recovered"


async def test_recover_rate_limited(
    api_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sw = await _seed(db_session)
    # Fenster bereits ausgeschöpft (3 frische Versuche)
    for _ in range(3):
        db_session.add(PoeEvent(device_id=sw.id, port="Gi1/0/7", action="no_change"))
    await db_session.commit()

    monkeypatch.setattr("netbuddy.services.poe.asyncio.sleep", _nosleep)
    tx = _RecoverTransport()
    app.dependency_overrides[get_live_connection] = _override(tx)
    try:
        resp = await api_client.post(f"/poe/devices/{sw.id}/recover", json={"port": "Gi1/0/7"})
    finally:
        app.dependency_overrides.pop(get_live_connection, None)
    assert resp.json()["action"] == "skipped_ratelimit"
    # kein Bounce gesendet
    assert tx.configs == []
