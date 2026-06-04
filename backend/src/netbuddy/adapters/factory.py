from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.connection import params_from_credential
from netbuddy.adapters.registry import build_adapter
from netbuddy.adapters.scrapli_transport import ScrapliTransport
from netbuddy.db.models import Credential, Device


def connect(device: Device, credential: Credential) -> tuple[SwitchAdapter, ScrapliTransport]:
    """Baut einen einsatzbereiten Adapter + offenen-fähigen Transport für ein Gerät.

    Verbindet noch nicht — der Aufrufer öffnet den Transport als async Context-Manager::

        adapter, transport = connect(device, credential)
        async with transport:
            info = await adapter.get_system_info()

    Wählt den Transport anhand von ``device.adapter_id`` (Plattform-Map in
    :mod:`netbuddy.adapters.connection`); read-only.
    """
    transport = ScrapliTransport(params_from_credential(device, credential))
    adapter = build_adapter(device.adapter_id, transport)
    return adapter, transport
