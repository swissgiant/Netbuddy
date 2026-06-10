import httpx

from netbuddy.adapters.factory import connect
from netbuddy.db.models import Credential, Device, DeviceType


def _device(adapter_id: str) -> Device:
    return Device(
        hostname="fw",
        mgmt_ip="10.0.0.1",
        vendor="x",
        device_type=DeviceType.FIREWALL,
        adapter_id=adapter_id,
    )


def _cred(**extra: str) -> Credential:
    return Credential(name="api", base_url="https://10.0.0.1", api_token="SECRET", extra=extra)


def _auth_headers(client: object) -> httpx.Headers:
    inner: httpx.AsyncClient = client._client  # type: ignore[attr-defined]
    return inner.headers


def test_fortigate_uses_bearer_authorization() -> None:
    _adapter, client = connect(_device("fortigate"), _cred())
    assert _auth_headers(client)["Authorization"] == "Bearer SECRET"


def test_paloalto_uses_pan_key_header() -> None:
    _adapter, client = connect(_device("paloalto"), _cred())
    assert _auth_headers(client)["X-PAN-KEY"] == "SECRET"


def test_meraki_uses_meraki_header() -> None:
    _adapter, client = connect(_device("meraki"), _cred())
    assert _auth_headers(client)["X-Cisco-Meraki-API-Key"] == "SECRET"


def test_credential_extra_overrides_default() -> None:
    _adapter, client = connect(_device("fortigate"), _cred(auth_header="X-Custom", auth_prefix=""))
    headers = _auth_headers(client)
    assert headers["X-Custom"] == "SECRET"
    assert "Authorization" not in headers
