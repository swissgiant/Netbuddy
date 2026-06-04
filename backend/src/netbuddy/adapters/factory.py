from typing import Any

from netbuddy.adapters.api_client import HttpxApiClient
from netbuddy.adapters.base import AdapterError, SwitchAdapter
from netbuddy.adapters.connection import params_from_credential
from netbuddy.adapters.registry import (
    adapter_kind,
    build_adapter,
    get_api_adapter_class,
)
from netbuddy.adapters.scrapli_transport import ScrapliTransport
from netbuddy.db.models import Credential, Device


def connect(device: Device, credential: Credential) -> tuple[SwitchAdapter, Any]:
    """Baut einen einsatzbereiten Adapter + offenbare Ressource (async Context-Manager).

    Wählt anhand von ``device.adapter_id`` zwischen den zwei Integrations-Klassen:
    CLI/TextFSM (Scrapli-Transport) oder JSON-API (HTTP-Client). Der Aufrufer öffnet die
    Ressource::

        adapter, resource = connect(device, credential)
        async with resource:
            info = await adapter.get_system_info()

    Read-only.
    """
    if adapter_kind(device.adapter_id) == "api":
        if not credential.base_url:
            raise AdapterError(
                f"API-Adapter {device.adapter_id!r} braucht eine base_url in der Credential"
            )
        header_name = str(credential.extra.get("auth_header", "X-API-KEY"))
        client = HttpxApiClient(
            credential.base_url, token=credential.api_token, header_name=header_name
        )
        adapter = get_api_adapter_class(device.adapter_id)(
            client, match_ip=str(device.mgmt_ip), options=credential.extra
        )
        return adapter, client

    transport = ScrapliTransport(params_from_credential(device, credential))
    return build_adapter(device.adapter_id, transport), transport
