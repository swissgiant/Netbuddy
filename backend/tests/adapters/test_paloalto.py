from typing import Any

import pytest

from netbuddy.adapters import adapter_kind, available_adapters
from netbuddy.adapters.base import CapabilityNotSupportedError
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.paloalto import PaloAltoAdapter
from netbuddy.db.models import DeviceType

_SYSTEM_XML = """<response status="success"><result><system>
  <hostname>fw-pa-01</hostname>
  <model>PA-440</model>
  <sw-version>11.0.3</sw-version>
  <serial>012345678901</serial>
</system></result></response>"""

_ARP_XML = """<response status="success"><result>
  <entries>
    <entry><ip>10.50.0.10</ip><mac>64:9d:99:2f:89:66</mac><interface>ethernet1/2</interface></entry>
    <entry><ip>10.50.0.11</ip><mac></mac><interface>ethernet1/2</interface></entry>
  </entries>
</result></response>"""

_IF_XML = """<response status="success"><result>
  <hw>
    <entry><name>ethernet1/1</name><state>up</state><mac>00:1b:17:00:00:01</mac><speed>1000</speed></entry>
    <entry><name>ethernet1/2</name><state>down</state><mac>00:1b:17:00:00:02</mac><speed>auto</speed></entry>
  </hw>
</result></response>"""


class _FakeClient:
    async def get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        cmd = (params or {}).get("cmd", "")
        if "system" in cmd:
            return _SYSTEM_XML
        if "arp" in cmd:
            return _ARP_XML
        return _IF_XML


def _adapter() -> PaloAltoAdapter:
    return PaloAltoAdapter(_FakeClient())


async def test_system_info() -> None:
    info = await _adapter().get_system_info()
    assert info.hostname == "fw-pa-01"
    assert info.vendor == "paloalto"
    assert info.model == "PA-440"
    assert info.os_version == "11.0.3"
    assert info.device_type is DeviceType.FIREWALL


async def test_arp_skips_incomplete() -> None:
    arp = await _adapter().get_arp()
    assert len(arp) == 1
    assert arp[0].ip_address == "10.50.0.10"
    assert arp[0].interface == "ethernet1/2"


async def test_interfaces() -> None:
    interfaces = await _adapter().get_interfaces()
    by_name = {i.name: i for i in interfaces}
    assert by_name["ethernet1/1"].oper_status.value == "up"
    assert by_name["ethernet1/1"].speed_mbps == 1000
    assert by_name["ethernet1/2"].speed_mbps is None  # "auto"


async def test_unsupported_raise() -> None:
    with pytest.raises(CapabilityNotSupportedError):
        await _adapter().get_lldp_neighbors()


def test_registered() -> None:
    assert adapter_kind("paloalto") == "api"
    assert available_adapters()["paloalto"] == frozenset(
        {Capability.READ_SYSTEM_INFO, Capability.READ_INTERFACES, Capability.READ_ARP}
    )
