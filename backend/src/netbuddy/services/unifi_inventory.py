"""UniFi-Cloud-Inventar: Hosts synchronisieren + Switches/APs als NetBuddy-Devices importieren.

Quelle: UniFi Site Manager Cloud-API (`api.ui.com`, `/v1/devices` nach Host gruppiert).
Pro Host (Konsole) gibt es einen An/Aus-Schalter (`UnifiHost.enabled`); deaktivierte Hosts
(z.B. Steelco ohne Netzanbindung) werden beim Import übersprungen.

Bewusst getrennt: `fetch_device_groups()` macht den Netz-Call, `sync_hosts()`/`import_devices()`
sind reine DB-Logik (ohne Netz testbar).
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.api_client import HttpxApiClient
from netbuddy.db.models import (
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DeviceType,
    UnifiHost,
)
from netbuddy.services.sites_net import site_for_ip


class ImportSummary(BaseModel):
    created: int = 0
    updated: int = 0
    skipped_disabled: int = 0  # Geräte in deaktivierten Hosts
    skipped_other: int = 0  # weder Switch noch AP (Kameras/Gateways/Consoles)


async def fetch_device_groups(credential: Credential) -> list[dict[str, Any]]:
    """Holt `/v1/devices` (nach Host gruppiert) von der UniFi-Cloud."""
    client = HttpxApiClient(
        credential.base_url or "https://api.ui.com",
        token=credential.api_token,
        header_name="X-API-KEY",
    )
    async with client:
        payload = await client.get_json("/v1/devices")
    data = payload.get("data", []) if isinstance(payload, dict) else payload
    return [g for g in (data or []) if isinstance(g, dict)]


def classify(dev: dict[str, Any]) -> DeviceType | None:
    """UniFi-Gerät → Switch/AP, oder None (Kamera/Gateway/Console/UOS = nicht importieren)."""
    if dev.get("productLine") != "network":
        return None
    model = (dev.get("model") or "").upper()
    typ = (dev.get("type") or "").lower()
    if "USW" in model or typ == "usw":
        return DeviceType.SWITCH
    if model.startswith(("U6", "U7", "UAP")) or typ in ("uap", "ap"):
        return DeviceType.AP
    return None


async def sync_hosts(
    session: AsyncSession, credential: Credential, groups: list[dict[str, Any]]
) -> list[UnifiHost]:
    """Hosts aus der Cloud upserten (per host_id). `enabled` bestehender Hosts bleibt erhalten."""
    existing = {
        h.host_id: h
        for h in (
            await session.execute(select(UnifiHost).where(UnifiHost.credential_id == credential.id))
        ).scalars()
    }
    hosts: list[UnifiHost] = []
    for g in groups:
        hid = g.get("hostId")
        if not hid:
            continue
        name = g.get("hostName") or str(hid)
        host = existing.get(str(hid))
        if host is None:
            host = UnifiHost(credential_id=credential.id, host_id=str(hid), name=name, enabled=True)
            session.add(host)
        else:
            host.name = name
        hosts.append(host)
    await session.flush()
    return hosts


async def import_devices(
    session: AsyncSession, credential: Credential, groups: list[dict[str, Any]]
) -> ImportSummary:
    """Switches/APs aus AKTIVEN Hosts als Devices anlegen/aktualisieren (Standort per IP)."""
    hosts = {
        h.host_id: h
        for h in (
            await session.execute(select(UnifiHost).where(UnifiHost.credential_id == credential.id))
        ).scalars()
    }
    summary = ImportSummary()
    for g in groups:
        host = hosts.get(str(g.get("hostId")))
        devices = g.get("devices", []) or []
        if host is None or not host.enabled:
            summary.skipped_disabled += len(devices)
            continue
        for dev in devices:
            dtype = classify(dev)
            ip = dev.get("ip") or dev.get("ipAddress")
            name = dev.get("name") or dev.get("mac")
            if dtype is None or not ip or not name:
                summary.skipped_other += 1
                continue
            site_id = await site_for_ip(session, str(ip))
            existing_dev = (
                await session.execute(
                    select(Device).where(Device.hostname == name, Device.deleted_at.is_(None))
                )
            ).scalar_one_or_none()
            if existing_dev is None:
                d = Device(
                    hostname=name,
                    mgmt_ip=str(ip),
                    vendor="ubiquiti",
                    model=dev.get("model"),
                    adapter_id="unifi_cloud",
                    device_type=dtype,
                    site_id=site_id,
                    enabled=True,
                )
                session.add(d)
                await session.flush()
                session.add(
                    DeviceCredential(
                        device_id=d.id, credential_id=credential.id, protocol=CredentialProtocol.API
                    )
                )
                summary.created += 1
            else:
                existing_dev.mgmt_ip = str(ip)
                existing_dev.adapter_id = "unifi_cloud"
                existing_dev.device_type = dtype
                existing_dev.model = dev.get("model") or existing_dev.model
                existing_dev.site_id = site_id or existing_dev.site_id
                link = (
                    await session.execute(
                        select(DeviceCredential).where(
                            DeviceCredential.device_id == existing_dev.id,
                            DeviceCredential.credential_id == credential.id,
                        )
                    )
                ).scalar_one_or_none()
                if link is None:
                    session.add(
                        DeviceCredential(
                            device_id=existing_dev.id,
                            credential_id=credential.id,
                            protocol=CredentialProtocol.API,
                        )
                    )
                summary.updated += 1
    await session.flush()
    return summary
