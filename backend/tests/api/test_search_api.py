from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    Device,
    DeviceType,
    Interface,
    LldpNeighbor,
    MacAddressEntry,
    MacEntryType,
)


async def _fixture(db_session: AsyncSession) -> Device:
    sw = Device(
        hostname="sw-cu-01",
        mgmt_ip="10.0.0.1",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    db_session.add(sw)
    await db_session.flush()
    iface = Interface(device_id=sw.id, name="Eth1/1/7")
    db_session.add(iface)
    await db_session.flush()
    db_session.add_all(
        [
            MacAddressEntry(
                device_id=sw.id,
                interface_id=iface.id,
                mac_address="aa:bb:cc:11:22:33",
                vlan_id=12,
                entry_type=MacEntryType.DYNAMIC,
            ),
            LldpNeighbor(
                local_device_id=sw.id,
                local_interface_id=iface.id,
                remote_chassis_id="b4:fb:e4:00:00:01",
                remote_port_id="eth0",
                remote_system_name="bls-ap-cu-07",
                remote_mgmt_address="10.123.12.7",
            ),
        ]
    )
    await db_session.flush()
    return sw


async def test_search_by_mac(api_client: AsyncClient, db_session: AsyncSession) -> None:
    await _fixture(db_session)
    resp = await api_client.get("/search", params={"q": "aa:bb:cc"})
    assert resp.status_code == 200
    hits = resp.json()
    mac_hit = next(h for h in hits if h["kind"] == "mac")
    assert mac_hit["device_hostname"] == "sw-cu-01"
    assert mac_hit["port"] == "Eth1/1/7"
    assert mac_hit["vlan"] == 12


async def test_search_by_name(api_client: AsyncClient, db_session: AsyncSession) -> None:
    await _fixture(db_session)
    resp = await api_client.get("/search", params={"q": "ap-cu-07"})
    hits = resp.json()
    lldp_hit = next(h for h in hits if h["kind"] == "lldp")
    assert lldp_hit["system_name"] == "bls-ap-cu-07"
    assert lldp_hit["port"] == "Eth1/1/7"
    assert lldp_hit["mgmt_address"] == "10.123.12.7"


async def test_search_by_ip(api_client: AsyncClient, db_session: AsyncSession) -> None:
    await _fixture(db_session)
    hits = (await api_client.get("/search", params={"q": "10.123.12.7"})).json()
    assert any(h["mgmt_address"] == "10.123.12.7" for h in hits)


async def test_search_empty_query_rejected(api_client: AsyncClient) -> None:
    assert (await api_client.get("/search", params={"q": ""})).status_code == 422
