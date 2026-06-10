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
    mgmt_ip_template: str | None = None  # z.B. "10.120.10.{n}"


class SiteUpdate(BaseModel):
    """Teil-Update; nur gesetzte Felder werden geändert (`mgmt_ip_template: null` = löschen)."""

    name: str | None = None
    code: str | None = None
    description: str | None = None
    mgmt_ip_template: str | None = None


class SiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str | None
    description: str | None
    mgmt_ip_template: str | None
    created_at: datetime


def _check_template(template: str | None) -> None:
    if template is not None and "{n}" not in template:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='mgmt_ip_template braucht den Platzhalter "{n}" (z.B. "10.120.10.{n}")',
        )


@router.post("", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
async def create_site(body: SiteCreate, session: SessionDep) -> Site:
    """Legt einen Standort an."""
    _check_template(body.mgmt_ip_template)
    site = Site(
        name=body.name,
        code=body.code,
        description=body.description,
        mgmt_ip_template=body.mgmt_ip_template,
    )
    session.add(site)
    await session.flush()
    return site


@router.patch("/{site_id}", response_model=SiteRead)
async def update_site(site_id: uuid.UUID, body: SiteUpdate, session: SessionDep) -> Site:
    """Ändert einen Standort (z.B. die Namens→IP-Regel nachträglich setzen)."""
    site = await session.get(Site, site_id)
    if site is None or site.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standort nicht gefunden")
    fields = body.model_dump(exclude_unset=True)
    if "mgmt_ip_template" in fields:
        _check_template(fields["mgmt_ip_template"])
    for key, value in fields.items():
        setattr(site, key, value)
    await session.flush()
    await session.refresh(site)
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
