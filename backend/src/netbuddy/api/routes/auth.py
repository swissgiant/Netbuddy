import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import CurrentUserDep, SessionDep
from netbuddy.core.config import get_settings
from netbuddy.db.models import OidcConfig, User, UserRole
from netbuddy.services.auth import (
    COOKIE_NAME,
    any_user_exists,
    create_session,
    hash_password,
    revoke_token,
    verify_password,
)
from netbuddy.services.oidc import (
    build_oauth_app,
    get_oidc_config,
    is_configured,
    resolve_groups,
    role_from_groups,
    upsert_oidc_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: UserRole
    enabled: bool


class LoginResult(BaseModel):
    token: str  # für API-Clients (Bearer); Browser bekommt zusätzlich das httpOnly-Cookie
    user: UserRead


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=get_settings().use_secure_cookies,  # hinter TLS: nur über HTTPS senden
        max_age=12 * 3600,
        path="/",
    )


@router.get("/setup-status")
async def setup_status(session: SessionDep) -> dict[str, bool]:
    """`setup_needed=true`, solange noch kein Benutzer existiert (Erst-Einrichtung)."""
    return {"setup_needed": not await any_user_exists(session)}


@router.post("/setup", response_model=LoginResult)
async def setup_first_admin(
    body: LoginBody, session: SessionDep, response: Response
) -> LoginResult:
    """Legt den ersten Admin an — nur möglich, solange es noch keine Benutzer gibt."""
    if await any_user_exists(session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Setup bereits abgeschlossen"
        )
    user = User(
        username=body.username, password_hash=hash_password(body.password), role=UserRole.ADMIN
    )
    session.add(user)
    await session.flush()
    token = await create_session(session, user)
    _set_cookie(response, token)
    return LoginResult(token=token, user=UserRead.model_validate(user))


@router.post("/login", response_model=LoginResult)
async def login(body: LoginBody, session: SessionDep, response: Response) -> LoginResult:
    """Login mit Username/Passwort → Session-Token (Cookie + Bearer)."""
    stmt = select(User).where(
        User.username == body.username, User.deleted_at.is_(None), User.enabled.is_(True)
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login fehlgeschlagen")
    token = await create_session(session, user)
    _set_cookie(response, token)
    return LoginResult(token=token, user=UserRead.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: SessionDep, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else None
    if token:
        await revoke_token(session, token)
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUserDep) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")
    return user


# --- Entra-ID-(Azure-AD-)SSO ------------------------------------------------------------------


@router.get("/oidc-status")
async def oidc_status(session: SessionDep) -> dict[str, bool]:
    """`enabled=true`, wenn SSO konfiguriert & aktiv ist (Frontend zeigt dann den Button)."""
    return {"enabled": is_configured(await get_oidc_config(session))}


@router.get("/login/entra")
async def login_entra(request: Request, session: SessionDep) -> Response:
    """Startet den OIDC-Code-Flow → Redirect zu Entra (State/Nonce via SessionMiddleware)."""
    cfg = await get_oidc_config(session)
    if not is_configured(cfg):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="SSO ist nicht konfiguriert"
        )
    assert cfg is not None and cfg.redirect_uri is not None
    app = build_oauth_app(cfg)
    return await app.authorize_redirect(request, cfg.redirect_uri)  # type: ignore[no-any-return]


@router.get("/callback")
async def callback(request: Request, session: SessionDep) -> Response:
    """Entra-Callback: Token holen, Gruppen→Rolle, User upsert, Session setzen, zurück zur App."""
    cfg = await get_oidc_config(session)
    if not is_configured(cfg):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="SSO ist nicht konfiguriert"
        )
    assert cfg is not None
    app = build_oauth_app(cfg)
    try:
        token: dict[str, Any] = await app.authorize_access_token(request)
    except Exception as exc:  # authlib wirft bei State/Token-Fehlern
        logger.warning("OIDC-Callback fehlgeschlagen: {err}", err=exc)
        return RedirectResponse("/?sso_error=token", status_code=status.HTTP_303_SEE_OTHER)

    claims: dict[str, Any] = token.get("userinfo") or {}
    subject = claims.get("oid") or claims.get("sub")
    if not subject:
        return RedirectResponse("/?sso_error=claims", status_code=status.HTTP_303_SEE_OTHER)

    groups = await resolve_groups(token)
    role = role_from_groups(groups, cfg)
    if role is None:
        logger.info("OIDC-Login ohne passende Gruppe: {sub}", sub=subject)
        return RedirectResponse("/?sso_error=norole", status_code=status.HTTP_303_SEE_OTHER)

    username = claims.get("preferred_username") or claims.get("email") or str(subject)
    email = claims.get("email") or claims.get("preferred_username")
    user = await upsert_oidc_user(
        session, subject=str(subject), username=str(username), email=email, role=role
    )
    nb_token = await create_session(session, user)
    redirect = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    _set_cookie(redirect, nb_token)
    return redirect


class OidcConfigRead(BaseModel):
    """SSO-Config fürs Admin-UI — Secret wird nie zurückgegeben, nur ob eines gesetzt ist."""

    enabled: bool
    tenant_id: str | None
    client_id: str | None
    redirect_uri: str | None
    group_admin_id: str | None
    group_operator_id: str | None
    group_viewer_id: str | None
    has_secret: bool


class OidcConfigUpdate(BaseModel):
    enabled: bool = False
    tenant_id: str | None = None
    client_id: str | None = None
    # Nur setzen, wenn nicht-leer übergeben; sonst bleibt das bestehende Secret erhalten.
    client_secret: str | None = None
    redirect_uri: str | None = None
    group_admin_id: str | None = None
    group_operator_id: str | None = None
    group_viewer_id: str | None = None


def _config_read(cfg: OidcConfig | None) -> OidcConfigRead:
    if cfg is None:
        return OidcConfigRead(
            enabled=False,
            tenant_id=None,
            client_id=None,
            redirect_uri=None,
            group_admin_id=None,
            group_operator_id=None,
            group_viewer_id=None,
            has_secret=False,
        )
    return OidcConfigRead(
        enabled=cfg.enabled,
        tenant_id=cfg.tenant_id,
        client_id=cfg.client_id,
        redirect_uri=cfg.redirect_uri,
        group_admin_id=cfg.group_admin_id,
        group_operator_id=cfg.group_operator_id,
        group_viewer_id=cfg.group_viewer_id,
        has_secret=bool(cfg.client_secret),
    )


@router.get("/oidc-config", response_model=OidcConfigRead)
async def get_oidc_config_route(session: SessionDep) -> OidcConfigRead:
    """Aktuelle SSO-Config (admin-only via RBAC). Secret bleibt verborgen."""
    return _config_read(await get_oidc_config(session))


@router.put("/oidc-config", response_model=OidcConfigRead)
async def update_oidc_config(body: OidcConfigUpdate, session: SessionDep) -> OidcConfigRead:
    """SSO-Config speichern (admin-only). Leeres `client_secret` lässt das bestehende stehen."""
    cfg = await get_oidc_config(session)
    if cfg is None:
        cfg = OidcConfig()
        session.add(cfg)
    cfg.enabled = body.enabled
    cfg.tenant_id = body.tenant_id
    cfg.client_id = body.client_id
    cfg.redirect_uri = body.redirect_uri
    cfg.group_admin_id = body.group_admin_id
    cfg.group_operator_id = body.group_operator_id
    cfg.group_viewer_id = body.group_viewer_id
    if body.client_secret:
        cfg.client_secret = body.client_secret
    await session.flush()
    return _config_read(cfg)
