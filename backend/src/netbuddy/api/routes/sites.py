import uuid
from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Site

router = APIRouter(prefix="/sites", tags=["sites"])


class SiteCreate(BaseModel):
    name: str
    code: str | None = None
    description: str | None = None


class SiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str | None
    description: str | None
    created_at: datetime


@router.post("", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
async def create_site(body: SiteCreate, session: SessionDep) -> Site:
    """Legt einen Standort an."""
    site = Site(name=body.name, code=body.code, description=body.description)
    session.add(site)
    await session.flush()
    return site


@router.get("", response_model=list[SiteRead])
async def list_sites(session: SessionDep) -> Sequence[Site]:
    """Listet aktive Standorte."""
    stmt = select(Site).where(Site.deleted_at.is_(None)).order_by(Site.name)
    return (await session.execute(stmt)).scalars().all()
