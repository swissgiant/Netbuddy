from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    ArpData,
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
)
from netbuddy.db.models import Credential, Device, DeviceType
from netbuddy.services.crawl import AdapterProvider, crawl, guess_adapter


class _FakeAdapter:
    adapter_id = "fake"

    def __init__(self, neighbors: list[LldpNeighborData]) -> None:
        self._neighbors = neighbors

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.READ_SYSTEM_INFO, Capability.READ_LLDP})

    async def get_system_info(self) -> SystemInfo:
        return SystemInfo(vendor="x", device_type=DeviceType.SWITCH)

    async def get_interfaces(self) -> list[InterfaceData]:
        return []

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        return self._neighbors

    async def get_mac_table(self) -> list[MacEntryData]:
        return []

    async def get_arp(self) -> list[ArpData]:
        return []

    async def get_config(self) -> str:
        return ""


# Nachbarn je Management-IP: Seed (10.0.0.1) sieht leaf-01; leaf-01 (10.0.0.2) sieht nichts Neues.
_NEIGHBORS = {
    "10.0.0.1": [
        LldpNeighborData(
            local_interface="Eth1/1/1",
            remote_chassis_id="00:11:22:33:44:55",
            remote_port_id="Eth1/1/48",
            remote_system_name="leaf-01",
            remote_system_description="Dell EMC Networking OS10",
            mgmt_address="10.0.0.2",
        )
    ],
    "10.0.0.2": [],
}


def _provider() -> AdapterProvider:
    @asynccontextmanager
    async def cm(device: Device, credential: Credential) -> AsyncIterator[_FakeAdapter]:
        yield _FakeAdapter(_NEIGHBORS.get(device.mgmt_ip, []))

    return cm


def test_guess_adapter() -> None:
    assert guess_adapter("Dell EMC Networking OS10", None) == "dell_os10"
    assert guess_adapter("Cisco IOS Software", None) == "cisco_ios"
    assert guess_adapter("ArubaOS-CX", None) == "aruba_cx"
    assert guess_adapter("etwas Unbekanntes", "dell_os6") == "dell_os6"
    assert guess_adapter(None, None) is None


async def test_crawl_adds_and_recurses(db_session: AsyncSession) -> None:
    seed = Device(
        hostname="core-sw",
        mgmt_ip="10.0.0.1",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    cred = Credential(name="disc", username="svc")
    db_session.add_all([seed, cred])
    await db_session.flush()

    report = await crawl(db_session, [seed], cred, _provider(), max_depth=2)

    assert report.seeds == 1
    assert "core-sw" in report.discovered
    assert "leaf-01" in report.discovered  # neu angelegt UND im selben Lauf gecrawlt
    assert [a.hostname for a in report.added] == ["leaf-01"]
    assert report.added[0].adapter_id == "dell_os10"  # aus system_description geraten

    leaf = (
        await db_session.execute(select(Device).where(Device.mgmt_ip == "10.0.0.2"))
    ).scalar_one()
    assert leaf.hostname == "leaf-01"
    assert leaf.site_id == seed.site_id


async def test_crawl_depth_limit(db_session: AsyncSession) -> None:
    seed = Device(
        hostname="core-sw",
        mgmt_ip="10.0.0.1",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    cred = Credential(name="disc", username="svc")
    db_session.add_all([seed, cred])
    await db_session.flush()

    # depth 0: Seed discovern, aber keine Nachbarn aufnehmen
    report = await crawl(db_session, [seed], cred, _provider(), max_depth=0)
    assert report.discovered == ["core-sw"]
    assert report.added == []
