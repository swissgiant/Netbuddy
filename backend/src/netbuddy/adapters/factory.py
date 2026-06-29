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
from netbuddy.adapters.tplink_transport import TplinkTransport
from netbuddy.db.models import Credential, Device

# Vendor-korrekte Auth-Header je API-Adapter: (Header-Name, Token-Präfix).
# Per Credential überschreibbar (`extra.auth_header` / `extra.auth_prefix`).
_API_AUTH_DEFAULTS: dict[str, tuple[str, str]] = {
    "fortigate": ("Authorization", "Bearer "),  # FortiOS REST-API-Admin-Token
    "paloalto": ("X-PAN-KEY", ""),  # PAN-OS XML-/REST-API-Key
    "cato": ("x-api-key", ""),  # Cato GraphQL
    "meraki": ("X-Cisco-Meraki-API-Key", ""),  # Meraki Dashboard
    "unifi": ("X-API-KEY", ""),  # UniFi Network Integration API (lokaler Controller)
    "unifi_cloud": ("X-API-KEY", ""),  # UniFi Site Manager Cloud-API (api.ui.com)
}


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
    if device.adapter_id == "unifi_local":
        # unifi_local braucht den lokalen Controller (Cookie-Console, Site→IP) — die Endpoints
        # bauen den Adapter über services.unifi_local, nicht über diesen generischen Pfad.
        raise AdapterError(
            "unifi_local wird über den lokalen Controller-Pfad gebaut, nicht über connect()"
        )
    if adapter_kind(device.adapter_id) == "api":
        if not credential.base_url:
            raise AdapterError(
                f"API-Adapter {device.adapter_id!r} braucht eine base_url in der Credential"
            )
        default_header, default_prefix = _API_AUTH_DEFAULTS.get(
            device.adapter_id, ("X-API-KEY", "")
        )
        header_name = str(credential.extra.get("auth_header", default_header))
        token_prefix = str(credential.extra.get("auth_prefix", default_prefix))
        client = HttpxApiClient(
            credential.base_url,
            token=credential.api_token,
            header_name=header_name,
            token_prefix=token_prefix,
        )
        adapter = get_api_adapter_class(device.adapter_id)(
            client, match_ip=str(device.mgmt_ip), options=credential.extra
        )
        return adapter, client

    params = params_from_credential(device, credential)
    # TP-Link JetStream/Omada: eigener Transport (CR-Zeilenende + nicht abschaltbarer Pager).
    transport: Any = (
        TplinkTransport(params)
        if device.adapter_id == "tplink_jetstream"
        else ScrapliTransport(params)
    )
    return build_adapter(device.adapter_id, transport), transport
