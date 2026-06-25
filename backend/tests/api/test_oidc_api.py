from httpx import AsyncClient


async def _setup_admin(auth_client: AsyncClient) -> dict[str, str]:
    resp = await auth_client.post("/auth/setup", json={"username": "alex", "password": "secret1"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


async def test_oidc_status_public_and_default_off(auth_client: AsyncClient) -> None:
    # öffentlich (kein Login nötig), default aus
    resp = await auth_client.get("/auth/oidc-status")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}


async def test_oidc_config_admin_only(auth_client: AsyncClient) -> None:
    admin = await _setup_admin(auth_client)
    await auth_client.post(
        "/users", json={"username": "vw", "password": "pw", "role": "viewer"}, headers=admin
    )
    login = await auth_client.post("/auth/login", json={"username": "vw", "password": "pw"})
    viewer = {"Authorization": f"Bearer {login.json()['token']}"}

    assert (await auth_client.get("/auth/oidc-config", headers=viewer)).status_code == 403
    assert (await auth_client.get("/auth/oidc-config", headers=admin)).status_code == 200


async def test_oidc_config_roundtrip_masks_secret(auth_client: AsyncClient) -> None:
    admin = await _setup_admin(auth_client)
    body = {
        "enabled": True,
        "tenant_id": "tenant-123",
        "client_id": "client-abc",
        "client_secret": "super-secret",
        "redirect_uri": "https://bls-srv-netbuddy.bls.local/auth/callback",
        "group_admin_id": "GA",
        "group_operator_id": "GO",
        "group_viewer_id": "GV",
    }
    put = await auth_client.put("/auth/oidc-config", json=body, headers=admin)
    assert put.status_code == 200
    data = put.json()
    assert data["enabled"] is True
    assert data["tenant_id"] == "tenant-123"
    assert data["has_secret"] is True
    assert "client_secret" not in data  # Secret wird nie zurückgegeben

    # jetzt meldet der öffentliche Status enabled=true
    assert (await auth_client.get("/auth/oidc-status")).json() == {"enabled": True}

    # leeres Secret bei erneutem PUT lässt das bestehende stehen
    body2 = {**body, "client_secret": ""}
    again = await auth_client.put("/auth/oidc-config", json=body2, headers=admin)
    assert again.json()["has_secret"] is True


async def test_login_entra_without_config_unavailable(auth_client: AsyncClient) -> None:
    resp = await auth_client.get("/auth/login/entra")
    assert resp.status_code == 503
