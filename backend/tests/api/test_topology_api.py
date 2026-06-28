from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import ApLocation


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
