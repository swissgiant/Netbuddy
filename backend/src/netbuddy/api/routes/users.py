import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.api.routes.auth import UserRead
from netbuddy.db.models import User, UserRole
from netbuddy.services.auth import hash_password

router = APIRouter(prefix="/users", tags=["users"])  # via RBAC-Policy nur für admin


class UserCreate(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.VIEWER


@router.get("", response_model=list[UserRead])
async def list_users(session: SessionDep) -> Sequence[User]:
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.username)
    return (await session.execute(stmt)).scalars().all()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, session: SessionDep) -> User:
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    session.add(user)
    await session.flush()
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, session: SessionDep) -> None:
    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User nicht gefunden")
    user.deleted_at = datetime.now(UTC)
