from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DeviceType,
)


async def test_device_credential_link(db_session: AsyncSession) -> None:
    device = Device(
        hostname="sw1",
        mgmt_ip="10.0.0.1",
        vendor="cisco",
        device_type=DeviceType.SWITCH,
        adapter_id="cisco_ios",
    )
    credential = Credential(
        name="lab-readonly",
        username="netbuddy",
        password="hunter2",
    )
    db_session.add_all([device, credential])
    await db_session.flush()

    link = DeviceCredential(
        device_id=device.id,
        credential_id=credential.id,
        protocol=CredentialProtocol.SSH,
    )
    db_session.add(link)
    await db_session.flush()

    result = await db_session.execute(
        select(DeviceCredential).where(DeviceCredential.device_id == device.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].protocol == CredentialProtocol.SSH
    assert rows[0].credential_id == credential.id


async def test_encrypted_string_roundtrip(db_session: AsyncSession) -> None:
    plaintext = "public-secret"
    credential = Credential(
        name="snmp-prod",
        username="snmp",
        snmp_community=plaintext,
    )
    db_session.add(credential)
    await db_session.flush()

    raw = await db_session.execute(
        text("SELECT snmp_community FROM credential WHERE id = :id"),
        {"id": credential.id},
    )
    raw_value = raw.scalar_one()
    assert raw_value is not None
    assert raw_value != plaintext
    # Fernet tokens start with "gAAAAA" (base64-encoded version byte + timestamp).
    assert raw_value.startswith("gAAAAA")

    await db_session.refresh(credential, attribute_names=["snmp_community"])
    assert credential.snmp_community == plaintext


async def test_soft_delete_keeps_row(db_session: AsyncSession) -> None:
    device = Device(
        hostname="sw-retired",
        mgmt_ip="10.0.0.99",
        vendor="cisco",
        device_type=DeviceType.SWITCH,
        adapter_id="cisco_ios",
    )
    db_session.add(device)
    await db_session.flush()
    device_id = device.id

    device.deleted_at = datetime.now(UTC)
    await db_session.flush()

    fetched = await db_session.get(Device, device_id)
    assert fetched is not None
    assert fetched.deleted_at is not None
    assert fetched.hostname == "sw-retired"
