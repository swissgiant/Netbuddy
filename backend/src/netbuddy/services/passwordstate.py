"""Passwordstate (Click Studios) lesen und Einträge als NetBuddy-Credentials übernehmen.

API: ``GET <base>/api/passwords/<PasswordListID>?QueryAll=true`` mit Header ``APIKey`` (Key je
Passwortliste, in Passwordstate unter „List Administrator Actions → API Keys“). NetBuddy-Credential
„Passwordstate“: ``base_url`` (z.B. https://ch-sv-p-pwst-1.corp.belimed.com), ``api_token`` =
API-Key, ``extra.list_ids`` = Liste der PasswordListIDs (optional, sonst beim Aufruf angeben),
``extra.verify`` = false für interne CA.

Ablauf: ``preview`` (ohne Passwörter, zeigt Anlegen/Aktualisieren + Geräte-Zuordnung) →
``import_entries`` (legt Credentials an, verknüpft Geräte per Hostname/IP). Passwörter werden nie
geloggt oder an das Frontend geliefert.
"""

import ipaddress
import re
import uuid
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.api_client import HttpxApiClient
from netbuddy.adapters.base import AdapterError
from netbuddy.db.models import Credential, Device, DeviceCredential
from netbuddy.db.models.device_credential import CredentialProtocol

_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


class PwEntry(BaseModel):
    """Ein Passwordstate-Eintrag (Passwort nur intern, nie in API-Antworten)."""

    password_id: int
    list_id: int | None
    list_name: str | None
    title: str
    username: str | None
    password: str | None
    description: str | None
    url: str | None
    hostname: str | None
    notes: str | None


class PwPreviewRow(BaseModel):
    password_id: int
    title: str
    username: str | None
    hostname: str | None
    url: str | None
    description: str | None
    has_password: bool
    action: str  # "anlegen" | "aktualisieren" | "überspringen"
    credential_name: str
    devices: list[str]  # Hostnamen der NetBuddy-Geräte, die verknüpft würden


class PwImportSummary(BaseModel):
    dry_run: bool
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    linked: list[str] = []  # "credential → device"


class PwList(BaseModel):
    list_id: int
    name: str
    tree_path: str | None
    description: str | None


class PasswordstateApi:
    def __init__(self, credential: Credential) -> None:
        if not credential.base_url or not credential.api_token:
            raise AdapterError("Passwordstate-Credential braucht base_url und api_token (API-Key)")
        extra = credential.extra or {}
        self.name = credential.name
        self.list_ids = _list_ids_from_extra(extra)
        self._client = HttpxApiClient(
            credential.base_url.rstrip("/"),
            token=credential.api_token,
            header_name="APIKey",
            verify=bool(extra.get("verify", False)),
            timeout=60.0,
        )

    async def __aenter__(self) -> "PasswordstateApi":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.__aexit__(None, None, None)

    async def fetch_list(self, list_id: int) -> list[PwEntry]:
        data = await self._get(f"/api/passwords/{list_id}", f"Liste {list_id}")
        return parse_entries(data)

    async def fetch_lists(self) -> list[PwList]:
        """Alle Passwortlisten (nur mit System-Wide-Key, Listen-Keys liefern 401)."""
        return parse_lists(await self._get("/api/passwordlists/", "Listenübersicht"))

    async def _get(self, path: str, what: str) -> Any:
        try:
            return await self._client.get_json(path, params={"QueryAll": "true"})
        except httpx.HTTPStatusError as exc:
            detail = _error_text(exc.response)
            raise AdapterError(
                f"Passwordstate: HTTP {exc.response.status_code} für {what}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"Passwordstate: {exc}") from exc


def parse_lists(data: Any) -> list[PwList]:
    out: list[PwList] = []
    for row in data if isinstance(data, list) else []:
        if isinstance(row, dict) and row.get("PasswordListID"):
            out.append(
                PwList(
                    list_id=int(row["PasswordListID"]),
                    name=str(row.get("PasswordList") or row["PasswordListID"]),
                    tree_path=row.get("TreePath") or None,
                    description=row.get("Description") or None,
                )
            )
    return out


_ID_RE = re.compile(r"\d+")


def _list_ids_from_extra(extra: dict[str, Any]) -> list[int]:
    """``extra.list_ids`` (Liste) oder das Formularfeld (site/org_id/account_id), dort auch
    mehrere IDs mit Komma/Leerzeichen („12, 15 18")."""
    raw: list[Any] = list(extra.get("list_ids") or [])
    for key in ("site", "org_id", "account_id"):
        found = _ID_RE.findall(str(extra.get(key, "")))
        if found:
            raw += found
            break
    out: list[int] = []
    for x in raw:
        if str(x).strip().isdigit() and int(x) not in out:
            out.append(int(x))
    return out


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        errs = payload[0].get("errors") or []
        return "; ".join(str(e.get("message") or e.get("phrase") or e) for e in errs)[:300]
    return str(payload)[:200]


def parse_entries(data: Any) -> list[PwEntry]:
    out: list[PwEntry] = []
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict) or "PasswordID" not in row:
            continue
        out.append(
            PwEntry(
                password_id=int(row["PasswordID"]),
                list_id=int(row["PasswordListID"]) if row.get("PasswordListID") else None,
                list_name=row.get("PasswordList"),
                title=str(row.get("Title") or f"Passwordstate #{row['PasswordID']}"),
                username=(row.get("UserName") or "").strip() or None,
                password=row.get("Password") or None,
                description=row.get("Description") or None,
                url=row.get("URL") or None,
                hostname=row.get("HostName") or None,
                notes=row.get("Notes") or None,
            )
        )
    return out


def _candidate_hosts(entry: PwEntry) -> set[str]:
    """Hostnamen/IPs, über die ein Eintrag einem NetBuddy-Gerät zugeordnet werden kann."""
    blob = " ".join(x for x in (entry.hostname, entry.url, entry.title, entry.description) if x)
    hosts = {ip for ip in _IP_RE.findall(blob) if _valid_ip(ip)}
    for raw in (entry.hostname, entry.url):
        if not raw:
            continue
        host = re.sub(r"^\w+://", "", raw).split("/")[0].split(":")[0].strip().lower()
        if host and not _IP_RE.fullmatch(host):
            hosts.add(host)
            hosts.add(host.split(".")[0])
    return hosts


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


async def _device_index(session: AsyncSession) -> dict[str, Device]:
    devices = (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars()
    index: dict[str, Device] = {}
    for d in devices:
        index[str(d.mgmt_ip)] = d
        index[d.hostname.lower()] = d
        index[d.hostname.lower().split(".")[0]] = d
    return index


def _match_devices(entry: PwEntry, index: dict[str, Device]) -> list[Device]:
    found: dict[uuid.UUID, Device] = {}
    for key in _candidate_hosts(entry):
        dev = index.get(key)
        if dev is not None:
            found[dev.id] = dev
    return list(found.values())


def credential_names(entries: list[PwEntry]) -> dict[int, str]:
    """Credential-Name je Eintrag: Titel; bei gleichem Titel mit anderem User „Titel (user)“."""
    users_by_title: dict[str, set[str]] = {}
    for e in entries:
        users_by_title.setdefault(e.title.strip().lower(), set()).add((e.username or "").lower())
    out: dict[int, str] = {}
    for e in entries:
        title = e.title.strip()
        if len(users_by_title[title.lower()]) > 1 and e.username:
            title = f"{title} ({e.username})"
        out[e.password_id] = title[:128]
    return out


async def preview(session: AsyncSession, entries: list[PwEntry]) -> list[PwPreviewRow]:
    index = await _device_index(session)
    existing = {
        c.name.lower(): c
        for c in (
            await session.execute(select(Credential).where(Credential.deleted_at.is_(None)))
        ).scalars()
    }
    names = credential_names(entries)
    rows: list[PwPreviewRow] = []
    for e in entries:
        name = names[e.password_id]
        if not e.password or not e.username:
            action = "überspringen"
        elif name.lower() in existing:
            action = "aktualisieren"
        else:
            action = "anlegen"
        rows.append(
            PwPreviewRow(
                password_id=e.password_id,
                title=e.title,
                username=e.username,
                hostname=e.hostname,
                url=e.url,
                description=e.description,
                has_password=bool(e.password),
                action=action,
                credential_name=name,
                devices=[d.hostname for d in _match_devices(e, index)],
            )
        )
    return rows


async def import_entries(
    session: AsyncSession,
    entries: list[PwEntry],
    *,
    dry_run: bool,
    source: str = "passwordstate",
) -> PwImportSummary:
    """Einträge → Credentials (SSH, Port 22); gleicher Name = Passwort/User aktualisieren.

    Verknüpft Geräte (per Hostname/IP im Eintrag) als SSH-Credential, falls noch nicht verknüpft.
    """
    summary = PwImportSummary(dry_run=dry_run)
    index = await _device_index(session)
    names = credential_names(entries)
    existing = {
        c.name.lower(): c
        for c in (
            await session.execute(select(Credential).where(Credential.deleted_at.is_(None)))
        ).scalars()
    }
    for e in entries:
        name = names[e.password_id]
        if not e.password or not e.username:
            summary.skipped.append(f"{name} (ohne User/Passwort)")
            continue
        cred = existing.get(name.lower())
        if cred is None:
            summary.created.append(name)
            cred = Credential(
                name=name,
                username=e.username,
                password=e.password,
                ssh_port=22,
                extra={"source": source, "password_id": e.password_id, "list_id": e.list_id},
            )
            if not dry_run:
                session.add(cred)
                await session.flush()
            existing[name.lower()] = cred
        else:
            summary.updated.append(name)
            if not dry_run:
                cred.username = e.username
                cred.password = e.password
                cred.extra = {
                    **(cred.extra or {}),
                    "source": source,
                    "password_id": e.password_id,
                    "list_id": e.list_id,
                }
        for dev in _match_devices(e, index):
            if dry_run:
                summary.linked.append(f"{name} → {dev.hostname}")
                continue
            link = (
                await session.execute(
                    select(DeviceCredential).where(
                        DeviceCredential.device_id == dev.id,
                        DeviceCredential.credential_id == cred.id,
                        DeviceCredential.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if link is None:
                session.add(
                    DeviceCredential(
                        device_id=dev.id, credential_id=cred.id, protocol=CredentialProtocol.SSH
                    )
                )
                summary.linked.append(f"{name} → {dev.hostname}")
    if not dry_run:
        await session.flush()
    return summary
