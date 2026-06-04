from netbuddy.adapters import MockTransport
from netbuddy.adapters.scrapli_transport import _is_read_only
from netbuddy.services.onboarding import parse_show_help, pick_candidates, suggest_profile

_HELP = """\
  version        System hardware and software status
  interface      Interface status and configuration
  lldp           LLDP neighbor information
  mac            MAC address table
  running-config Current operating configuration
  <cr>
"""

_RESPONSES = {
    "show ?": _HELP,
    "show version": "Model X, Version 1.2.3",
    "show interface": "Gi0/1 up",
    "show lldp": "neighbor core-sw on Gi0/1",
    "show mac": "vlan 1 aabb.ccdd.eeff Gi0/1",
}


def test_parse_and_pick() -> None:
    entries = parse_show_help(_HELP)
    assert ("version", "System hardware and software status") in entries
    chosen = pick_candidates(entries)
    cmds = {cap.value: cmd for cap, (cmd, _desc) in chosen.items()}
    assert cmds["read_system_info"] == "show version"
    assert cmds["read_interfaces"] == "show interface"
    assert cmds["read_lldp"] == "show lldp"
    assert cmds["read_mac_table"] == "show mac"


async def test_suggest_profile_captures_raw() -> None:
    draft = await suggest_profile(MockTransport(_RESPONSES), suggested_adapter_id="unknown_x")
    assert draft.suggested_adapter_id == "unknown_x"
    by_cap = {c.capability.value: c for c in draft.capabilities}
    assert by_cap["read_system_info"].command == "show version"
    assert by_cap["read_system_info"].raw_excerpt == "Model X, Version 1.2.3"
    assert all(c.command is not None for c in draft.capabilities)


async def test_suggest_profile_missing_candidate() -> None:
    # Hilfe ohne LLDP → read_lldp ohne Kandidaten
    help_no_lldp = "  version  status\n  interface  ports\n  mac  table\n"
    draft = await suggest_profile(
        MockTransport(
            {"show ?": help_no_lldp, "show version": "v", "show interface": "i", "show mac": "m"}
        )
    )
    lldp = next(c for c in draft.capabilities if c.capability.value == "read_lldp")
    assert lldp.command is None


def test_read_only_guard_allows_help() -> None:
    assert _is_read_only("show ?")
    assert _is_read_only("?")
    assert _is_read_only("help")
    assert _is_read_only("show version")
    assert not _is_read_only("configure terminal")
    assert not _is_read_only("write memory")
