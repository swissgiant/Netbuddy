"""Zentrale VLAN-Verwaltung (#36).

Die 16 Test-VLANs werden **einmal zentral** definiert (VLAN-ID, Name, Beschreibung) und gelten mit
**derselben VLAN-ID an allen Standorten** — das pro-Standort unterschiedliche Subnetz (+ Gateway,
typischerweise auf der Standort-Firewall) hängt als :class:`VlanSubnet` daran. Grundlage für die
spätere VLAN-Generierung auf den Switches (#37), die FW-Kopplung (#38) und die Port-Zuweisung (#34).
Read/Write read-only auf dem Datenmodell — kein Gerätezugriff in diesem Increment.
"""

import ipaddress
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Site, Vlan, VlanSubnet

router = APIRouter(prefix="/vlans", tags=["vlans"])


class VlanSubnetIn(BaseModel):
    site_id: uuid.UUID
    cidr: str
    gateway: str | None = None


class VlanSubnetRead(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    site_name: str | None = None
    cidr: str
    gateway: str | None = None


class VlanCreate(BaseModel):
    vlan_id: int
    name: str
    description: str | None = None

    @field_validator("vlan_id")
    @classmethod
    def _range(cls, value: int) -> int:
        if not 1 <= value <= 4094:
            raise ValueError("VLAN-ID muss zwischen 1 und 4094 liegen")
        return value

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name darf nicht leer sein")
        return value.strip()


class VlanUpdate(BaseModel):
    """Teil-Update; nur gesetzte Felder werden geändert."""

    name: str | None = None
    description: str | None = None


class VlanRead(BaseModel):
    id: uuid.UUID
    vlan_id: int
    name: str
    description: str | None
    created_at: datetime
    subnets: list[VlanSubnetRead] = []


def _validate_subnet(cidr: str, gateway: str | None) -> tuple[str, str | None]:
    """Prüft CIDR (+ optionales Gateway, das im Netz liegen muss) und normalisiert beide."""
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ungültiges Subnetz: {cidr!r} ({exc})",
        ) from exc
    gw: str | None = None
    if gateway and gateway.strip():
        try:
            gw_addr = ipaddress.ip_address(gateway.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Ungültiges Gateway: {gateway!r} ({exc})",
            ) from exc
        if gw_addr not in net:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Gateway {gw_addr} liegt nicht im Subnetz {net}",
            )
        gw = str(gw_addr)
    return str(net), gw


async def _site_names(session: SessionDep) -> dict[uuid.UUID, str]:
    return {sid: name for sid, name in (await session.execute(select(Site.id, Site.name))).all()}


async def _read_model(session: SessionDep, vlan: Vlan, names: dict[uuid.UUID, str]) -> VlanRead:
    subs = (
        (
            await session.execute(
                select(VlanSubnet).where(VlanSubnet.vlan_id == vlan.id).order_by(VlanSubnet.cidr)
            )
        )
        .scalars()
        .all()
    )
    return VlanRead(
        id=vlan.id,
        vlan_id=vlan.vlan_id,
        name=vlan.name,
        description=vlan.description,
        created_at=vlan.created_at,
        subnets=[
            VlanSubnetRead(
                id=s.id,
                site_id=s.site_id,
                site_name=names.get(s.site_id),
                cidr=str(s.cidr),
                gateway=str(s.gateway) if s.gateway else None,
            )
            for s in subs
        ],
    )


async def _get_or_404(session: SessionDep, vlan_id: uuid.UUID) -> Vlan:
    vlan = await session.get(Vlan, vlan_id)
    if vlan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN nicht gefunden")
    return vlan


@router.get("", response_model=list[VlanRead])
async def list_vlans(session: SessionDep) -> list[VlanRead]:
    """Listet alle zentral definierten VLANs inkl. ihrer pro-Standort-Subnetze."""
    vlans = (await session.execute(select(Vlan).order_by(Vlan.vlan_id))).scalars().all()
    names = await _site_names(session)
    return [await _read_model(session, v, names) for v in vlans]


@router.post("", response_model=VlanRead, status_code=status.HTTP_201_CREATED)
async def create_vlan(body: VlanCreate, session: SessionDep) -> VlanRead:
    """Legt ein VLAN an (VLAN-ID unternehmensweit eindeutig)."""
    exists = await session.scalar(select(Vlan).where(Vlan.vlan_id == body.vlan_id))
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VLAN-ID {body.vlan_id} existiert bereits",
        )
    vlan = Vlan(vlan_id=body.vlan_id, name=body.name, description=body.description)
    session.add(vlan)
    await session.flush()
    return await _read_model(session, vlan, await _site_names(session))


@router.patch("/{vlan_id}", response_model=VlanRead)
async def update_vlan(vlan_id: uuid.UUID, body: VlanUpdate, session: SessionDep) -> VlanRead:
    """Ändert Name/Beschreibung eines VLANs (die VLAN-ID selbst ist unveränderlich)."""
    vlan = await _get_or_404(session, vlan_id)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields:
        if not (fields["name"] or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name darf nicht leer sein"
            )
        vlan.name = fields["name"].strip()
    if "description" in fields:
        vlan.description = fields["description"]
    await session.flush()
    return await _read_model(session, vlan, await _site_names(session))


@router.delete("/{vlan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vlan(vlan_id: uuid.UUID, session: SessionDep) -> None:
    """Löscht ein VLAN samt aller pro-Standort-Subnetze (Cascade)."""
    vlan = await _get_or_404(session, vlan_id)
    await session.delete(vlan)


@router.put("/{vlan_id}/subnets", response_model=VlanSubnetRead)
async def set_subnet(vlan_id: uuid.UUID, body: VlanSubnetIn, session: SessionDep) -> VlanSubnetRead:
    """Setzt (Upsert) das Subnetz + Gateway eines VLANs für einen Standort."""
    vlan = await _get_or_404(session, vlan_id)
    site = await session.get(Site, body.site_id)
    if site is None or site.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standort nicht gefunden")
    cidr, gw = _validate_subnet(body.cidr, body.gateway)
    row = await session.scalar(
        select(VlanSubnet).where(VlanSubnet.vlan_id == vlan.id, VlanSubnet.site_id == body.site_id)
    )
    if row is None:
        row = VlanSubnet(vlan_id=vlan.id, site_id=body.site_id, cidr=cidr, gateway=gw)
        session.add(row)
    else:
        row.cidr = cidr
        row.gateway = gw
    await session.flush()
    names = await _site_names(session)
    return VlanSubnetRead(
        id=row.id,
        site_id=row.site_id,
        site_name=names.get(row.site_id),
        cidr=str(row.cidr),
        gateway=str(row.gateway) if row.gateway else None,
    )


@router.delete("/{vlan_id}/subnets/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subnet(vlan_id: uuid.UUID, site_id: uuid.UUID, session: SessionDep) -> None:
    """Entfernt das Subnetz eines VLANs für einen Standort."""
    row = await session.scalar(
        select(VlanSubnet).where(VlanSubnet.vlan_id == vlan_id, VlanSubnet.site_id == site_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subnetz nicht gefunden")
    await session.delete(row)


# --- VLAN-Survey (S63): Ist-Zustand der VLANs pro Standort einsammeln -------------------------


class SurveyRunRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    data: dict[str, object]


_survey_running: dict[str, bool] = {"active": False}


async def _survey_task() -> None:
    """Hintergrund-Lauf mit eigener DB-Session (der Request wartet nicht)."""
    from loguru import logger

    from netbuddy.db.models import VlanSurveyRun
    from netbuddy.db.session import SessionLocal
    from netbuddy.services.vlan_survey import run_vlan_survey

    try:
        async with SessionLocal() as session:
            data = await run_vlan_survey(session)
            session.add(VlanSurveyRun(data=data))
            await session.commit()
            logger.info("VLAN-Survey abgeschlossen: {} Sites", len(data.get("sites", {})))
    except Exception:
        logger.exception("VLAN-Survey fehlgeschlagen")
    finally:
        _survey_running["active"] = False


@router.post("/survey/run", status_code=status.HTTP_202_ACCEPTED)
async def start_vlan_survey() -> dict[str, str]:
    """Startet den read-only VLAN-Survey über die ganze Fleet (dauert einige Minuten).

    Läuft im Hintergrund; das Ergebnis erscheint als neuer Lauf unter ``GET /vlans/survey``.
    """
    import asyncio

    if _survey_running["active"]:
        return {"status": "already-running"}
    _survey_running["active"] = True
    asyncio.get_running_loop().create_task(_survey_task())
    return {"status": "started"}


@router.get("/survey", response_model=SurveyRunRead | None)
async def get_vlan_survey(session: SessionDep) -> SurveyRunRead | None:
    """Der jüngste Survey-Lauf (oder null, wenn noch keiner lief)."""
    from netbuddy.db.models import VlanSurveyRun

    row = (
        (
            await session.execute(
                select(VlanSurveyRun).order_by(VlanSurveyRun.created_at.desc()).limit(1)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    return SurveyRunRead(id=row.id, created_at=row.created_at, data=row.data)


@router.get("/survey/status")
async def vlan_survey_status() -> dict[str, bool]:
    """Läuft gerade ein Survey?"""
    return {"running": _survey_running["active"]}
