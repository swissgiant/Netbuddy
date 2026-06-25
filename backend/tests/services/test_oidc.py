from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import OidcConfig, User, UserRole
from netbuddy.services import oidc


def _cfg(**kw: Any) -> OidcConfig:
    base = dict(
        enabled=True,
        tenant_id="t",
        client_id="c",
        client_secret="s",
        redirect_uri="https://h/auth/callback",
        group_admin_id="GA",
        group_operator_id="GO",
        group_viewer_id="GV",
    )
    base.update(kw)
    return OidcConfig(**base)


def test_role_hierarchy_admin_wins() -> None:
    cfg = _cfg()
    # Mitglied in allen drei → höchste Rolle (admin zuerst).
    assert oidc.role_from_groups(["GV", "GO", "GA"], cfg) is UserRole.ADMIN
    assert oidc.role_from_groups(["GO", "GV"], cfg) is UserRole.OPERATOR
    assert oidc.role_from_groups(["GV"], cfg) is UserRole.VIEWER


def test_role_none_without_matching_group() -> None:
    assert oidc.role_from_groups(["other"], _cfg()) is None
    assert oidc.role_from_groups([], _cfg()) is None


def test_is_configured() -> None:
    assert oidc.is_configured(_cfg()) is True
    assert oidc.is_configured(None) is False
    assert oidc.is_configured(_cfg(enabled=False)) is False
    assert oidc.is_configured(_cfg(client_secret=None)) is False
    assert oidc.is_configured(_cfg(redirect_uri=None)) is False


async def test_resolve_groups_from_claim() -> None:
    token = {"userinfo": {"groups": ["G1", "G2"]}}
    assert await oidc.resolve_groups(token) == ["G1", "G2"]


async def test_resolve_groups_overage_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_graph(access_token: str) -> list[str]:
        assert access_token == "AT"
        return ["GX", "GY"]

    monkeypatch.setattr(oidc, "_graph_groups", fake_graph)
    token = {"userinfo": {"_claim_names": {"groups": "src1"}}, "access_token": "AT"}
    assert await oidc.resolve_groups(token) == ["GX", "GY"]


async def test_upsert_creates_then_updates(db_session: AsyncSession) -> None:
    u1 = await oidc.upsert_oidc_user(
        db_session,
        subject="oid-1",
        username="a@bls.local",
        email="a@bls.local",
        role=UserRole.VIEWER,
    )
    assert u1.password_hash is None
    assert u1.role is UserRole.VIEWER

    # gleicher Subject → selber User, Rolle wird angeglichen
    u2 = await oidc.upsert_oidc_user(
        db_session,
        subject="oid-1",
        username="a@bls.local",
        email="a@bls.local",
        role=UserRole.ADMIN,
    )
    assert u2.id == u1.id
    assert u2.role is UserRole.ADMIN


async def test_upsert_username_collision_with_local_user(db_session: AsyncSession) -> None:
    db_session.add(User(username="dup", password_hash="x", role=UserRole.ADMIN))
    await db_session.flush()
    u = await oidc.upsert_oidc_user(
        db_session, subject="oid-2", username="dup", email=None, role=UserRole.VIEWER
    )
    assert u.username != "dup"
    assert u.username.startswith("dup#")
