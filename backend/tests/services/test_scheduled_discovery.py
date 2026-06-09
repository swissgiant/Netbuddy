from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    ArpData,
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
)
from netbuddy.db.models import (
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DeviceType,
)
from netbuddy.services.crawl import AdapterProvider
from netbuddy.services.discovery import run_scheduled_discovery


class _FakeAdapter:
    adapter_id = "fake"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.READ_SYSTEM_INFO})

    async def get_system_info(self) -> SystemInfo:
        return SystemInfo(vendor="x", model="M", device_type=DeviceType.SWITCH)

    async def get_interfaces(self) -> list[InterfaceData]:
        return []

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        return []

    async def get_mac_table(self) -> list[MacEntryData]:
        return []

    async def get_arp(self) -> list[ArpData]:
        return []

    async def get_config(self) -> str:
        return ""


def _provider() -> AdapterProvider:
    @asynccontextmanager
    async def cm(device: Device, credential: Credential) -> AsyncIterator[_FakeAdapter]:
        yield _FakeAdapter()

    return cm


async def test_scheduled_discovery_only_devices_with_credential(db_session: AsyncSession) -> None:
    cred = Credential(name="svc", username="u")
    with_cred = Device(
        hostname="has-cred",
        mgmt_ip="10.0.0.1",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    without_cred = Device(
        hostname="no-cred",
        mgmt_ip="10.0.0.2",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    db_session.add_all([cred, with_cred, without_cred])
    await db_session.flush()
    db_session.add(
        DeviceCredential(
            device_id=with_cred.id, credential_id=cred.id, protocol=CredentialProtocol.SSH
        )
    )
    await db_session.flush()

    summary = await run_scheduled_discovery(db_session, _provider())

    assert summary["devices"] == 1
    assert summary["ok"] == ["has-cred"]
    assert summary["errors"] == []
    # System-Info wurde persistiert
    assert with_cred.model == "M"
    assert without_cred.model is None
