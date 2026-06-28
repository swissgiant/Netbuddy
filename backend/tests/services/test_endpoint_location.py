from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    ApLocation,
    Credential,
    Device,
    DeviceType,
    Interface,
    LldpNeighbor,
    Site,
)
from netbuddy.services import endpoint_location


def _ap(name: str, mac: str, status: str = "online", model: str = "U7 Pro") -> dict[str, str]:
    return {
        "name": name,
        "mac": mac,
        "model": model,
        "ip": "",
        "productLine": "network",
        "status": status,
    }


def _groups() -> list[dict[str, Any]]:
    return [
        {
            "hostId": "h1",
            "hostName": "console",
            "devices": [
                _ap("BLS-AP-1", "d021f9600001"),  # wired, online
                _ap("BLS-AP-2", "d021f9600002", status="offline"),  # wired, offline
                _ap("BLS-AP-3", "d021f9600003"),  # gemesht (2 an einem Port)
                _ap("BLS-AP-4", "d021f9600004"),  # gemesht (2 an einem Port)
                _ap("BLS-AP-5", "aaaabbbbcccc"),  # online, kein Wired-Port
                {
                    "name": "Cam",
                    "mac": "ffff",
                    "model": "G6",
                    "productLine": "protect",
                    "status": "online",
                },  # keine AP
            ],
        }
    ]


async def _seed_switch(session: AsyncSession) -> Device:
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
    ports = {}
    for pname in ("Gi1/0/7", "Gi1/0/8", "Gi1/0/9"):
        iface = Interface(device_id=sw.id, name=pname)
        session.add(iface)
        await session.flush()
        ports[pname] = iface.id

    def nb(iface_id: Any, chassis: str, name: str) -> LldpNeighbor:
        return LldpNeighbor(
            local_device_id=sw.id,
            local_interface_id=iface_id,
            remote_chassis_id=chassis,
            remote_port_id="eth0",
            remote_system_name=name,
        )

    session.add_all(
        [
            nb(ports["Gi1/0/7"], "d0:21:f9:60:00:01", "BLS-AP-1"),
            nb(ports["Gi1/0/8"], "d0:21:f9:60:00:02", "BLS-AP-2"),
            nb(ports["Gi1/0/9"], "d0:21:f9:60:00:03", "BLS-AP-3"),
            nb(ports["Gi1/0/9"], "d0:21:f9:60:00:04", "BLS-AP-4"),
        ]
    )
    await session.commit()
    return sw


async def test_build_ap_locations(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sw = await _seed_switch(db_session)

    async def fake_groups(_cred: Credential) -> list[dict[str, Any]]:
        return _groups()

    monkeypatch.setattr(endpoint_location, "fetch_device_groups", fake_groups)
    cred = Credential(name="cloud", base_url="https://api.ui.com")

    infos = await endpoint_location.build_ap_locations(db_session, cred, persist=True)
    by_mac = {i.ap_mac: i for i in infos}

    # Kamera ist kein AP → nicht enthalten
    assert "ffff" not in by_mac and len(by_mac) == 5

    # verortet, online, kein Mesh
    a1 = by_mac["d021f9600001"]
    assert a1.device_hostname == "BLS-SW-CU" and a1.port == "Gi1/0/7"
    assert a1.source == "lldp" and a1.mesh is False

    # offline + trotzdem verortet (für Recovery wichtig)
    assert by_mac["d021f9600002"].status == "offline"
    assert by_mac["d021f9600002"].port == "Gi1/0/8"

    # zwei APs an einem Port → beide Mesh
    assert by_mac["d021f9600003"].mesh and by_mac["d021f9600004"].mesh
    assert "Port" in (by_mac["d021f9600003"].mesh_reason or "")

    # online ohne Wired-Port → Mesh-Verdacht
    a5 = by_mac["aaaabbbbcccc"]
    assert a5.port is None and a5.mesh and "Wired" in (a5.mesh_reason or "")

    # sticky persistiert
    rows = {r.ap_mac: r for r in (await db_session.execute(select(ApLocation))).scalars().all()}
    assert rows["d021f9600001"].device_id == sw.id and rows["d021f9600001"].port == "Gi1/0/7"


async def test_location_is_sticky_when_ap_goes_offline(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_switch(db_session)
    cred = Credential(name="cloud", base_url="https://api.ui.com")

    async def online(_c: Credential) -> list[dict[str, Any]]:
        return [{"hostId": "h", "hostName": "c", "devices": [_ap("BLS-AP-1", "d021f9600001")]}]

    monkeypatch.setattr(endpoint_location, "fetch_device_groups", online)
    await endpoint_location.build_ap_locations(db_session, cred, persist=True)

    # AP1 verschwindet aus LLDP (Discovery löscht es) UND geht offline …
    await db_session.execute(
        delete(LldpNeighbor).where(LldpNeighbor.remote_system_name == "BLS-AP-1")
    )
    await db_session.commit()

    async def offline(_c: Credential) -> list[dict[str, Any]]:
        return [
            {
                "hostId": "h",
                "hostName": "c",
                "devices": [_ap("BLS-AP-1", "d021f9600001", status="offline")],
            }
        ]

    monkeypatch.setattr(endpoint_location, "fetch_device_groups", offline)
    infos = await endpoint_location.build_ap_locations(db_session, cred, persist=True)

    # … der letzte bekannte Port bleibt erhalten (sticky) — auch in der Anzeige
    assert infos[0].status == "offline"
    assert infos[0].port == "Gi1/0/7"
    row = (
        await db_session.execute(select(ApLocation).where(ApLocation.ap_mac == "d021f9600001"))
    ).scalar_one()
    assert row.port == "Gi1/0/7"
