from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from netbuddy.services import endpoint_location, poe_recover


class _Transport:
    """Stateful Fake: Fault/Link-down bis ein `no shutdown` kommt → dann On/Link-up."""

    def __init__(self) -> None:
        self.recovered = False

    async def send_command(self, command: str) -> str:
        if "power" in command:
            return (
                "Gi1/0/7  auto Low On 4/4 7000\n"
                if self.recovered
                else "Gi1/0/7  auto Low Fault Unknown/Unknown\n"
            )
        return f"Gi1/0/7 N/A 100 Auto {'Up' if self.recovered else 'Down'} On\n"

    async def send_config(self, lines: list[str]) -> str:
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


async def _nosleep(_s: float) -> None:
    return None


async def test_auto_recover_bounces_stuck_ap(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(db_session)
    monkeypatch.setattr("netbuddy.services.poe.asyncio.sleep", _nosleep)

    async def groups(_c: Credential) -> list[dict[str, Any]]:
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

    monkeypatch.setattr(endpoint_location, "fetch_device_groups", groups)

    transport = _Transport()

    @asynccontextmanager
    async def connection(device: Device, cred: Credential) -> AsyncIterator[tuple[Any, Any]]:
        yield object(), transport

    events = await poe_recover.auto_recover(db_session, connection, actor="worker")
    await db_session.commit()

    assert len(events) == 1 and events[0].action == "recovered"
    rows = (await db_session.execute(select(PoeEvent))).scalars().all()
    assert len(rows) == 1 and rows[0].actor == "worker" and rows[0].ap_name == "BLS-AP-7"


async def test_collect_and_recover_unifi(
    db_session: AsyncSession,
) -> None:
    from netbuddy.services import unifi_local

    site = Site(name="Cusano", code="CU")
    db_session.add(site)
    await db_session.flush()
    sw = Device(
        hostname="BLS-SW-CU-01",
        mgmt_ip="10.123.40.3",
        vendor="ubiquiti",
        adapter_id="unifi_cloud",
        device_type=DeviceType.SWITCH,
        site_id=site.id,
    )
    db_session.add(sw)
    await db_session.commit()

    async def fake_fetch(_cred: Credential) -> tuple[list[Any], list[Any]]:
        dev = unifi_local.UnifiDevice(
            site="Cusano",
            mac="aa:bb",
            type="usw",
            name="BLS-SW-CU-01",
            ip="10.123.40.3",
            poe_ports=[unifi_local.UnifiSwitchPort(port_idx=2, poe_enable=True, poe_good=False)],
        )
        return [dev], []

    cred = Credential(name="UnifiLocal", username="netbuddy", password="pw")
    cands = await poe_recover.collect_unifi_stuck(db_session, cred, fetch=fake_fetch)
    assert len(cands) == 1
    c = cands[0]
    assert (
        c.source == "unifi" and c.port_idx == 2 and c.device_id == sw.id and c.switch_mac == "aa:bb"
    )

    calls: list[tuple[str, str, int]] = []

    async def fake_pc(_cred: Credential, st: str, mac: str, port_idx: int) -> dict[str, Any]:
        calls.append((st, mac, port_idx))
        return {"meta": {"rc": "ok"}}

    event = await poe_recover.recover_unifi(db_session, cred, c, actor="op", power_cycle=fake_pc)
    await db_session.commit()
    assert event.action == "recovered" and calls == [("Cusano", "aa:bb", 2)]
    assert event.actor == "op"


async def test_auto_recover_no_cloud_credential_is_noop(
    db_session: AsyncSession,
) -> None:
    # kein Cloud-Cred angelegt → kein AP-Abgleich möglich → no-op
    @asynccontextmanager
    async def connection(device: Device, cred: Credential) -> AsyncIterator[tuple[Any, Any]]:
        yield object(), _Transport()

    events = await poe_recover.auto_recover(db_session, connection, actor="worker")
    assert events == []
