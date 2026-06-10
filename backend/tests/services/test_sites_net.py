from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import Device, DeviceType, Site, SiteSubnet, VpnTunnel
from netbuddy.services.sites_net import site_for_ip, subnet_overlaps_site


async def test_site_for_ip_longest_prefix(db_session: AsyncSession) -> None:
    sulgen = Site(name="Sulgen")
    cusano = Site(name="Cusano")
    db_session.add_all([sulgen, cusano])
    await db_session.flush()
    db_session.add_all(
        [
            SiteSubnet(site_id=sulgen.id, cidr="10.120.0.0/16"),
            SiteSubnet(site_id=cusano.id, cidr="10.123.0.0/16"),
            # spezifischeres Segment gewinnt (z.B. DMZ in Cusano innerhalb 10.120er-Raum)
            SiteSubnet(site_id=cusano.id, cidr="10.120.99.0/24"),
        ]
    )
    await db_session.flush()

    assert await site_for_ip(db_session, "10.120.10.48") == sulgen.id
    assert await site_for_ip(db_session, "10.123.4.7") == cusano.id
    assert await site_for_ip(db_session, "10.120.99.5") == cusano.id  # längster Präfix
    assert await site_for_ip(db_session, "192.168.1.1") is None
    assert await site_for_ip(db_session, "kaputt") is None


def test_subnet_overlaps_site() -> None:
    assert subnet_overlaps_site(["10.121.0.0/16"], ["10.121.0.0/16"])
    assert subnet_overlaps_site(["10.121.5.0/24"], ["10.121.0.0/16"])  # Teilmenge
    assert not subnet_overlaps_site(["192.168.0.0/24"], ["10.121.0.0/16"])
    assert not subnet_overlaps_site([], ["10.121.0.0/16"])


async def test_device_create_auto_assigns_site(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    site = Site(name="Sulgen")
    db_session.add(site)
    await db_session.flush()
    db_session.add(SiteSubnet(site_id=site.id, cidr="10.120.0.0/16"))
    await db_session.flush()

    created = await api_client.post(
        "/devices",
        json={
            "hostname": "sw-auto",
            "mgmt_ip": "10.120.10.77",
            "vendor": "fs",
            "adapter_id": "fs_centec",
        },
    )
    assert created.json()["site_id"] == str(site.id)


async def test_subnet_crud_via_api(api_client: AsyncClient) -> None:
    site = (await api_client.post("/sites", json={"name": "Grosuplje"})).json()
    sub = await api_client.post(f"/sites/{site['id']}/subnets", json={"cidr": "10.121.0.0/16"})
    assert sub.status_code == 201

    listed = (await api_client.get("/sites")).json()
    me = next(s for s in listed if s["id"] == site["id"])
    assert [x["cidr"] for x in me["subnets"]] == ["10.121.0.0/16"]

    bad = await api_client.post(f"/sites/{site['id']}/subnets", json={"cidr": "quatsch"})
    assert bad.status_code == 422

    assert (
        await api_client.delete(f"/sites/{site['id']}/subnets/{sub.json()['id']}")
    ).status_code == 204


async def test_vpn_tunnel_upsert_preserves_relevant(db_session: AsyncSession) -> None:
    from netbuddy.adapters.capabilities import Capability
    from netbuddy.adapters.dto import VpnTunnelData
    from netbuddy.services.discovery import run_discovery

    fw = Device(
        hostname="fw1",
        mgmt_ip="10.120.10.1",
        vendor="fortinet",
        device_type=DeviceType.FIREWALL,
        adapter_id="fortigate",
    )
    db_session.add(fw)
    await db_session.flush()

    class _FakeFw:
        adapter_id = "fortigate"

        def capabilities(self) -> frozenset[Capability]:
            return frozenset({Capability.READ_VPN_TUNNELS})

        async def get_vpn_tunnels(self) -> list[VpnTunnelData]:
            return [
                VpnTunnelData(name="to-grosuplje", is_up=True, remote_subnets=["10.121.0.0/16"]),
                VpnTunnelData(name="to-partner", is_up=True, remote_subnets=["198.51.100.0/24"]),
            ]

    await run_discovery(db_session, fw, _FakeFw())  # type: ignore[arg-type]
    from sqlalchemy import select

    tunnels = {t.name: t for t in (await db_session.execute(select(VpnTunnel))).scalars()}
    assert set(tunnels) == {"to-grosuplje", "to-partner"}

    # Admin schaltet den Partner-Tunnel ab → muss den nächsten Lauf überleben
    tunnels["to-partner"].relevant = False
    await db_session.flush()
    await run_discovery(db_session, fw, _FakeFw())  # type: ignore[arg-type]

    tunnels = {t.name: t for t in (await db_session.execute(select(VpnTunnel))).scalars()}
    assert tunnels["to-partner"].relevant is False
    assert tunnels["to-grosuplje"].relevant is True


async def test_topology_vpn_edge_between_sites(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    sulgen = Site(name="Sulgen")
    grosuplje = Site(name="Grosuplje")
    db_session.add_all([sulgen, grosuplje])
    await db_session.flush()
    db_session.add_all(
        [
            SiteSubnet(site_id=sulgen.id, cidr="10.120.0.0/16"),
            SiteSubnet(site_id=grosuplje.id, cidr="10.121.0.0/16"),
        ]
    )
    fw = Device(
        hostname="fw1",
        mgmt_ip="10.120.10.1",
        vendor="fortinet",
        device_type=DeviceType.FIREWALL,
        adapter_id="fortigate",
        site_id=sulgen.id,
    )
    db_session.add(fw)
    await db_session.flush()
    db_session.add_all(
        [
            VpnTunnel(
                device_id=fw.id,
                name="to-grosuplje",
                is_up=True,
                local_subnets=["10.120.0.0/16"],
                remote_subnets=["10.121.0.0/16"],
            ),
            VpnTunnel(  # Partner-Tunnel: relevant=False → KEINE Kante
                device_id=fw.id,
                name="to-partner",
                is_up=True,
                relevant=False,
                local_subnets=["10.120.0.0/16"],
                remote_subnets=["10.121.0.0/16"],
            ),
        ]
    )
    await db_session.flush()

    topo = (await api_client.get("/topology")).json()
    vpn_edges = [e for e in topo["edges"] if e["type"] == "vpn"]
    assert len(vpn_edges) == 1
    assert vpn_edges[0]["label"] == "to-grosuplje"
    assert vpn_edges[0]["up"] is True
    # Kante geht von der FIREWALL aus zum Remote-Standort
    assert vpn_edges[0]["source"] == f"device:{fw.id}"
    assert vpn_edges[0]["target"] == f"site:{grosuplje.id}"
    # Geräte liegen im Standort-Container
    fw_node = next(n for n in topo["nodes"] if n["id"] == f"device:{fw.id}")
    assert fw_node["parent"] == f"site:{sulgen.id}"
