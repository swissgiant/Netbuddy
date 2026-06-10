from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    ArpData,
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
    VpnTunnelData,
)
from netbuddy.adapters.profile import LldpControlSpec
from netbuddy.db.models import Device, DeviceType
from netbuddy.services.lldp_control import enable_lldp, is_physical, read_lldp_enabled

_SPEC = LldpControlSpec(
    status_command="show lldp local config",
    enabled_marker=r"global enabled\s*:\s*YES",
    enable_global=["lldp enable"],
    enable_interface=["lldp enable"],
)


class _FakeAdapter:
    """Minimaler SwitchAdapter: physische + logische Interfaces, Konfig für das Backup."""

    adapter_id = "fs_centec"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.READ_INTERFACES})

    async def get_system_info(self) -> SystemInfo:
        return SystemInfo(vendor="fs", device_type=DeviceType.SWITCH)

    async def get_interfaces(self) -> list[InterfaceData]:
        return [
            InterfaceData(name="eth-0-1"),
            InterfaceData(name="eth-0-2"),
            InterfaceData(name="vlan10"),  # logisch → kein lldp enable
        ]

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        return []

    async def get_mac_table(self) -> list[MacEntryData]:
        return []

    async def get_arp(self) -> list[ArpData]:
        return []

    async def get_vpn_tunnels(self) -> list[VpnTunnelData]:
        return []

    async def get_config(self) -> str:
        return "hostname bls-sw-53\n"


class _FakeWriteTransport:
    """Status startet 'NO'; nach erstem send_config kippt er auf 'YES' (Gerät hat LLDP an)."""

    def __init__(self) -> None:
        self.enabled = False
        self.config_calls: list[list[str]] = []

    async def send_command(self, command: str) -> str:
        state = "YES" if self.enabled else "NO"
        return f"LLDP global configuration:\nLLDP function global enabled : {state}\n"

    async def send_config(self, lines: list[str]) -> str:
        self.config_calls.append(lines)
        self.enabled = True
        return "ok"


def test_is_physical() -> None:
    assert is_physical("eth-0-1")
    assert is_physical("GigabitEthernet1/0/1")
    assert not is_physical("vlan10")
    assert not is_physical("port-channel1")
    assert not is_physical("loopback0")


async def test_read_lldp_enabled_marker() -> None:
    t = _FakeWriteTransport()
    assert await read_lldp_enabled(t, _SPEC) is False
    t.enabled = True
    assert await read_lldp_enabled(t, _SPEC) is True


async def test_enable_lldp_backs_up_writes_and_verifies(db_session) -> None:  # type: ignore[no-untyped-def]
    device = Device(
        hostname="bls-sw-53",
        mgmt_ip="10.120.10.53",
        vendor="fs",
        device_type=DeviceType.SWITCH,
        adapter_id="fs_centec",
    )
    db_session.add(device)
    await db_session.flush()

    transport = _FakeWriteTransport()
    result = await enable_lldp(db_session, device, _FakeAdapter(), transport, _SPEC)

    assert result.was_enabled is False
    assert result.enabled_after is True  # nach dem Schreiben verifiziert
    assert result.backed_up is True
    assert result.interfaces_configured == 2  # nur die zwei physischen Ports

    # Backup wurde vor dem Schreiben angelegt
    from sqlalchemy import select

    from netbuddy.db.models import ConfigBackup

    backups = (
        (await db_session.execute(select(ConfigBackup).where(ConfigBackup.device_id == device.id)))
        .scalars()
        .all()
    )
    assert len(backups) == 1

    # gesendete Konfig: global + pro physischem Port lldp enable
    sent = transport.config_calls[0]
    assert "lldp enable" in sent
    assert "interface eth-0-1" in sent
    assert "interface eth-0-2" in sent
    assert "interface vlan10" not in sent
