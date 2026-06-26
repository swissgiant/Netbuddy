from netbuddy.adapters.base import (
    AdapterError,
    CapabilityNotSupportedError,
    SwitchAdapter,
)
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.cato import CatoAdapter
from netbuddy.adapters.connection import ConnectionParams, params_from_credential
from netbuddy.adapters.declarative import DeclarativeAdapter
from netbuddy.adapters.dto import (
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
)
from netbuddy.adapters.factory import connect
from netbuddy.adapters.fortigate import FortigateAdapter
from netbuddy.adapters.meraki import MerakiAdapter
from netbuddy.adapters.paloalto import PaloAltoAdapter
from netbuddy.adapters.profile import VendorProfile, load_profile
from netbuddy.adapters.registry import (
    UnknownAdapterError,
    adapter_kind,
    available_adapters,
    build_adapter,
    get_profile,
    provenance_for,
)
from netbuddy.adapters.scrapli_transport import ScrapliTransport
from netbuddy.adapters.transport import (
    CommandTransport,
    MockTransport,
    RecordingTransport,
    TransportError,
)
from netbuddy.adapters.unifi import UnifiAdapter
from netbuddy.adapters.unifi_cloud import UnifiCloudAdapter
from netbuddy.adapters.watchguard import WatchGuardAdapter

__all__ = [
    "AdapterError",
    "Capability",
    "CapabilityNotSupportedError",
    "CatoAdapter",
    "CommandTransport",
    "ConnectionParams",
    "DeclarativeAdapter",
    "FortigateAdapter",
    "InterfaceData",
    "LldpNeighborData",
    "MacEntryData",
    "MerakiAdapter",
    "MockTransport",
    "PaloAltoAdapter",
    "RecordingTransport",
    "ScrapliTransport",
    "SwitchAdapter",
    "SystemInfo",
    "TransportError",
    "UnifiAdapter",
    "UnifiCloudAdapter",
    "UnknownAdapterError",
    "VendorProfile",
    "WatchGuardAdapter",
    "adapter_kind",
    "available_adapters",
    "build_adapter",
    "connect",
    "get_profile",
    "load_profile",
    "params_from_credential",
    "provenance_for",
]
