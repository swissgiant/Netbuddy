from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import Device, DeviceType, Interface, LldpNeighbor


async def test_create_delete_device(api_client: AsyncClient) -> None:
    created = await api_client.post(
        "/devices",
        json={
            "hostname": "sw-x",
            "mgmt_ip": "10.0.0.7",
            "vendor": "dell",
            "adapter_id": "dell_os10",
        },
    )
    assert created.status_code == 201
    device_id = created.json()["id"]
    assert created.json()["site_id"] is None

    assert (await api_client.get("/devices")).json()
    assert (await api_client.delete(f"/devices/{device_id}")).status_code == 204
    assert all(d["id"] != device_id for d in (await api_client.get("/devices")).json())


async def test_create_delete_credential(api_client: AsyncClient) -> None:
    cred = await api_client.post("/credentials", json={"name": "c1", "username": "u"})
    cid = cred.json()["id"]
    assert (await api_client.delete(f"/credentials/{cid}")).status_code == 204
    assert all(c["id"] != cid for c in (await api_client.get("/credentials")).json())
    assert (await api_client.delete(f"/credentials/{cid}")).status_code == 404


async def test_lldp_suggestions(api_client: AsyncClient, db_session: AsyncSession) -> None:
    known = Device(
        hostname="core-sw",
        mgmt_ip="10.0.0.1",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    db_session.add(known)
    await db_session.flush()
    iface = Interface(device_id=known.id, name="Eth1/1/1")
    db_session.add(iface)
    await db_session.flush()
    # ein unbekannter Nachbar (Vorschlag) + ein bekannter (kein Vorschlag)
    db_session.add_all(
        [
            LldpNeighbor(
                local_device_id=known.id,
                local_interface_id=iface.id,
                remote_chassis_id="aa:bb:cc:00:00:01",
                remote_port_id="Gi0/1",
                remote_system_name="new-access-sw",
                remote_system_description="Dell OS10",
            ),
            LldpNeighbor(
                local_device_id=known.id,
                local_interface_id=iface.id,
                remote_chassis_id="aa:bb:cc:00:00:02",
                remote_port_id="Gi0/2",
                remote_system_name="core-sw",
                remote_system_description="self-known",
            ),
        ]
    )
    await db_session.flush()

    resp = await api_client.get("/discovery/suggestions")
    assert resp.status_code == 200
    suggestions = resp.json()
    names = {s["name"] for s in suggestions}
    assert "new-access-sw" in names
    assert "core-sw" not in names  # bereits im Inventar
    sug = next(s for s in suggestions if s["name"] == "new-access-sw")
    assert sug["sources"] == ["lldp"]
    assert sug["seen_on"] == ["core-sw / Eth1/1/1"]
    assert sug["guessed_adapter"] == "dell_os10"  # aus "Dell OS10" geraten


async def test_patch_device_updates_fields(api_client: AsyncClient) -> None:
    site = (await api_client.post("/sites", json={"name": "Werk Süd"})).json()
    created = await api_client.post(
        "/devices",
        json={"hostname": "wrong", "mgmt_ip": "10.0.0.99", "vendor": "", "adapter_id": ""},
    )
    did = created.json()["id"]

    patched = await api_client.patch(
        f"/devices/{did}",
        json={
            "hostname": "core-2",
            "mgmt_ip": "10.0.0.5",
            "adapter_id": "dell_os10",
            "site_id": site["id"],
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["hostname"] == "core-2"
    assert body["mgmt_ip"] == "10.0.0.5"
    assert body["adapter_id"] == "dell_os10"
    assert body["site_id"] == site["id"]

    # site_id explizit leeren
    cleared = await api_client.patch(f"/devices/{did}", json={"site_id": None})
    assert cleared.json()["site_id"] is None


async def test_device_credential_link_unlink(api_client: AsyncClient) -> None:
    cred = await api_client.post("/credentials", json={"name": "lab", "username": "u"})
    cid = cred.json()["id"]
    dev = await api_client.post(
        "/devices",
        json={
            "hostname": "sw-link",
            "mgmt_ip": "10.0.0.8",
            "vendor": "dell",
            "adapter_id": "dell_os10",
        },
    )
    did = dev.json()["id"]

    link = await api_client.post(
        f"/devices/{did}/credentials", json={"credential_id": cid, "protocol": "ssh"}
    )
    assert link.status_code == 201
    # idempotent
    assert (
        await api_client.post(f"/devices/{did}/credentials", json={"credential_id": cid})
    ).status_code == 201

    rows = (await api_client.get("/device-credentials")).json()
    mine = [r for r in rows if r["device_id"] == did]
    assert len(mine) == 1
    assert mine[0]["credential_name"] == "lab"
    assert mine[0]["protocol"] == "ssh"

    assert (
        await api_client.delete(f"/devices/{did}/credentials/{cid}?protocol=ssh")
    ).status_code == 204
    rows2 = [
        r for r in (await api_client.get("/device-credentials")).json() if r["device_id"] == did
    ]
    assert rows2 == []
