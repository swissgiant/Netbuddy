import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Device, Site

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


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: uuid.UUID, session: SessionDep) -> None:
    """Entfernt einen Standort (Soft-Delete). Abgelehnt, solange Geräte daran hängen."""
    site = await session.get(Site, site_id)
    if site is None or site.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standort nicht gefunden")
    count = await session.scalar(
        select(func.count())
        .select_from(Device)
        .where(Device.site_id == site_id, Device.deleted_at.is_(None))
    )
    if count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Standort hat noch {count} zugeordnete(s) Gerät(e)",
        )
    site.deleted_at = datetime.now(UTC)
