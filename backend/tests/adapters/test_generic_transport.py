from scrapli.driver.generic import AsyncGenericDriver

from netbuddy.adapters.connection import ConnectionParams, params_from_credential
from netbuddy.adapters.scrapli_transport import _build_async_scrapli
from netbuddy.db.models import Credential, Device, DeviceType


def _params(platform: str) -> ConnectionParams:
    return ConnectionParams(host="10.0.0.1", username="svc", platform=platform)


def test_unknown_platform_uses_generic_driver() -> None:
    driver = _build_async_scrapli(_params("generic"))
    assert isinstance(driver, AsyncGenericDriver)


def test_known_platform_uses_core_driver() -> None:
    driver = _build_async_scrapli(_params("cisco_iosxe"))
    # scrapli-Factory liefert für cisco_iosxe den Netzwerk-Treiber (keinen GenericDriver)
    assert driver.__class__.__name__ == "AsyncIOSXEDriver"


def test_dell_fs_adapters_map_to_generic_platform() -> None:
    for adapter_id in ("dell_os10", "dell_os6", "fs_centec", "fs_ruijie"):
        device = Device(
            hostname="h",
            mgmt_ip="10.0.0.1",
            vendor="x",
            device_type=DeviceType.SWITCH,
            adapter_id=adapter_id,
        )
        params = params_from_credential(device, Credential(name="c", username="u", ssh_port=22))
        assert params.platform == "generic"
