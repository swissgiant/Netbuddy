import ipaddress
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Device, Site, SiteSubnet

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


class SubnetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cidr: str
    description: str | None

    @field_validator("cidr", mode="before")
    @classmethod
    def _cidr_to_str(cls, value: object) -> str:
        return str(value)  # CIDR-Spalte liefert IPv4Network, kein str


class SiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str | None
    description: str | None
    mgmt_ip_template: str | None
    created_at: datetime
    subnets: list[SubnetRead] = []


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


async def _subnets_by_site(session: SessionDep) -> dict[uuid.UUID, list[SiteSubnet]]:
    grouped: dict[uuid.UUID, list[SiteSubnet]] = {}
    for sub in (await session.execute(select(SiteSubnet).order_by(SiteSubnet.cidr))).scalars():
        grouped.setdefault(sub.site_id, []).append(sub)
    return grouped


@router.get("", response_model=list[SiteRead])
async def list_sites(session: SessionDep) -> list[SiteRead]:
    """Listet aktive Standorte inkl. ihrer IP-Segmente."""
    stmt = select(Site).where(Site.deleted_at.is_(None)).order_by(Site.name)
    sites = (await session.execute(stmt)).scalars().all()
    subnets = await _subnets_by_site(session)
    return [
        SiteRead(
            id=s.id,
            name=s.name,
            code=s.code,
            description=s.description,
            mgmt_ip_template=s.mgmt_ip_template,
            created_at=s.created_at,
            subnets=[SubnetRead.model_validate(x) for x in subnets.get(s.id, [])],
        )
        for s in sites
    ]


class SubnetCreate(BaseModel):
    cidr: str
    description: str | None = None


@router.post("/{site_id}/subnets", response_model=SubnetRead, status_code=status.HTTP_201_CREATED)
async def add_subnet(site_id: uuid.UUID, body: SubnetCreate, session: SessionDep) -> SiteSubnet:
    """Fügt einem Standort ein IP-Segment hinzu (z.B. 10.120.0.0/16)."""
    site = await session.get(Site, site_id)
    if site is None or site.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standort nicht gefunden")
    try:
        cidr = str(ipaddress.ip_network(body.cidr.strip(), strict=False))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ungültiges Subnetz: {body.cidr!r} ({exc})",
        ) from exc
    subnet = SiteSubnet(site_id=site_id, cidr=cidr, description=body.description)
    session.add(subnet)
    await session.flush()
    return subnet


@router.delete("/{site_id}/subnets/{subnet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subnet(site_id: uuid.UUID, subnet_id: uuid.UUID, session: SessionDep) -> None:
    """Entfernt ein IP-Segment eines Standorts."""
    subnet = await session.get(SiteSubnet, subnet_id)
    if subnet is None or subnet.site_id != site_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment nicht gefunden")
    await session.delete(subnet)


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
