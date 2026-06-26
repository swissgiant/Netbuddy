from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    Credential,
    Device,
    DeviceCredential,
    DeviceType,
    Site,
    SiteSubnet,
)
from netbuddy.services.unifi_inventory import classify, import_devices, sync_hosts

_GROUPS = [
    {
        "hostId": "h-sulgen",
        "hostName": "BLS-UniFi-Sulgen",
        "devices": [
            {
                "name": "SW1",
                "model": "USW-Pro-48",
                "mac": "aa",
                "ip": "10.120.10.5",
                "productLine": "network",
                "type": "usw",
            },
            {
                "name": "AP1",
                "model": "U6-LR",
                "mac": "bb",
                "ip": "10.120.12.5",
                "productLine": "network",
                "type": "uap",
            },
            {"name": "Cam1", "model": "G4 Pro", "ip": "10.120.41.5", "productLine": "protect"},
            {
                "name": "UOS",
                "model": "UOS Server",
                "ip": "10.120.12.250",
                "productLine": "network",
                "type": "ugw",
            },
        ],
    },
    {
        "hostId": "h-steelco",
        "hostName": "STEELCO-HQ TVCC",
        "devices": [
            {
                "name": "TVCC1",
                "model": "USW-TVCC-A01",
                "ip": "10.120.99.5",
                "productLine": "network",
                "type": "usw",
            },
        ],
    },
]


def test_classify() -> None:
    assert classify({"productLine": "network", "model": "USW-Pro-48"}) is DeviceType.SWITCH
    assert classify({"productLine": "network", "model": "U6-LR"}) is DeviceType.AP
    assert classify({"productLine": "protect", "model": "G4 Pro"}) is None  # Kamera
    assert classify({"productLine": "network", "model": "UOS Server"}) is None  # Console


async def _cred(s: AsyncSession) -> Credential:
    c = Credential(name="UnifiCloud", base_url="https://api.ui.com")
    c.api_token = "k"
    s.add(c)
    site = Site(name="Sulgen")
    s.add(site)
    await s.flush()
    s.add(SiteSubnet(site_id=site.id, cidr="10.120.0.0/16"))
    await s.flush()
    return c


async def test_sync_hosts_then_import_excludes_disabled(db_session: AsyncSession) -> None:
    cred = await _cred(db_session)
    hosts = await sync_hosts(db_session, cred, _GROUPS)
    assert {h.name for h in hosts} == {"BLS-UniFi-Sulgen", "STEELCO-HQ TVCC"}

    # Steelco deaktivieren
    steelco = next(h for h in hosts if h.name == "STEELCO-HQ TVCC")
    steelco.enabled = False
    await db_session.flush()

    summary = await import_devices(db_session, cred, _GROUPS)
    assert summary.created == 2  # SW1 + AP1
    assert summary.skipped_disabled == 1  # Steelco-Switch
    assert summary.skipped_other == 2  # Kamera + Console

    devs = (
        (await db_session.execute(select(Device).where(Device.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    by = {d.hostname: d for d in devs}
    assert "SW1" in by and "AP1" in by and "TVCC1" not in by
    assert by["SW1"].adapter_id == "unifi_cloud"
    assert by["SW1"].device_type is DeviceType.SWITCH
    assert by["SW1"].site_id is not None  # Standort per IP zugeordnet
    # Credential verknüpft
    links = (
        (
            await db_session.execute(
                select(DeviceCredential).where(DeviceCredential.device_id == by["SW1"].id)
            )
        )
        .scalars()
        .all()
    )
    assert len(links) == 1


async def test_import_idempotent(db_session: AsyncSession) -> None:
    cred = await _cred(db_session)
    await sync_hosts(db_session, cred, _GROUPS)
    await import_devices(db_session, cred, _GROUPS)
    second = await import_devices(db_session, cred, _GROUPS)
    assert second.created == 0  # beim zweiten Lauf nichts Neues
    assert second.updated == 3  # SW1 + AP1 + TVCC1 (beide Hosts hier aktiv)
