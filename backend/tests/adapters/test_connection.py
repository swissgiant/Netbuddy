import pytest
from pydantic import SecretStr

from netbuddy.adapters.connection import params_from_credential
from netbuddy.db.models import Credential, Device, DeviceType


def _device(adapter_id: str = "cisco_ios") -> Device:
    return Device(
        hostname="sw-lab-01",
        mgmt_ip="10.0.0.1",
        vendor="cisco",
        device_type=DeviceType.SWITCH,
        adapter_id=adapter_id,
    )


def _credential() -> Credential:
    return Credential(
        name="lab-svc",
        username="svc-netbuddy",
        password="s3cret",
        enable_password="en4ble",
        ssh_port=2222,
    )


def test_params_from_credential_maps_fields() -> None:
    params = params_from_credential(_device(), _credential())
    assert params.host == "10.0.0.1"
    assert params.port == 2222
    assert params.username == "svc-netbuddy"
    assert params.platform == "cisco_iosxe"
    assert isinstance(params.password, SecretStr)
    assert params.password.get_secret_value() == "s3cret"
    assert params.enable_password is not None
    assert params.enable_password.get_secret_value() == "en4ble"


def test_params_without_passwords() -> None:
    cred = Credential(name="c", username="u", ssh_port=22)
    params = params_from_credential(_device(), cred)
    assert params.password is None
    assert params.enable_password is None
    assert params.port == 22


def test_unknown_adapter_id_raises() -> None:
    with pytest.raises(ValueError, match="Scrapli-Plattform"):
        params_from_credential(_device(adapter_id="juniper_junos"), _credential())
