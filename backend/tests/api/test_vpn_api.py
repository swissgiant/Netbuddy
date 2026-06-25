from httpx import AsyncClient

_SPEC = {
    "name": "GROSU-CUSANO",
    "end_a": {
        "site": "Grosuplje",
        "device_id": "dev-a",
        "wan_interface": "wan1",
        "peer_public_ip": "203.0.113.2",
        "local_subnets": ["10.121.0.0/16"],
        "lan_interface": "lan",
    },
    "end_b": {
        "site": "Cusano",
        "device_id": "dev-b",
        "wan_interface": "wan1",
        "peer_public_ip": "203.0.113.1",
        "local_subnets": ["10.123.0.0/16"],
        "lan_interface": "internal",
    },
}


async def test_vpn_plan_dry_run_masks_psk(api_client: AsyncClient) -> None:
    resp = await api_client.post("/vpn/plan", json=_SPEC)
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["tunnel_name"] == "GROSU-CUSANO"
    assert plan["psk_generated"] is True
    assert len(plan["firewalls"]) == 2
    # PSK muss in der Vorschau maskiert sein — niemals im Klartext zurückgegeben
    for fw in plan["firewalls"]:
        for op in fw["operations"]:
            if "psksecret" in op["body"]:
                assert op["body"]["psksecret"] == "********"
