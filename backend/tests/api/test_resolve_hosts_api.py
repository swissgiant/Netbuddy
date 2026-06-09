from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.api.deps import get_host_resolver
from netbuddy.api.main import app
from netbuddy.db.models import (
    ArpEntry,
    Device,
    DeviceType,
    Interface,
    MacAddressEntry,
    MacEntryType,
)


async def _seed(db_session: AsyncSession) -> None:
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
            ArpEntry(device_id=sw.id, ip_address="10.0.0.50", mac="aabbcc112233", vlan_id=12),
        ]
    )
    await db_session.flush()


async def test_resolve_hosts_then_search_by_name(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session)

    async def _fake_resolver(ip: str) -> str | None:
        return "workstation-42.lab.local" if ip == "10.0.0.50" else None

    app.dependency_overrides[get_host_resolver] = lambda: _fake_resolver
    try:
        resp = await api_client.post("/discovery/resolve-hosts")
        assert resp.status_code == 200
        assert resp.json() == {"hosts": 1, "resolved": 1}

        hits = (await api_client.get("/search", params={"q": "workstation-42"})).json()
    finally:
        app.dependency_overrides.pop(get_host_resolver, None)

    host_hit = next(h for h in hits if h["kind"] == "host")
    assert host_hit["device_hostname"] == "sw-cu-01"
    assert host_hit["port"] == "Eth1/1/7"
    assert host_hit["ip_address"] == "10.0.0.50"
    assert host_hit["name"] == "workstation-42.lab.local"
