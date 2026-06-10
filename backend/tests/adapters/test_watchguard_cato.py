from typing import Any

import pytest

from netbuddy.adapters import adapter_kind, available_adapters
from netbuddy.adapters.base import AdapterError, CapabilityNotSupportedError
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.cato import CatoAdapter, SiteNotFoundError
from netbuddy.adapters.watchguard import WatchGuardAdapter
from netbuddy.db.models import DeviceType

# --- WatchGuard: ehrliches Skeleton -----------------------------------------------------------


class _NoopClient:
    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        raise AssertionError("darf nicht aufgerufen werden")


async def test_watchguard_registers_without_capabilities() -> None:
    assert adapter_kind("watchguard") == "api"
    assert available_adapters()["watchguard"] == frozenset()
    adapter = WatchGuardAdapter(_NoopClient())
    with pytest.raises(CapabilityNotSupportedError):
        await adapter.get_system_info()


# --- Cato: GraphQL-Stammdaten -----------------------------------------------------------------

_SNAPSHOT: dict[str, Any] = {
    "data": {
        "accountSnapshot": {
            "sites": [
                {
                    "id": "123",
                    "info": {"name": "Werk Italien"},
                    "devices": [
                        {
                            "id": "d1",
                            "name": "socket-it",
                            "serial": "CATO123",
                            "version": "23.0",
                            "socketInfo": {"model": "X1500"},
                        }
                    ],
                }
            ]
        }
    }
}


class _FakeGraphql:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def post_json(self, path: str, body: dict[str, Any]) -> Any:
        self.bodies.append(body)
        return _SNAPSHOT


async def test_cato_system_info_for_site() -> None:
    client = _FakeGraphql()
    adapter = CatoAdapter(client, options={"account_id": "42", "site_name": "Werk Italien"})
    info = await adapter.get_system_info()
    assert info.hostname == "Werk Italien"
    assert info.vendor == "cato"
    assert info.model == "X1500"
    assert info.serial_number == "CATO123"
    assert info.device_type is DeviceType.FIREWALL
    assert client.bodies[0]["variables"] == {"accountID": "42"}


async def test_cato_unknown_site_raises() -> None:
    adapter = CatoAdapter(_FakeGraphql(), options={"account_id": "42", "site_name": "gibtsnicht"})
    with pytest.raises(SiteNotFoundError):
        await adapter.get_system_info()


async def test_cato_requires_options() -> None:
    adapter = CatoAdapter(_FakeGraphql(), options={})
    with pytest.raises(AdapterError):
        await adapter.get_system_info()


def test_cato_registered() -> None:
    assert adapter_kind("cato") == "api"
    assert available_adapters()["cato"] == frozenset({Capability.READ_SYSTEM_INFO})
