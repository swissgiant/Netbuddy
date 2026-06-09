from httpx import AsyncClient


async def test_create_list_delete_site(api_client: AsyncClient) -> None:
    created = await api_client.post("/sites", json={"name": "Werk Süd", "code": "WS"})
    assert created.status_code == 201
    site_id = created.json()["id"]

    listed = (await api_client.get("/sites")).json()
    assert any(s["id"] == site_id and s["name"] == "Werk Süd" for s in listed)

    assert (await api_client.delete(f"/sites/{site_id}")).status_code == 204
    assert all(s["id"] != site_id for s in (await api_client.get("/sites")).json())


async def test_delete_site_blocked_while_device_attached(api_client: AsyncClient) -> None:
    site_id = (await api_client.post("/sites", json={"name": "Werk Nord"})).json()["id"]
    await api_client.post(
        "/devices",
        json={
            "hostname": "sw-n-01",
            "mgmt_ip": "10.0.0.1",
            "vendor": "dell",
            "adapter_id": "dell_os10",
            "site_id": site_id,
        },
    )
    resp = await api_client.delete(f"/sites/{site_id}")
    assert resp.status_code == 409
    assert "Gerät" in resp.json()["detail"]
