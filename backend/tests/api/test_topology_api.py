import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import ApLocation, Device, Interface, LldpNeighbor


async def test_topology_nodes_and_edges(api_client: AsyncClient) -> None:
    site = await api_client.post("/sites", json={"name": "Cusano", "code": "CU"})
    site_id = site.json()["id"]

    sw1 = await api_client.post(
        "/devices",
        json={
            "hostname": "core-sw-01",
            "mgmt_ip": "10.0.0.1",
            "vendor": "dell",
            "adapter_id": "dell_os10",
            "site_id": site_id,
        },
    )
    sw2 = await api_client.post(
        "/devices",
        json={
            "hostname": "access-sw-02",
            "mgmt_ip": "10.0.0.2",
            "vendor": "fs",
            "adapter_id": "fs_centec",
            "site_id": site_id,
        },
    )
    fw = await api_client.post(
        "/devices",
        json={
            "hostname": "fw-cu",
            "mgmt_ip": "10.0.0.254",
            "vendor": "fortinet",
            "adapter_id": "fortigate",
            "device_type": "firewall",
            "site_id": site_id,
        },
    )

    resp = await api_client.get("/topology")
    assert resp.status_code == 200
    topo = resp.json()

    types = {n["id"]: n["type"] for n in topo["nodes"]}
    assert types[f"site:{site_id}"] == "site"
    assert types[f"device:{sw1.json()['id']}"] == "switch"
    assert types[f"device:{fw.json()['id']}"] == "firewall"

    # Compound-Modell: Geräte liegen IM Standort-Container (parent), keine member-Kanten mehr
    parents = {n["id"]: n.get("parent") for n in topo["nodes"]}
    assert parents[f"device:{sw1.json()['id']}"] == f"site:{site_id}"
    assert all(e["type"] != "member" for e in topo["edges"])

    # sw2 + fw existieren als Knoten
    assert f"device:{sw2.json()['id']}" in types


async def test_topology_mesh_ap_wireless_edge(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Mesh-AP (uplink_ap_mac gesetzt) → gestrichelte wireless-Kante zum Eltern-AP, keine Waise."""
    site = await api_client.post("/sites", json={"name": "USA", "code": "US"})
    site_id = site.json()["id"]

    async def _ap(host: str, ip: str) -> str:
        resp = await api_client.post(
            "/devices",
            json={
                "hostname": host,
                "mgmt_ip": ip,
                "vendor": "ubiquiti",
                "adapter_id": "unifi_cloud",
                "device_type": "ap",
                "site_id": site_id,
            },
        )
        return str(resp.json()["id"])

    parent_id = await _ap("ap-parent", "10.9.0.1")
    child_id = await _ap("ap-child", "10.9.0.2")

    db_session.add(ApLocation(ap_mac="aaaaaaaaaaaa", ap_name="ap-parent"))
    db_session.add(
        ApLocation(
            ap_mac="bbbbbbbbbbbb",
            ap_name="ap-child",
            mesh=True,
            uplink_ap_mac="aaaaaaaaaaaa",
        )
    )
    await db_session.flush()

    topo = (await api_client.get("/topology")).json()
    wireless = [e for e in topo["edges"] if e["type"] == "wireless"]
    assert len(wireless) == 1
    ends = {wireless[0]["source"], wireless[0]["target"]}
    assert ends == {f"device:{child_id}", f"device:{parent_id}"}
    # Mesh-AP gilt als verbunden → kein "Unbekannter Switch"-Platzhalter erzeugt.
    assert all(n["type"] != "unknown" for n in topo["nodes"])


async def test_topology_empty(api_client: AsyncClient) -> None:
    resp = await api_client.get("/topology")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}


async def test_topology_ap_lldp_uplink_core_role_and_stack(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """AP↔Switch-LLDP (beide Richtungen) → uplink-Kante; Core-Rolle; Stack-Member als Kette."""
    site = await api_client.post("/sites", json={"name": "Riese", "code": "S00"})
    site_id = site.json()["id"]

    async def _dev(host: str, ip: str, **extra: object) -> str:
        payload: dict[str, object] = {
            "hostname": host,
            "mgmt_ip": ip,
            "vendor": "cisco-meraki",
            "adapter_id": "meraki",
            "site_id": site_id,
        }
        payload.update(extra)
        resp = await api_client.post("/devices", json=payload)
        assert resp.status_code in (200, 201), resp.text
        return str(resp.json()["id"])

    core = await _dev("S00NCS101", "10.0.0.1", adapter_id="cisco_nxos", vendor="cisco")
    sw_a = await _dev("S00NSW104", "10.0.0.4")
    sw_b = await _dev("S00NSW105", "10.0.0.5")
    ap1 = await _dev("S00NAP100", "10.0.40.100", device_type="ap")
    ap2 = await _dev("S00NAP101", "10.0.40.101", device_type="ap")

    async def _lldp(local: str, local_if: str, remote: str, port: str) -> None:
        iface = Interface(device_id=uuid.UUID(local), name=local_if)
        db_session.add(iface)
        await db_session.flush()
        db_session.add(
            LldpNeighbor(
                local_device_id=uuid.UUID(local),
                local_interface_id=iface.id,
                remote_chassis_id="00:11:22:33:44:55",
                remote_port_id=port,
                remote_system_name=remote,
            )
        )

    await _lldp(sw_a, "7", "S00NAP100", "wired0")  # Switch sieht AP
    await _lldp(ap2, "wired0", "S00NSW104", "7")  # AP meldet seinen Switch (Meraki lldpCdp)
    await _lldp(sw_a, "13", "S00NCS101", "Ethernet1/25")  # Switch↔Core
    for dev_id in (sw_a, sw_b):
        dev = await db_session.get(Device, uuid.UUID(dev_id))
        assert dev is not None
        dev.stack_name = "S00 - CED HQ"
    await db_session.flush()

    topo = (await api_client.get("/topology")).json()
    roles = {n["id"]: n.get("role") for n in topo["nodes"]}
    assert roles[f"device:{core}"] == "core"
    assert roles[f"device:{sw_a}"] is None
    stacks = {n["id"]: n.get("stack") for n in topo["nodes"]}
    assert stacks[f"device:{sw_b}"] == "S00 - CED HQ"

    by_type: dict[str, set[tuple[str, str]]] = {}
    for e in topo["edges"]:
        by_type.setdefault(e["type"], set()).add((e["source"], e["target"]))
    assert (f"device:{ap1}", f"device:{sw_a}") in by_type["uplink"]
    assert (f"device:{ap2}", f"device:{sw_a}") in by_type["uplink"]
    assert (f"device:{sw_a}", f"device:{core}") in by_type["lldp"]
    assert (f"device:{sw_a}", f"device:{sw_b}") in by_type["stack"]
    # alle verbunden → kein "Unbekannter Switch"
    assert all(n["type"] != "unknown" for n in topo["nodes"])


async def test_topology_resolves_truncated_procurve_sysname(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """ProCurve-LLDP kürzt SysNames auf 22 Zeichen + "..." → eindeutiger Präfix = Kante."""
    site = await api_client.post("/sites", json={"name": "B-SI", "code": "BSI"})
    site_id = site.json()["id"]
    core = await api_client.post(
        "/devices",
        json={
            "hostname": "BSI_C_Aruba2540_48G_1",
            "mgmt_ip": "10.100.50.23",
            "vendor": "hp",
            "adapter_id": "aruba_procurve",
            "site_id": site_id,
        },
    )
    access = await api_client.post(
        "/devices",
        json={
            "hostname": "HP-5406Rzl2",
            "mgmt_ip": "10.134.63.100",
            "vendor": "hp",
            "adapter_id": "aruba_procurve",
            "site_id": site_id,
        },
    )
    access_id = uuid.UUID(access.json()["id"])
    iface = Interface(device_id=access_id, name="1/C24")
    db_session.add(iface)
    await db_session.flush()
    db_session.add(
        LldpNeighbor(
            local_device_id=access_id,
            local_interface_id=iface.id,
            remote_chassis_id="64:e8:81:a1:19:00",
            remote_port_id="49",
            remote_system_name="BSI_C_Aruba2540...",
        )
    )
    await db_session.commit()

    topo = (await api_client.get("/topology")).json()
    lldp_edges = {(e["source"], e["target"]) for e in topo["edges"] if e["type"] == "lldp"}
    assert (f"device:{access_id}", f"device:{core.json()['id']}") in lldp_edges
