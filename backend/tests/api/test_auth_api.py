from httpx import AsyncClient


async def _setup_admin(auth_client: AsyncClient) -> str:
    resp = await auth_client.post("/auth/setup", json={"username": "alex", "password": "secret1"})
    assert resp.status_code == 200
    return str(resp.json()["token"])


async def test_setup_then_login_flow(auth_client: AsyncClient) -> None:
    # ohne Login: geschützt
    assert (await auth_client.get("/devices")).status_code == 401
    # Setup-Status + erster Admin
    assert (await auth_client.get("/auth/setup-status")).json() == {"setup_needed": True}
    token = await _setup_admin(auth_client)
    assert (await auth_client.get("/auth/setup-status")).json() == {"setup_needed": False}
    # zweites Setup verboten
    assert (
        await auth_client.post("/auth/setup", json={"username": "x", "password": "y"})
    ).status_code == 403
    # Bearer funktioniert
    headers = {"Authorization": f"Bearer {token}"}
    assert (await auth_client.get("/devices", headers=headers)).status_code == 200
    me = await auth_client.get("/auth/me", headers=headers)
    assert me.json()["username"] == "alex"
    assert me.json()["role"] == "admin"
    # falsches Passwort
    bad = await auth_client.post("/auth/login", json={"username": "alex", "password": "nope"})
    assert bad.status_code == 401


async def test_role_enforcement(auth_client: AsyncClient) -> None:
    admin_token = await _setup_admin(auth_client)
    admin = {"Authorization": f"Bearer {admin_token}"}

    # Admin legt viewer + operator an (nur admin darf /users)
    for username, role in (("vw", "viewer"), ("op", "operator")):
        resp = await auth_client.post(
            "/users", json={"username": username, "password": "pw", "role": role}, headers=admin
        )
        assert resp.status_code == 201

    async def login(username: str) -> dict[str, str]:
        resp = await auth_client.post("/auth/login", json={"username": username, "password": "pw"})
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    viewer, operator = await login("vw"), await login("op")

    # viewer: lesen ja, schreiben/suchen nein, /users nein
    assert (await auth_client.get("/devices", headers=viewer)).status_code == 200
    body = {"hostname": "h", "mgmt_ip": "10.1.1.1", "vendor": "v", "adapter_id": "dell_os10"}
    assert (await auth_client.post("/devices", json=body, headers=viewer)).status_code == 403
    assert (await auth_client.get("/users", headers=viewer)).status_code == 403

    # operator: schreiben ja, /users nein
    created = await auth_client.post("/devices", json=body, headers=operator)
    assert created.status_code == 201
    assert (await auth_client.get("/users", headers=operator)).status_code == 403

    # logout macht Token ungültig
    assert (await auth_client.post("/auth/logout", headers=operator)).status_code == 204
    assert (await auth_client.get("/devices", headers=operator)).status_code == 401
