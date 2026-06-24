import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import CurrentUserDep, SessionDep
from netbuddy.core.config import get_settings
from netbuddy.db.models import User, UserRole
from netbuddy.services.auth import (
    COOKIE_NAME,
    any_user_exists,
    create_session,
    hash_password,
    revoke_token,
    verify_password,
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
