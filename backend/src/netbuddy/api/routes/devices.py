import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, IPvAnyAddress
from sqlalchemy import delete, select

from netbuddy.adapters import UnknownAdapterError, get_profile
from netbuddy.api.deps import LiveAdapterDep, SessionDep, ValidatorDep
from netbuddy.db.models import (
    AdminStatus,
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DeviceType,
    DiscoveryRun,
    DiscoveryStatus,
    Interface,
    LldpNeighbor,
    MacAddressEntry,
    MacEntryType,
    OperStatus,
    ValidationCheck,
)
from netbuddy.services.discovery import run_discovery
from netbuddy.services.validation import DeviceValidationReport

router = APIRouter(prefix="/devices", tags=["devices"])


class DeviceRead(BaseModel):
    """Read-Schema für ein Gerät — entspricht der DB-Sicht ohne interne Soft-Delete-Felder."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    mgmt_ip: IPvAnyAddress
    vendor: str
    model: str | None
    os_version: str | None
    serial_number: str | None
    device_type: DeviceType
    adapter_id: str
    capabilities: list[str]
    enabled: bool
    first_seen: datetime
    last_seen: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[DeviceRead])
async def list_devices(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Sequence[Device]:
    """Listet aktive (nicht soft-gelöschte) Geräte, alphabetisch nach Hostname."""
    stmt = (
        select(Device)
        .where(Device.deleted_at.is_(None))
        .order_by(Device.hostname)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(device_id: uuid.UUID, session: SessionDep) -> Device:
    """Liefert ein einzelnes aktives Gerät oder 404, wenn es nicht existiert."""
    stmt = select(Device).where(
        Device.id == device_id,
        Device.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gerät nicht gefunden",
        )
    return device


# --- Geräte-Eintrag (Inventar, kein Gerätezugriff) -------------------------------------------


class DeviceCreate(BaseModel):
    """Anlage eines Geräts; `credential_id` verknüpft optional eine SSH-Credential."""

    hostname: str
    mgmt_ip: IPvAnyAddress
    vendor: str
    adapter_id: str
    device_type: DeviceType = DeviceType.SWITCH
    model: str | None = None
    credential_id: uuid.UUID | None = None


async def _create_device(body: DeviceCreate, session: SessionDep) -> Device:
    device = Device(
        hostname=body.hostname,
        mgmt_ip=str(body.mgmt_ip),
        vendor=body.vendor,
        adapter_id=body.adapter_id,
        device_type=body.device_type,
        model=body.model,
    )
    session.add(device)
    await session.flush()
    if body.credential_id is not None:
        session.add(
            DeviceCredential(
                device_id=device.id,
                credential_id=body.credential_id,
                protocol=CredentialProtocol.SSH,
            )
        )
        await session.flush()
    return device


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def create_device(body: DeviceCreate, session: SessionDep) -> Device:
    """Legt ein Gerät an (+ optionale SSH-Credential-Verknüpfung)."""
    return await _create_device(body, session)


class DeviceImportResult(BaseModel):
    created: int
    device_ids: list[uuid.UUID]


@router.post("/import", response_model=DeviceImportResult, status_code=status.HTTP_201_CREATED)
async def import_devices(body: list[DeviceCreate], session: SessionDep) -> DeviceImportResult:
    """Bulk-Eintrag vieler Geräte (für die 30+ Switches)."""
    ids = [(await _create_device(entry, session)).id for entry in body]
    return DeviceImportResult(created=len(ids), device_ids=ids)


# --- Live-Validierung (read-only Geräte-Zugriff) ---------------------------------------------


class ValidationCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    capability: str
    command: str
    status: str
    row_count: int
    detail: dict[str, Any]
    raw_excerpt: str | None
    checked_at: datetime


async def _ssh_credential(device_id: uuid.UUID, session: SessionDep) -> Credential | None:
    stmt = (
        select(Credential)
        .join(DeviceCredential, DeviceCredential.credential_id == Credential.id)
        .where(
            DeviceCredential.device_id == device_id,
            DeviceCredential.protocol == CredentialProtocol.SSH,
            Credential.deleted_at.is_(None),
        )
    )
    return (await session.execute(stmt)).scalars().first()


@router.post("/{device_id}/validate", response_model=DeviceValidationReport)
async def validate_device_endpoint(
    device_id: uuid.UUID, session: SessionDep, validator: ValidatorDep
) -> DeviceValidationReport:
    """Prüft read-only live, ob die gespeicherten Kommandos/Profile am Gerät funktionieren.

    Verbindet sich zum Gerät, fährt jede Capability, bewertet das Parsen und persistiert
    den Status (`validation_check`). ⚠️ erster echter Geräte-Zugriff.
    """
    device = await get_device(device_id, session)
    credential = await _ssh_credential(device_id, session)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine SSH-Credential für dieses Gerät verknüpft",
        )
    try:
        profile = get_profile(device.adapter_id)
    except UnknownAdapterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    report, raw_by_command = await validator(device, credential)

    # Letzten Lauf ersetzen.
    await session.execute(delete(ValidationCheck).where(ValidationCheck.device_id == device_id))
    for cap_report in report.capabilities:
        spec = profile.capabilities[cap_report.capability]
        commands = [src.command for src in spec.sources]
        raw = "\n\n".join(f"$ {c}\n{raw_by_command.get(c, '')}" for c in commands)
        session.add(
            ValidationCheck(
                device_id=device_id,
                adapter_id=device.adapter_id,
                capability=cap_report.capability.value,
                command=", ".join(commands),
                status=cap_report.status.value,
                row_count=cap_report.row_count,
                detail={"coverage": cap_report.coverage, "message": cap_report.message},
                raw_excerpt=raw or None,
            )
        )
    await session.flush()
    return report


@router.get("/{device_id}/validation", response_model=list[ValidationCheckRead])
async def get_device_validation(
    device_id: uuid.UUID, session: SessionDep
) -> Sequence[ValidationCheck]:
    """Letzter persistierter Validierungs-Status je Capability für ein Gerät."""
    await get_device(device_id, session)  # 404 wenn fehlt
    stmt = (
        select(ValidationCheck)
        .where(ValidationCheck.device_id == device_id)
        .order_by(ValidationCheck.capability)
    )
    return (await session.execute(stmt)).scalars().all()


# --- Discovery (read-only Geräte-Zugriff → Inventar persistieren) -----------------------------


class DiscoveryRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: DiscoveryStatus
    triggered_by: str
    devices_found: int
    errors: list[dict[str, Any]]
    started_at: datetime
    finished_at: datetime | None


@router.post("/{device_id}/discover", response_model=DiscoveryRunRead)
async def discover_device_endpoint(
    device_id: uuid.UUID, session: SessionDep, live_adapter: LiveAdapterDep
) -> DiscoveryRun:
    """Liest read-only live aus und schreibt das Inventar (Interfaces/LLDP/MAC) in die DB."""
    device = await get_device(device_id, session)
    credential = await _ssh_credential(device_id, session)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine SSH-Credential für dieses Gerät verknüpft",
        )
    async with live_adapter(device, credential) as adapter:
        return await run_discovery(session, device, adapter, triggered_by="api")


# --- Aggregat-Lesesichten ---------------------------------------------------------------------


class InterfaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    if_index: int | None
    description: str | None
    admin_status: AdminStatus
    oper_status: OperStatus
    mac_address: str | None
    speed_mbps: int | None
    mtu: int | None
    interface_type: str | None
    last_polled: datetime | None


class LldpNeighborRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    local_interface_id: uuid.UUID
    remote_chassis_id: str
    remote_port_id: str
    remote_port_description: str | None
    remote_system_name: str | None
    remote_system_description: str | None


class MacEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    interface_id: uuid.UUID
    mac_address: str
    vlan_id: int | None
    entry_type: MacEntryType


@router.get("/{device_id}/interfaces", response_model=list[InterfaceRead])
async def list_interfaces(device_id: uuid.UUID, session: SessionDep) -> Sequence[Interface]:
    """Interfaces eines Geräts (aus dem zuletzt discovers persistierten Inventar)."""
    await get_device(device_id, session)
    stmt = (
        select(Interface)
        .where(Interface.device_id == device_id, Interface.deleted_at.is_(None))
        .order_by(Interface.name)
    )
    return (await session.execute(stmt)).scalars().all()


@router.get("/{device_id}/lldp-neighbors", response_model=list[LldpNeighborRead])
async def list_lldp_neighbors(device_id: uuid.UUID, session: SessionDep) -> Sequence[LldpNeighbor]:
    """LLDP-Nachbarn eines Geräts."""
    await get_device(device_id, session)
    stmt = select(LldpNeighbor).where(LldpNeighbor.local_device_id == device_id)
    return (await session.execute(stmt)).scalars().all()


@router.get("/{device_id}/mac-table", response_model=list[MacEntryRead])
async def list_mac_table(device_id: uuid.UUID, session: SessionDep) -> Sequence[MacAddressEntry]:
    """MAC-Address-Table eines Geräts."""
    await get_device(device_id, session)
    stmt = select(MacAddressEntry).where(MacAddressEntry.device_id == device_id)
    return (await session.execute(stmt)).scalars().all()
