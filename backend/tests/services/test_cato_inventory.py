from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    Credential,
    Device,
    DeviceCredential,
    DeviceType,
    Site,
    SiteSubnet,
)
from netbuddy.services.cato_inventory import (
    CatoDevice,
    infra_candidates,
    parse_devices,
    parse_ranges,
    parse_sites,
    sync_sites,
)

_SNAPSHOT: dict[str, Any] = {
    "accountSnapshot": {
        "sites": [
            {
                "id": "101",
                "connectivityStatus": "connected",
                "popName": "Milan",
                "hostCount": 240,
                "info": {
                    "name": "Steelco HQ",
                    "type": "BRANCH",
                    "connType": "SOCKET_X1700",
                    "isHA": True,
                    "sockets": [
                        {
                            "id": "s1",
                            "serial": "SN-PRI",
                            "isPrimary": True,
                            "platform": "X1700",
                            "version": "22.0",
                        },
                        {
                            "id": "s2",
                            "serial": "SN-SEC",
                            "isPrimary": False,
                            "platform": "X1700",
                            "version": "22.0",
                        },
                    ],
                },
                "devices": [
                    {
                        "id": "d1",
                        "name": "s00fw1",
                        "connected": True,
                        "haRole": "PRIMARY",
                        "internalIP": "10.137.0.13",
                        "version": "22.0.18",
                        "socketInfo": {
                            "serial": "SN-PRI",
                            "platform": "X1700",
                            "version": "22.0",
                            "isPrimary": True,
                        },
                    },
                    {
                        "id": "d2",
                        "name": "s00fw2",
                        "connected": False,
                        "haRole": "SECONDARY",
                        "internalIP": "10.137.0.12",
                        "version": "22.0.18",
                        "socketInfo": {
                            "serial": "SN-SEC",
                            "platform": "X1700",
                            "version": "22.0",
                            "isPrimary": False,
                        },
                    },
                ],
            },
            {
                "id": "102",
                "connectivityStatus": "connected",
                "popName": "Zurich",
                "hostCount": 0,
                "info": {
                    "name": "HQ",
                    "type": "BRANCH",
                    "connType": "IPSEC_V2",
                    "isHA": False,
                    "sockets": [],
                },
                "devices": [],
            },
        ]
    }
}

_RANGES: dict[str, Any] = {
    "site": {
        "networkRangeList": {
            "items": [
                {
                    "networkRangeId": "r1",
                    "name": "Server",
                    "rangeType": "VLAN",
                    "subnet": "10.137.62.0/24",
                    "localIp": "10.137.62.1",
                    "gateway": None,
                    "vlan": 1062,
                    "dhcpSettings": {
                        "dhcpType": "DHCP_RANGE",
                        "ipRange": "10.137.62.100-10.137.62.200",
                    },
                    "internetOnly": False,
                },
                {
                    "networkRangeId": "r2",
                    "name": "Native",
                    "rangeType": "Native",
                    "subnet": "10.137.0.0/28",
                    "localIp": "10.137.0.14",
                    "vlan": None,
                    "dhcpSettings": None,
                },
            ],
            "total": 2,
        }
    }
}

_DEVICES: dict[str, Any] = {
    "devices": {
        "list": {
            "device": [
                {
                    "id": "x1",
                    "name": "S00NSW120",
                    "ip": "10.137.63.20",
                    "category": "Network Equipment",
                    "lastSeen": "2026-10-09T06:00:00Z",
                    "site": {"id": "101", "name": "Steelco HQ"},
                    "nic": {
                        "macAddress": "98:18:88:aa:bb:cc",
                        "ip": "10.137.63.20",
                        "vendor": "Cisco Meraki",
                    },
                    "os": {"product": None, "vendor": None, "version": None},
                    "hw": {"type": "Switch", "model": "MS225-48", "manufacturer": "Cisco Meraki"},
                    "network": {"subnet": "10.137.63.0/24", "networkName": "Mgmt"},
                },
                {
                    "id": "x2",
                    "name": "LAPTOP-1",
                    "ip": "10.137.41.50",
                    "category": "Computer",
                    "site": {"id": "101", "name": "Steelco HQ"},
                    "nic": {
                        "macAddress": "f4:8e:38:00:00:01",
                        "ip": "10.137.41.50",
                        "vendor": "Dell Inc.",
                    },
                    "os": {"product": "Windows 11", "vendor": "Microsoft", "version": "23H2"},
                    "hw": {"type": "Laptop", "model": "Latitude", "manufacturer": "Dell"},
                    "network": {"subnet": "10.137.41.0/24", "networkName": "Office"},
                },
                {
                    "id": "x3",
                    "name": None,
                    "ip": "10.137.63.5",
                    "category": None,
                    "site": {"id": "101", "name": "Steelco HQ"},
                    "nic": {
                        "macAddress": "00:09:0f:11:22:33",
                        "ip": "10.137.63.5",
                        "vendor": "Fortinet",
                    },
                    "os": None,
                    "hw": None,
                    "network": None,
                },
            ],
            "paging": {"total": 3},
        }
    }
}


def test_parse_sites_merges_socket_runtime_and_master_data() -> None:
    sites = parse_sites(_SNAPSHOT)
    assert [s.name for s in sites] == ["Steelco HQ", "HQ"]
    hq = sites[0]
    assert hq.connectivity == "connected" and hq.is_ha and hq.pop == "Milan"
    assert {s.serial: s.internal_ip for s in hq.sockets} == {
        "SN-PRI": "10.137.0.13",
        "SN-SEC": "10.137.0.12",
    }
    assert hq.sockets[0].name == "s00fw1" and hq.sockets[0].platform == "X1700"
    assert hq.sockets[1].connected is False
    assert sites[1].sockets == []


def test_parse_ranges_and_devices() -> None:
    ranges = parse_ranges(_RANGES)
    assert ranges[0].subnet == "10.137.62.0/24" and ranges[0].vlan == 1062
    assert ranges[0].dhcp_range == "10.137.62.100-10.137.62.200"
    assert ranges[1].vlan is None and ranges[1].local_ip == "10.137.0.14"
    devices, total = parse_devices(_DEVICES)
    assert total == 3 and len(devices) == 3
    assert devices[0].hw_type == "Switch" and devices[0].mac == "98:18:88:aa:bb:cc"
    assert devices[1].os == "Microsoft Windows 11 23H2"
    assert devices[2].nic_vendor == "Fortinet" and devices[2].hw_type is None


async def test_sync_sites_dry_run_then_apply(db_session: AsyncSession) -> None:
    cred = Credential(
        name="CatoCloud",
        base_url="https://api.catonetworks.com",
        api_token="k",
        extra={"account_id": "42", "site_map": {"HQ": "Sulgen"}},
    )
    sulgen = Site(name="Sulgen", code="CH")
    db_session.add_all([cred, sulgen])
    await db_session.flush()
    db_session.add(SiteSubnet(site_id=sulgen.id, cidr="10.120.0.0/16"))
    await db_session.flush()

    sites = parse_sites(_SNAPSHOT)
    sites[0].ranges = parse_ranges(_RANGES)

    preview = await sync_sites(db_session, cred, sites, dry_run=True)
    assert preview.dry_run
    assert preview.sites_created == ["Steelco HQ"]
    assert preview.sites_matched == ["HQ → Sulgen (site_map)"]
    assert len(preview.subnets_created) == 2 and preview.sockets_created == 2
    # Vorschau hat nichts angelegt
    none = (await db_session.execute(select(Site).where(Site.name == "Steelco HQ"))).scalar()
    assert none is None
    assert (await db_session.execute(select(Device))).scalars().all() == []

    applied = await sync_sites(db_session, cred, sites, dry_run=False)
    assert not applied.dry_run and applied.sockets_created == 2
    site = (await db_session.execute(select(Site).where(Site.name == "Steelco HQ"))).scalar_one()
    subs = await db_session.execute(select(SiteSubnet).where(SiteSubnet.site_id == site.id))
    cidrs = {str(s.cidr) for s in subs.scalars()}
    assert cidrs == {"10.137.62.0/24", "10.137.0.0/28"}
    socks = (await db_session.execute(select(Device).order_by(Device.hostname))).scalars().all()
    assert [(d.hostname, str(d.mgmt_ip), d.adapter_id, d.serial_number) for d in socks] == [
        ("s00fw1", "10.137.0.13", "cato", "SN-PRI"),
        ("s00fw2", "10.137.0.12", "cato", "SN-SEC"),
    ]
    assert all(d.site_id == site.id for d in socks)
    links = (await db_session.execute(select(DeviceCredential))).scalars().all()
    assert {link.device_id for link in links} == {d.id for d in socks}

    # Zweiter Lauf: idempotent (Segmente vorhanden, Sockets nur aktualisiert)
    again = await sync_sites(db_session, cred, sites, dry_run=False)
    assert again.sites_created == [] and again.subnets_created == []
    assert again.subnets_existing == 2
    assert again.sockets_created == 0 and again.sockets_updated == 2
    assert len((await db_session.execute(select(Device))).scalars().all()) == 2


async def test_sync_sites_matches_by_subnet_overlap_and_reports_conflict(
    db_session: AsyncSession,
) -> None:
    cred = Credential(
        name="CatoCloud", base_url="https://api.catonetworks.com", extra={"account_id": "42"}
    )
    riese = Site(name="S00 - Steelco HQ")
    other = Site(name="Woanders")
    db_session.add_all([cred, riese, other])
    await db_session.flush()
    db_session.add_all(
        [
            SiteSubnet(site_id=riese.id, cidr="10.137.0.0/16"),
            SiteSubnet(site_id=other.id, cidr="10.137.62.0/24"),
        ]
    )
    await db_session.flush()
    sites = parse_sites(_SNAPSHOT)[:1]
    sites[0].ranges = parse_ranges(_RANGES)
    report = await sync_sites(db_session, cred, sites, dry_run=True)
    assert report.sites_created == []
    assert report.sites_matched == ["Steelco HQ → S00 - Steelco HQ (subnetz 10.137.0.0/16)"]
    assert report.subnets_conflict == ["10.137.62.0/24 (Steelco HQ) liegt schon bei Woanders"]
    assert report.subnets_created == ["10.137.0.0/28 — Cato Steelco HQ: Native"]


async def test_infra_candidates_filters_and_marks_known(db_session: AsyncSession) -> None:
    db_session.add(
        Device(
            hostname="S00NSW120",
            mgmt_ip="10.137.63.20",
            vendor="meraki",
            adapter_id="meraki",
            device_type=DeviceType.SWITCH,
        )
    )
    await db_session.flush()
    devices, _ = parse_devices(_DEVICES)
    cands = await infra_candidates(db_session, devices)
    assert [(c.ip, c.reason) for c in cands] == [
        ("10.137.63.5", "hersteller"),
        ("10.137.63.20", "typ"),
    ]
    assert cands[1].known_device_id is not None and cands[0].known_device_id is None
    assert cands[0].guessed_adapter == "fortigate"
    assert cands[1].guessed_adapter == "meraki"
    everything = await infra_candidates(db_session, devices, infra_only=False)
    assert len(everything) == 3 and {c.reason for c in everything} == {"typ", "hersteller", "-"}


def test_dell_laptop_is_not_infra() -> None:
    d = CatoDevice(
        id="1",
        name="PC",
        ip="10.1.1.1",
        mac="f4:8e:38:00:00:01",
        nic_vendor="Dell Inc.",
        site=None,
        network_name=None,
        subnet=None,
        hw_type="Laptop",
        hw_model=None,
        manufacturer="Dell",
        os="Windows",
        category="Computer",
        first_seen=None,
        last_seen=None,
        is_managed=None,
    )
    from netbuddy.services.cato_inventory import _infra_reason

    assert _infra_reason(d) is None
