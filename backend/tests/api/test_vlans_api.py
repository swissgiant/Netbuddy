from httpx import AsyncClient


async def _site(api_client: AsyncClient, name: str, code: str) -> str:
    resp = await api_client.post("/sites", json={"name": name, "code": code})
    return str(resp.json()["id"])


async def test_vlan_crud_and_per_site_subnets(api_client: AsyncClient) -> None:
    sulgen = await _site(api_client, "Sulgen", "CH")
    usa = await _site(api_client, "USA", "US")

    # VLAN anlegen
    created = await api_client.post(
        "/vlans", json={"vlan_id": 101, "name": "Test-Netz 1", "description": "QA"}
    )
    assert created.status_code == 201
    vlan = created.json()
    vid = vlan["id"]
    assert vlan["vlan_id"] == 101
    assert vlan["subnets"] == []

    # gleiche VLAN-ID an zwei Standorten, je eigenes Subnetz + Gateway
    r1 = await api_client.put(
        f"/vlans/{vid}/subnets",
        json={"site_id": sulgen, "cidr": "10.120.101.0/24", "gateway": "10.120.101.1"},
    )
    assert r1.status_code == 200
    assert r1.json()["cidr"] == "10.120.101.0/24"
    assert r1.json()["site_name"] == "Sulgen"
    r2 = await api_client.put(
        f"/vlans/{vid}/subnets",
        json={"site_id": usa, "cidr": "10.122.101.0/24", "gateway": "10.122.101.1"},
    )
    assert r2.status_code == 200

    # Liste zeigt beide Subnetze
    listed = (await api_client.get("/vlans")).json()
    assert len(listed) == 1
    assert {s["cidr"] for s in listed[0]["subnets"]} == {"10.120.101.0/24", "10.122.101.0/24"}

    # Upsert: Subnetz für Sulgen ändern (kein Duplikat)
    up = await api_client.put(
        f"/vlans/{vid}/subnets",
        json={"site_id": sulgen, "cidr": "10.120.111.0/24", "gateway": "10.120.111.1"},
    )
    assert up.status_code == 200
    again = (await api_client.get("/vlans")).json()[0]
    assert len(again["subnets"]) == 2
    assert "10.120.111.0/24" in {s["cidr"] for s in again["subnets"]}

    # Subnetz löschen
    d = await api_client.delete(f"/vlans/{vid}/subnets/{usa}")
    assert d.status_code == 204
    assert len((await api_client.get("/vlans")).json()[0]["subnets"]) == 1

    # VLAN umbenennen
    patched = await api_client.patch(f"/vlans/{vid}", json={"name": "Test-Netz 1 (neu)"})
    assert patched.json()["name"] == "Test-Netz 1 (neu)"

    # VLAN löschen (cascade Subnetze)
    assert (await api_client.delete(f"/vlans/{vid}")).status_code == 204
    assert (await api_client.get("/vlans")).json() == []


async def test_vlan_id_unique_and_range(api_client: AsyncClient) -> None:
    await api_client.post("/vlans", json={"vlan_id": 200, "name": "A"})
    dup = await api_client.post("/vlans", json={"vlan_id": 200, "name": "B"})
    assert dup.status_code == 409

    too_big = await api_client.post("/vlans", json={"vlan_id": 5000, "name": "X"})
    assert too_big.status_code == 422


async def test_vlan_subnet_validation(api_client: AsyncClient) -> None:
    site = await _site(api_client, "Cusano", "CU")
    created = await api_client.post("/vlans", json={"vlan_id": 300, "name": "Net"})
    vid = created.json()["id"]

    bad_cidr = await api_client.put(
        f"/vlans/{vid}/subnets", json={"site_id": site, "cidr": "not-a-net"}
    )
    assert bad_cidr.status_code == 422

    gw_outside = await api_client.put(
        f"/vlans/{vid}/subnets",
        json={"site_id": site, "cidr": "10.0.0.0/24", "gateway": "10.0.9.1"},
    )
    assert gw_outside.status_code == 422
