import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, IPvAnyAddress
from sqlalchemy import delete, select

from netbuddy.adapters import Capability, UnknownAdapterError, adapter_kind, get_profile
from netbuddy.api.deps import (
    CurrentUserDep,
    LiveAdapterDep,
    LiveConnectionDep,
    OnboardingTransportDep,
    SessionDep,
    ValidatorDep,
)
from netbuddy.db.models import (
    AdminStatus,
    ArpEntry,
    ConfigBackup,
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DeviceType,
    DiscoveryRun,
    DiscoveryStatus,
    Host,
    Interface,
    LldpNeighbor,
    MacAddressEntry,
    MacEntryType,
    OperStatus,
    ValidationCheck,
    VpnTunnel,
)
from netbuddy.services.audit import audit
from netbuddy.services.backup import BackupResult, backup_device, diff_latest
from netbuddy.services.discovery import run_discovery
from netbuddy.services.hosts import normalize_mac
from netbuddy.services.lldp_control import LldpEnableResult, enable_lldp, read_lldp_enabled
from netbuddy.services.onboarding import ProfileDraft, suggest_profile
from netbuddy.services.oui import vendor_for_mac
from netbuddy.services.sites_net import site_for_ip
from netbuddy.services.validation import DeviceValidationReport, validate_adapter

router = APIRouter(prefix="/devices", tags=["devices"])


def _unreachable(device: Device, exc: Exception) -> HTTPException:
    """Verbindungsfehler → lesbare 502 statt rohem 500-Traceback im GUI."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=(
            f"{device.hostname} ({device.mgmt_ip}) nicht erreichbar: "
            f"{type(exc).__name__}: {exc}. SSH aktiv? IP/Port korrekt?"
        ),
    )


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
    site_id: uuid.UUID | None
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
    site_id: uuid.UUID | None = None
    credential_id: uuid.UUID | None = None


async def _create_device(body: DeviceCreate, session: SessionDep) -> Device:
    # Standort automatisch aus den Site-IP-Segmenten ableiten, wenn keiner angegeben ist.
    site_id = body.site_id or await site_for_ip(session, str(body.mgmt_ip))
    device = Device(
        hostname=body.hostname,
        mgmt_ip=str(body.mgmt_ip),
        vendor=body.vendor,
        adapter_id=body.adapter_id,
        device_type=body.device_type,
        model=body.model,
        site_id=site_id,
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
async def create_device(body: DeviceCreate, session: SessionDep, user: CurrentUserDep) -> Device:
    """Legt ein Gerät an (+ optionale SSH-Credential-Verknüpfung)."""
    device = await _create_device(body, session)
    await audit(session, user, "device.create", device.hostname, {"adapter_id": device.adapter_id})
    return device


class DeviceUpdate(BaseModel):
    """Teil-Update eines Geräts; nur gesetzte Felder werden geändert (`site_id: null` = leeren)."""

    hostname: str | None = None
    mgmt_ip: IPvAnyAddress | None = None
    vendor: str | None = None
    adapter_id: str | None = None
    device_type: DeviceType | None = None
    site_id: uuid.UUID | None = None


@router.patch("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: uuid.UUID, body: DeviceUpdate, session: SessionDep, user: CurrentUserDep
) -> Device:
    """Ändert ein Gerät inline (Standort/Adapter/IP/…), ohne Löschen+Neuanlegen."""
    device = await get_device(device_id, session)
    fields = body.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(device, key, str(value) if key == "mgmt_ip" and value is not None else value)
    await session.flush()
    await audit(session, user, "device.update", device.hostname, {"fields": list(fields)})
    await session.refresh(device)  # onupdate-Felder (updated_at) frisch laden, sonst Lazy-IO
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> None:
    """Entfernt ein Gerät (Soft-Delete)."""
    device = await get_device(device_id, session)
    device.deleted_at = datetime.now(UTC)
    await audit(session, user, "device.delete", device.hostname)


class DeviceCredentialLink(BaseModel):
    credential_id: uuid.UUID
    protocol: CredentialProtocol | None = None  # None = aus der Credential ableiten


@router.post("/{device_id}/credentials", status_code=status.HTTP_201_CREATED)
async def link_credential(
    device_id: uuid.UUID, body: DeviceCredentialLink, session: SessionDep
) -> DeviceCredentialLink:
    """Verknüpft eine Credential mit einem Gerät (idempotent).

    Das Protokoll wird aus der Credential abgeleitet (base_url → api, sonst ssh) —
    eine API-Credential erscheint damit nicht mehr fälschlich als „(ssh)"."""
    await get_device(device_id, session)
    credential = await session.get(Credential, body.credential_id)
    if credential is None or credential.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential nicht gefunden"
        )
    protocol = body.protocol or (
        CredentialProtocol.API if credential.base_url else CredentialProtocol.SSH
    )
    existing = await session.get(DeviceCredential, (device_id, body.credential_id, protocol))
    if existing is None:
        session.add(
            DeviceCredential(
                device_id=device_id, credential_id=body.credential_id, protocol=protocol
            )
        )
        await session.flush()
    return DeviceCredentialLink(credential_id=body.credential_id, protocol=protocol)


@router.delete("/{device_id}/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_credential(
    device_id: uuid.UUID,
    credential_id: uuid.UUID,
    session: SessionDep,
    protocol: CredentialProtocol = CredentialProtocol.SSH,
) -> None:
    """Löst eine Credential-Verknüpfung eines Geräts."""
    await session.execute(
        delete(DeviceCredential).where(
            DeviceCredential.device_id == device_id,
            DeviceCredential.credential_id == credential_id,
            DeviceCredential.protocol == protocol,
        )
    )


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


async def _device_credential(device: Device, session: SessionDep) -> Credential | None:
    """Beste Credential fürs Gerät: API-Adapter → Credential mit base_url, CLI → ohne."""
    if not device.adapter_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{device.hostname}: kein Profil/Adapter zugewiesen — bitte in der "
            "Geräteliste eines auswählen (z.B. dell_os6).",
        )
    stmt = (
        select(Credential)
        .join(DeviceCredential, DeviceCredential.credential_id == Credential.id)
        .where(
            DeviceCredential.device_id == device.id,
            DeviceCredential.deleted_at.is_(None),
            Credential.deleted_at.is_(None),
        )
    )
    creds = list((await session.execute(stmt)).scalars())
    if not creds:
        return None
    try:
        wants_api = adapter_kind(device.adapter_id) == "api"
    except UnknownAdapterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    for cred in creds:
        if bool(cred.base_url) == wants_api:
            return cred
    return creds[0]


@router.post("/{device_id}/validate", response_model=DeviceValidationReport)
async def validate_device_endpoint(
    device_id: uuid.UUID,
    session: SessionDep,
    validator: ValidatorDep,
    live_adapter: LiveAdapterDep,
) -> DeviceValidationReport:
    """Prüft read-only live, ob die gespeicherten Kommandos/Profile am Gerät funktionieren.

    CLI-Profile laufen über den Recording-Validator (mit Roh-Output je Befehl); API-Adapter
    (fortigate/unifi/…) über die Live-Verbindung ohne Roh-Capture. ⚠️ echter Geräte-Zugriff.
    """
    device = await get_device(device_id, session)
    credential = await _device_credential(device, session)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine Credential für dieses Gerät verknüpft",
        )

    is_api = adapter_kind(device.adapter_id) == "api"
    raw_by_command: dict[str, str] = {}
    try:
        if is_api:
            async with live_adapter(device, credential) as adapter:
                report = await validate_adapter(adapter)
        else:
            get_profile(device.adapter_id)  # 400 bei unbekanntem Profil
            report, raw_by_command = await validator(device, credential)
    except UnknownAdapterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (TimeoutError, OSError) as exc:
        raise _unreachable(device, exc) from exc
    except Exception as exc:
        if type(exc).__name__.startswith(("Scrapli", "Httpx", "Connect")):
            raise _unreachable(device, exc) from exc
        raise

    def _commands(capability: Capability) -> list[str]:
        if is_api:
            return [f"API: {capability.value}"]
        return [
            src.command for src in get_profile(device.adapter_id).capabilities[capability].sources
        ]

    # Letzten Lauf ersetzen.
    await session.execute(delete(ValidationCheck).where(ValidationCheck.device_id == device_id))
    for cap_report in report.capabilities:
        commands = _commands(cap_report.capability)
        raw = "\n\n".join(f"$ {c}\n{raw_by_command.get(c, '')}" for c in commands if not is_api)
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
    credential = await _device_credential(device, session)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine SSH-Credential für dieses Gerät verknüpft",
        )
    try:
        async with live_adapter(device, credential) as adapter:
            return await run_discovery(session, device, adapter, triggered_by="api")
    except (TimeoutError, OSError) as exc:
        raise _unreachable(device, exc) from exc
    except Exception as exc:
        if type(exc).__name__.startswith("Scrapli"):
            raise _unreachable(device, exc) from exc
        raise


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
    parent_name: str | None
    vlan_id: int | None
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
    resolved_ip: str | None = None  # aus ARP/LLDP-Mgmt (über chassis_id-MAC)
    resolved_name: str | None = None  # aus DNS (Host-Korrelation)
    guessed_vendor: str | None = None  # aus dem OUI der chassis_id-MAC (IEEE-Registry)


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
async def list_lldp_neighbors(device_id: uuid.UUID, session: SessionDep) -> list[LldpNeighborRead]:
    """LLDP-Nachbarn eines Geräts, angereichert um IP (ARP/LLDP-Mgmt) + DNS-Name (Host)."""
    await get_device(device_id, session)
    neighbors = (
        (
            await session.execute(
                select(LldpNeighbor).where(LldpNeighbor.local_device_id == device_id)
            )
        )
        .scalars()
        .all()
    )
    # MAC → korrelierter Host (IP + DNS-Name) bzw. ARP-IP, gematcht über die chassis_id (= MAC).
    hosts = {h.mac: h for h in (await session.execute(select(Host))).scalars()}
    arp_ip: dict[str, str] = {}
    for ip, mac in (await session.execute(select(ArpEntry.ip_address, ArpEntry.mac))).all():
        arp_ip.setdefault(mac, ip)

    result: list[LldpNeighborRead] = []
    for n in neighbors:
        mac = normalize_mac(n.remote_chassis_id)
        host = hosts.get(mac)
        result.append(
            LldpNeighborRead(
                id=n.id,
                local_interface_id=n.local_interface_id,
                remote_chassis_id=n.remote_chassis_id,
                remote_port_id=n.remote_port_id,
                remote_port_description=n.remote_port_description,
                remote_system_name=n.remote_system_name,
                remote_system_description=n.remote_system_description,
                resolved_ip=(host.ip_address if host else None)
                or arp_ip.get(mac)
                or n.remote_mgmt_address,
                resolved_name=host.name if host else None,
                guessed_vendor=vendor_for_mac(n.remote_chassis_id),
            )
        )
    return result


@router.get("/{device_id}/mac-table", response_model=list[MacEntryRead])
async def list_mac_table(device_id: uuid.UUID, session: SessionDep) -> Sequence[MacAddressEntry]:
    """MAC-Address-Table eines Geräts."""
    await get_device(device_id, session)
    stmt = select(MacAddressEntry).where(MacAddressEntry.device_id == device_id)
    return (await session.execute(stmt)).scalars().all()


class ArpEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ip_address: str
    mac: str
    vlan_id: int | None


@router.get("/{device_id}/arp", response_model=list[ArpEntryRead])
async def list_arp(device_id: uuid.UUID, session: SessionDep) -> Sequence[ArpEntry]:
    """ARP-Tabelle eines Geräts (IP↔MAC, Basis der Namensauflösung)."""
    await get_device(device_id, session)
    stmt = select(ArpEntry).where(ArpEntry.device_id == device_id).order_by(ArpEntry.ip_address)
    return (await session.execute(stmt)).scalars().all()


# --- Assistiertes Onboarding (read-only: Geräte-Hilfe → Kandidaten-Befehle) -------------------


@router.post("/{device_id}/suggest-profile", response_model=ProfileDraft)
async def suggest_profile_endpoint(
    device_id: uuid.UUID, session: SessionDep, transport_factory: OnboardingTransportDep
) -> ProfileDraft:
    """Liest read-only die Geräte-Hilfe (`show ?`), findet Kandidaten-Befehle je Capability und
    holt deren Output → Profil-Entwurf für ein neues/unbekanntes Gerät. ⚠️ echter Geräte-Zugriff."""
    device = await get_device(device_id, session)
    credential = await _device_credential(device, session)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine SSH-Credential für dieses Gerät verknüpft",
        )
    async with transport_factory(device, credential) as transport:
        return await suggest_profile(transport, suggested_adapter_id=device.adapter_id)


# --- Config-Backup (read-only) + Diff ---------------------------------------------------------


class ConfigBackupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sha256: str
    created_at: datetime


@router.post("/{device_id}/backup", response_model=BackupResult)
async def backup_device_endpoint(
    device_id: uuid.UUID, session: SessionDep, live_adapter: LiveAdapterDep, user: CurrentUserDep
) -> BackupResult:
    """Sichert read-only die laufende Konfiguration (nur bei Änderung neu gespeichert)."""
    device = await get_device(device_id, session)
    credential = await _device_credential(device, session)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine SSH-Credential für dieses Gerät verknüpft",
        )
    async with live_adapter(device, credential) as adapter:
        result = await backup_device(session, device, adapter)
    await audit(session, user, "device.backup", device.hostname, {"changed": result.changed})
    return result


@router.get("/{device_id}/backups", response_model=list[ConfigBackupRead])
async def list_backups(device_id: uuid.UUID, session: SessionDep) -> Sequence[ConfigBackup]:
    """Metadaten der Konfig-Sicherungen eines Geräts (neueste zuerst)."""
    await get_device(device_id, session)
    stmt = (
        select(ConfigBackup)
        .where(ConfigBackup.device_id == device_id)
        .order_by(ConfigBackup.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


@router.get("/{device_id}/backups/{backup_id}")
async def get_backup_content(
    device_id: uuid.UUID, backup_id: uuid.UUID, session: SessionDep
) -> dict[str, str]:
    """Voller Konfig-Text einer Sicherung."""
    backup = await session.get(ConfigBackup, backup_id)
    if backup is None or backup.device_id != device_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup nicht gefunden")
    return {"content": backup.content, "sha256": backup.sha256}


@router.get("/{device_id}/config-diff")
async def config_diff(device_id: uuid.UUID, session: SessionDep) -> dict[str, str]:
    """Unified-Diff der beiden jüngsten Sicherungen (leer, wenn < 2 vorhanden)."""
    await get_device(device_id, session)
    return {"diff": await diff_latest(session, device_id)}


# --- LLDP-Steuerung (Status read-only; Aktivieren = Schreibzugriff) ---------------------------


class LldpStatusResult(BaseModel):
    supported: bool  # Profil hat einen LLDP-Schreibpfad
    enabled: bool | None  # globaler LLDP-Status (None, wenn nicht unterstützt/nicht lesbar)


async def _lldp_prereqs(device_id: uuid.UUID, session: SessionDep) -> tuple[Device, Credential]:
    device = await get_device(device_id, session)
    credential = await _device_credential(device, session)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine SSH-Credential für dieses Gerät verknüpft",
        )
    return device, credential


@router.post("/{device_id}/lldp/status", response_model=LldpStatusResult)
async def lldp_status_endpoint(
    device_id: uuid.UUID, session: SessionDep, connection: LiveConnectionDep
) -> LldpStatusResult:
    """Prüft read-only live, ob LLDP global aktiv ist (für die „aktivieren?"-Nachfrage)."""
    device, credential = await _lldp_prereqs(device_id, session)
    profile = get_profile(device.adapter_id)
    if profile.lldp_control is None:
        return LldpStatusResult(supported=False, enabled=None)
    async with connection(device, credential) as (_adapter, transport):
        enabled = await read_lldp_enabled(transport, profile.lldp_control)
    return LldpStatusResult(supported=True, enabled=enabled)


@router.post("/{device_id}/lldp/enable", response_model=LldpEnableResult)
async def lldp_enable_endpoint(
    device_id: uuid.UUID,
    session: SessionDep,
    connection: LiveConnectionDep,
    user: CurrentUserDep,
) -> LldpEnableResult:
    """Aktiviert LLDP global + pro Port. ⚠️ Schreibzugriff: vorher Backup, danach Verifikation.

    Eng auf LLDP begrenzt; nur erlaubt, wenn das Profil einen `lldp_control`-Pfad hat.
    """
    device, credential = await _lldp_prereqs(device_id, session)
    profile = get_profile(device.adapter_id)
    if profile.lldp_control is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Adapter {device.adapter_id!r} unterstützt LLDP-Aktivierung nicht",
        )
    async with connection(device, credential) as (adapter, transport):
        result = await enable_lldp(session, device, adapter, transport, profile.lldp_control)
    await audit(
        session,
        user,
        "device.lldp_enable",
        device.hostname,
        {"interfaces": result.interfaces_configured, "enabled_after": result.enabled_after},
    )
    return result


# --- VPN-Tunnel (Firewalls): Liste + „berücksichtigen"-Schalter -------------------------------


class VpnTunnelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    remote_gateway: str | None
    is_up: bool
    relevant: bool
    local_subnets: list[str]
    remote_subnets: list[str]


@router.get("/{device_id}/vpn-tunnels", response_model=list[VpnTunnelRead])
async def list_vpn_tunnels(device_id: uuid.UUID, session: SessionDep) -> Sequence[VpnTunnel]:
    """VPN-Tunnel einer Firewall (aus der Discovery), inkl. Relevanz-Flag."""
    await get_device(device_id, session)
    stmt = select(VpnTunnel).where(VpnTunnel.device_id == device_id).order_by(VpnTunnel.name)
    return (await session.execute(stmt)).scalars().all()


class VpnTunnelUpdate(BaseModel):
    relevant: bool


@router.patch("/{device_id}/vpn-tunnels/{tunnel_id}", response_model=VpnTunnelRead)
async def update_vpn_tunnel(
    device_id: uuid.UUID,
    tunnel_id: uuid.UUID,
    body: VpnTunnelUpdate,
    session: SessionDep,
    user: CurrentUserDep,
) -> VpnTunnel:
    """Schaltet einen Tunnel für die Topologie ein/aus (Partner-/Lieferanten-Tunnel raus)."""
    tunnel = await session.get(VpnTunnel, tunnel_id)
    if tunnel is None or tunnel.device_id != device_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tunnel nicht gefunden")
    tunnel.relevant = body.relevant
    await session.flush()
    device = await get_device(device_id, session)
    await audit(
        session,
        user,
        "device.vpn_tunnel_toggle",
        device.hostname,
        {"tunnel": tunnel.name, "relevant": body.relevant},
    )
    await session.refresh(tunnel)
    return tunnel
