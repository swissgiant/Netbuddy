import pytest
from sqlalchemy import select

from netbuddy.adapters import build_adapter, get_profile
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    ArpData,
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
    VpnTunnelData,
)
from netbuddy.adapters.profile import PortVlanControlSpec
from netbuddy.db.models import ConfigBackup, Device, DeviceType, Interface
from netbuddy.services.port_vlan import assign_port_vlan, reset_port_vlan

_SPEC = PortVlanControlSpec(set_access=["switchport mode access", "switchport access vlan {vlan}"])


class _FakeAdapter:
    """SwitchAdapter, dessen Port-VLAN sich erst nach dem Schreiben ändert (für Verify)."""

    adapter_id = "fs_centec"

    def __init__(self, state: dict[str, int | None]) -> None:
        self._state = state

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.READ_INTERFACES})

    async def get_system_info(self) -> SystemInfo:
        return SystemInfo(vendor="fs", device_type=DeviceType.SWITCH)

    async def get_interfaces(self) -> list[InterfaceData]:
        return [
            InterfaceData(name="eth-0-5", vlan_id=self._state.get("vlan")),
            InterfaceData(name="eth-0-6"),
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
    def __init__(self, state: dict[str, int | None]) -> None:
        self._state = state
        self.config_calls: list[list[str]] = []

    async def send_command(self, command: str) -> str:
        return ""

    async def send_config(self, lines: list[str]) -> str:
        self.config_calls.append(lines)
        for line in lines:
            if line.startswith("switchport access vlan"):
                self._state["vlan"] = int(line.split()[-1])
        return "ok"


async def test_assign_port_vlan_writes_verifies_and_updates_inventory(db_session) -> None:  # type: ignore[no-untyped-def]
    device = Device(
        hostname="bls-sw-53",
        mgmt_ip="10.120.10.53",
        vendor="fs",
        device_type=DeviceType.SWITCH,
        adapter_id="fs_centec",
    )
    db_session.add(device)
    await db_session.flush()
    db_session.add(Interface(device_id=device.id, name="eth-0-5"))
    await db_session.flush()

    state: dict[str, int | None] = {"vlan": None}
    transport = _FakeWriteTransport(state)
    result = await assign_port_vlan(
        db_session, device, _FakeAdapter(state), transport, _SPEC, "eth-0-5", 107
    )

    assert result.vlan_id == 107
    assert result.verified is True  # Re-Read bestätigt das neue VLAN
    assert result.backed_up is True

    # gesendete Konfig: interface + access-mode + access vlan (mit gefülltem {vlan})
    sent = transport.config_calls[0]
    assert "interface eth-0-5" in sent
    assert "switchport mode access" in sent
    assert "switchport access vlan 107" in sent

    # Backup vor dem Schreiben + Inventar-Interface aktualisiert
    backups = (
        (await db_session.execute(select(ConfigBackup).where(ConfigBackup.device_id == device.id)))
        .scalars()
        .all()
    )
    assert len(backups) == 1
    row = (
        (
            await db_session.execute(
                select(Interface).where(
                    Interface.device_id == device.id, Interface.name == "eth-0-5"
                )
            )
        )
        .scalars()
        .first()
    )
    assert row is not None and row.vlan_id == 107


async def test_reset_port_vlan_back_to_default(db_session) -> None:  # type: ignore[no-untyped-def]
    device = Device(
        hostname="bls-sw-53",
        mgmt_ip="10.120.10.53",
        vendor="fs",
        device_type=DeviceType.SWITCH,
        adapter_id="fs_centec",
    )
    db_session.add(device)
    await db_session.flush()
    db_session.add(Interface(device_id=device.id, name="eth-0-5", vlan_id=107))
    await db_session.flush()

    state: dict[str, int | None] = {"vlan": 107}
    transport = _FakeWriteTransport(state)
    result = await reset_port_vlan(
        db_session, device, _FakeAdapter(state), transport, _SPEC, "eth-0-5"
    )
    assert result.vlan_id == 1 and result.verified is True
    assert "switchport access vlan 1" in transport.config_calls[0]
    row = (
        (
            await db_session.execute(
                select(Interface).where(
                    Interface.device_id == device.id, Interface.name == "eth-0-5"
                )
            )
        )
        .scalars()
        .first()
    )
    assert row is not None and row.vlan_id == 1


async def test_assign_port_vlan_rejects_logical_port(db_session) -> None:  # type: ignore[no-untyped-def]
    device = Device(
        hostname="x",
        mgmt_ip="10.120.10.53",
        vendor="fs",
        device_type=DeviceType.SWITCH,
        adapter_id="fs_centec",
    )
    db_session.add(device)
    await db_session.flush()
    state: dict[str, int | None] = {"vlan": None}
    with pytest.raises(ValueError, match="kein physischer Port"):
        await assign_port_vlan(
            db_session,
            device,
            _FakeAdapter(state),
            _FakeWriteTransport(state),
            _SPEC,
            "vlan10",
            107,
        )


def test_cli_profiles_advertise_port_vlan_capability() -> None:
    for adapter_id in ("dell_os10", "dell_os6", "fs_centec", "fs_ruijie", "tplink_jetstream"):
        profile = get_profile(adapter_id)
        assert profile.port_vlan_control is not None
        adapter = build_adapter(adapter_id, _FakeWriteTransport({"vlan": None}))
        assert Capability.CONFIGURE_PORT_VLAN in adapter.capabilities()


_SPEC_FULL = PortVlanControlSpec(
    set_access=["switchport mode access", "switchport access vlan {vlan}"],
    save=["enable", "copy running-config startup-config", "y"],
    save_marker="Configuration Saved",
    verify_command="show interfaces switchport {name}",
    verify_pattern=r"Access Mode VLAN:\s*{vlan}\b",
)


class _FakeVerifyTransport:
    """send_config trackt Aufrufe (Config + Save getrennt); send_command liefert Show-Verify."""

    def __init__(self, state: dict[str, int | None]) -> None:
        self._state = state
        self.config_calls: list[list[str]] = []

    async def send_config(self, lines: list[str]) -> str:
        self.config_calls.append(lines)
        for line in lines:
            if line.startswith("switchport access vlan"):
                self._state["vlan"] = int(line.split()[-1])
        if "copy running-config startup-config" in lines:
            return "This operation may take a few minutes.\nConfiguration Saved!"
        return "ok"

    async def send_command(self, command: str) -> str:
        v = self._state.get("vlan")
        if v in (None, 1):
            return "Port: X\nVLAN Membership Mode: Access Mode\nAccess Mode VLAN: 1 (default)"
        return f"Port: X\nVLAN Membership Mode: Access Mode\nAccess Mode VLAN: {v}"


async def test_assign_saves_and_verifies_via_show(db_session) -> None:  # type: ignore[no-untyped-def]
    device = Device(
        hostname="sw",
        mgmt_ip="10.120.10.53",
        vendor="fs",
        device_type=DeviceType.SWITCH,
        adapter_id="fs_centec",
    )
    db_session.add(device)
    await db_session.flush()
    state: dict[str, int | None] = {"vlan": None}
    t = _FakeVerifyTransport(state)
    res = await assign_port_vlan(
        db_session, device, _FakeAdapter(state), t, _SPEC_FULL, "eth-0-5", 103
    )
    assert res.saved is True  # Marker "Configuration Saved" gefunden
    assert res.verified is True  # Show-Verify matcht "Access Mode VLAN: 103"
    # zwei send_config-Aufrufe: Konfig + Save-Sequenz
    assert len(t.config_calls) == 2
    assert t.config_calls[1] == ["enable", "copy running-config startup-config", "y"]


async def test_reset_verify_accepts_missing_access_line(db_session) -> None:  # type: ignore[no-untyped-def]
    device = Device(
        hostname="sw2",
        mgmt_ip="10.120.10.54",
        vendor="fs",
        device_type=DeviceType.SWITCH,
        adapter_id="fs_centec",
    )
    db_session.add(device)
    await db_session.flush()
    state: dict[str, int | None] = {"vlan": 103}
    t = _FakeVerifyTransport(state)
    spec = _SPEC_FULL.model_copy(
        update={"verify_pattern": r"switchport access vlan {vlan}\b"}  # Pattern das NICHT matcht
    )
    res = await reset_port_vlan(db_session, device, _FakeAdapter(state), t, spec, "eth-0-5")
    # Show-Output enthält keine "switchport access vlan"-Zeile -> Reset gilt als verifiziert
    assert res.verified is True and res.vlan_id == 1


def test_all_profiles_have_save_sequences() -> None:
    for adapter_id in ("dell_os10", "dell_os6", "fs_centec", "fs_ruijie", "tplink_jetstream"):
        profile = get_profile(adapter_id)
        assert profile.port_vlan_control.save, adapter_id
        assert profile.lldp_control.save, adapter_id
