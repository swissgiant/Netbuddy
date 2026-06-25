"""Entra-ID-(Azure-AD-)SSO: OIDC-Code-Flow + Rolle aus AAD-Gruppen-Mitgliedschaft.

Muster: keine lokale Userverwaltung für SSO — wer in welcher AAD-Sicherheitsgruppe ist,
bestimmt die Rolle. Lokale User (Passwort) bleiben als Break-Glass-Zugang erhalten.
Konfiguration liegt in der DB (`OidcConfig`, über die Admin-Seite gepflegt).
"""

from typing import Any, cast

import httpx
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import OidcConfig, User, UserRole

GRAPH_MEMBEROF_URL = "https://graph.microsoft.com/v1.0/me/transitiveMemberOf?$select=id"
_SCOPE = "openid profile email User.Read"


async def get_oidc_config(session: AsyncSession) -> OidcConfig | None:
    """Die (einzige) SSO-Konfigurationszeile, oder None falls noch nie gespeichert."""
    return (await session.execute(select(OidcConfig).limit(1))).scalar_one_or_none()


def is_configured(cfg: OidcConfig | None) -> bool:
    """SSO ist nutzbar, wenn aktiviert und die Pflichtfelder gesetzt sind."""
    return bool(
        cfg
        and cfg.enabled
        and cfg.tenant_id
        and cfg.client_id
        and cfg.client_secret
        and cfg.redirect_uri
    )


def build_oauth_app(cfg: OidcConfig) -> StarletteOAuth2App:
    """Baut einen frischen authlib-Client aus der DB-Config (lazy, kein Secret im Code).

    Pro Aufruf neu registriert, damit Konfigurationsänderungen im UI sofort greifen.
    """
    oauth = OAuth()
    oauth.register(
        name="entra",
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{cfg.tenant_id}/v2.0/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": _SCOPE},
    )
    return cast(StarletteOAuth2App, oauth.create_client("entra"))


def role_from_groups(groups: list[str], cfg: OidcConfig) -> UserRole | None:
    """AAD-Gruppen → NetBuddy-Rolle. Hierarchie: Admin zuerst (admin ⊇ operator ⊇ viewer).

    None = User ist in keiner der drei Gruppen → kein Zugriff.
    """
    members = set(groups)
    if cfg.group_admin_id and cfg.group_admin_id in members:
        return UserRole.ADMIN
    if cfg.group_operator_id and cfg.group_operator_id in members:
        return UserRole.OPERATOR
    if cfg.group_viewer_id and cfg.group_viewer_id in members:
        return UserRole.VIEWER
    return None


async def resolve_groups(token: dict[str, Any]) -> list[str]:
    """Gruppen-IDs des Users ermitteln.

    Normalfall: aus dem `groups`-Claim des ID-Tokens. Overage (User in >~200 Gruppen →
    kein groups-Claim, stattdessen `_claim_names`/`hasgroups`): per Graph nachladen.
    """
    claims: dict[str, Any] = token.get("userinfo") or {}
    groups = claims.get("groups")
    if isinstance(groups, list) and groups:
        return [str(g) for g in groups]

    overage = "_claim_names" in claims or claims.get("hasgroups")
    access_token = token.get("access_token")
    if overage and access_token:
        return await _graph_groups(str(access_token))
    return []


async def _graph_groups(access_token: str) -> list[str]:
    """Overage-Fallback: transitive Gruppen-Mitgliedschaft über Microsoft Graph."""
    ids: list[str] = []
    url: str | None = GRAPH_MEMBEROF_URL
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        while url:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            for obj in data.get("value", []):
                gid = obj.get("id")
                if gid:
                    ids.append(str(gid))
            url = data.get("@odata.nextLink")
    return ids


async def upsert_oidc_user(
    session: AsyncSession,
    *,
    subject: str,
    username: str,
    email: str | None,
    role: UserRole,
) -> User:
    """SSO-User finden (per oidc_subject) oder anlegen; Rolle/Mail bei jedem Login angleichen."""
    existing = (
        await session.execute(
            select(User).where(User.oidc_subject == subject, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.role = role
        existing.email = email
        existing.enabled = True
        existing.username = await _unique_username(session, username, exclude_subject=subject)
        await session.flush()
        return existing

    user = User(
        username=await _unique_username(session, username, exclude_subject=subject),
        password_hash=None,
        oidc_subject=subject,
        email=email,
        role=role,
        enabled=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _unique_username(session: AsyncSession, preferred: str, *, exclude_subject: str) -> str:
    """Vermeidet Kollision mit einem (lokalen) User gleichen Namens; hängt sonst oid-Fragment an."""
    clash = (
        await session.execute(
            select(User.id).where(
                User.username == preferred,
                User.deleted_at.is_(None),
                (User.oidc_subject.is_(None)) | (User.oidc_subject != exclude_subject),
            )
        )
    ).first()
    if clash is None:
        return preferred
    return f"{preferred}#{exclude_subject[:8]}"
