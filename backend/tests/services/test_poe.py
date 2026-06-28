from netbuddy.adapters.profile import PoeControlSpec
from netbuddy.services import poe

# Echtes Dell-N2248PX-Format (gekürzt) — gemischte Zustände inkl. PD mit Namen + Power.
_POWER = """\
Unit Status
===========
Power.......................................... On

Port Configuration
==================

Port      Powered Device           State Priority Status     Class                Power[mW]
                                                             (Measured/Assigned)
--------- ------------------------ ----- -------- ---------- -------------------- ---------
Gi1/0/1                            auto  Low      Searching  Unknown/Unknown
Gi1/0/4                            auto  Low      Fault      Unknown/Unknown
Gi1/0/7   BLS-AP-CH-30             auto  Low      On         4/4                  7000
Gi1/0/9                            never Low      Off        Unknown/Unknown
"""

_LINK = """\
Port      Description               Duplex Speed   Neg  Link  Flow  ...
Gi1/0/1                             N/A    Unknown Auto Down  Off
Gi1/0/4                             Full   100     Auto Up    On    A  1
Gi1/0/7                             Full   1000    Auto Up    On    A  1
"""


def test_parse_power_inline_states() -> None:
    ports = poe._parse_dell_os6_power(_POWER)
    assert set(ports) == {"Gi1/0/1", "Gi1/0/4", "Gi1/0/7", "Gi1/0/9"}
    assert ports["Gi1/0/1"].poe_status == "Searching"
    assert ports["Gi1/0/1"].searching and not ports["Gi1/0/1"].faulted
    assert ports["Gi1/0/4"].poe_status == "Fault" and ports["Gi1/0/4"].faulted
    on = ports["Gi1/0/7"]
    assert on.poe_status == "On" and on.delivering and on.poe_state == "auto"
    assert on.poe_class == "4/4" and on.power_mw == 7000
    assert ports["Gi1/0/9"].poe_state == "never" and ports["Gi1/0/9"].poe_status == "Off"


def test_parse_link_status() -> None:
    links = poe._parse_dell_os6_link(_LINK)
    assert links == {"Gi1/0/1": False, "Gi1/0/4": True, "Gi1/0/7": True}


class _FakeTransport:
    def __init__(self, power: str, link: str) -> None:
        self._power, self._link = power, link

    async def send_command(self, command: str) -> str:
        return self._power if "power" in command else self._link

    async def send_config(self, lines: list[str]) -> str:  # pragma: no cover - nicht genutzt
        return ""


async def test_scan_poe_merges_link() -> None:
    ports = {p.port: p for p in await poe.scan_poe(_FakeTransport(_POWER, _LINK), PoeControlSpec())}
    assert ports["Gi1/0/1"].link_up is False
    assert ports["Gi1/0/4"].link_up is True
    # Gi1/0/9 hat keine Link-Zeile → None (unbekannt)
    assert ports["Gi1/0/9"].link_up is None


async def test_scan_poe_board_without_poe_is_empty() -> None:
    fake = _FakeTransport("This board doesn't support poe!\n", _LINK)
    assert await poe.scan_poe(fake, PoeControlSpec()) == []


def test_is_stuck_rules() -> None:
    fault_down = poe.PoePort(port="Gi1/0/4", poe_status="Fault", link_up=False)
    fault_up = poe.PoePort(port="Gi1/0/4", poe_status="Fault", link_up=True)
    searching_down = poe.PoePort(port="Gi1/0/9", poe_status="Searching", link_up=False)
    on_down = poe.PoePort(port="Gi1/0/7", poe_status="On", link_up=False)

    assert poe.is_stuck(fault_down, "offline") is True
    assert poe.is_stuck(searching_down, "offline") is True
    # gesundes, selbst-versorgtes Gerät (Link up) → nie stuck, auch bei Fault
    assert poe.is_stuck(fault_up, "offline") is False
    # AP online → kein Eingriff
    assert poe.is_stuck(fault_down, "online") is False
    # delivering/On → kein Stör-Status
    assert poe.is_stuck(on_down, "offline") is False
