from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    ArpEntry,
    Device,
    DeviceType,
    Interface,
    MacAddressEntry,
    Site,
    SiteSubnet,
)
from netbuddy.services.fw_uplink import firewall_uplinks


async def _switch(session: AsyncSession, site: Site, name: str, ip: str) -> Device:
    dev = Device(
        hostname=name,
        mgmt_ip=ip,
        vendor="x",
        adapter_id="huawei_vrp",
        device_type=DeviceType.SWITCH,
        site_id=site.id,
    )
    session.add(dev)
    await session.flush()
    return dev


async def _port_with_macs(session: AsyncSession, dev: Device, port: str, macs: list[str]) -> None:
    iface = Interface(device_id=dev.id, name=port)
    session.add(iface)
    await session.flush()
    for mac in macs:
        session.add(MacAddressEntry(device_id=dev.id, interface_id=iface.id, mac_address=mac))
    await session.flush()


async def test_direct_socket_port_detected_by_gateway_mac(db_session: AsyncSession) -> None:
    site = Site(name="B-HQ")
    db_session.add(site)
    await db_session.flush()
    db_session.add(SiteSubnet(site_id=site.id, cidr="10.131.63.0/24"))
    socket = Device(
        hostname="B-HQ-socket1",
        mgmt_ip="10.131.0.12",
        vendor="cato",
        adapter_id="cato",
        device_type=DeviceType.FIREWALL,
        site_id=site.id,
    )
    db_session.add(socket)
    core = await _switch(db_session, site, "swi-bhq-001", "10.131.63.201")
    access = await _switch(db_session, site, "swi-bhq-011", "10.131.63.211")
    await db_session.flush()
    gw = "b6:d0:04:02:00:02"
    # Core: Gateway-MAC auf Eth-Trunk27 (nur Socket-MACs) → direkt am Socket
    await _port_with_macs(db_session, core, "Eth-Trunk27", [gw, "b6:d0:04:02:00:03"])
    await _port_with_macs(
        db_session, core, "Eth-Trunk48", [f"00:50:56:84:00:{i:02x}" for i in range(40)]
    )
    # Access: Gateway-MAC auf dem Trunk Richtung Core + 200 andere → kein Direktanschluss
    await _port_with_macs(
        db_session,
        access,
        "Trk10",
        [gw] + [f"00:50:56:b2:{i // 256:02x}:{i % 256:02x}" for i in range(200)],
    )
    db_session.add(ArpEntry(device_id=core.id, ip_address="10.131.63.1", mac="b6d004020002"))
    await db_session.flush()

    ups = await firewall_uplinks(db_session, [socket, core, access])
    by_host = {u.switch_hostname: u for u in ups}
    assert by_host["swi-bhq-001"].port == "Eth-Trunk27" and by_host["swi-bhq-001"].direct
    assert by_host["swi-bhq-001"].firewall_ids == [socket.id]
    assert by_host["swi-bhq-011"].port == "Trk10" and not by_host["swi-bhq-011"].direct
    assert by_host["swi-bhq-011"].macs_on_port == 201


async def test_no_result_without_gateway_arp(db_session: AsyncSession) -> None:
    site = Site(name="B-X")
    db_session.add(site)
    await db_session.flush()
    fw = Device(
        hostname="fw",
        mgmt_ip="10.9.0.1",
        vendor="cato",
        adapter_id="cato",
        device_type=DeviceType.FIREWALL,
        site_id=site.id,
    )
    db_session.add(fw)
    sw = await _switch(db_session, site, "sw", "10.9.0.2")
    await _port_with_macs(db_session, sw, "1", ["aa:bb:cc:dd:ee:ff"])
    assert await firewall_uplinks(db_session, [fw, sw]) == []
