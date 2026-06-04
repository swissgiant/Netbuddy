from httpx import AsyncClient


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

    # Jedes Gerät hat eine member-Kante zum Standort
    member_edges = [e for e in topo["edges"] if e["type"] == "member"]
    assert len(member_edges) == 3
    assert all(e["target"] == f"site:{site_id}" for e in member_edges)

    # sw2 + fw existieren als Knoten
    assert f"device:{sw2.json()['id']}" in types


async def test_topology_empty(api_client: AsyncClient) -> None:
    resp = await api_client.get("/topology")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}
