from pydantic import BaseModel

from netbuddy.db.models import AdminStatus, DeviceType, MacEntryType, OperStatus


class SystemInfo(BaseModel):
    """Vendor-neutrale Geräte-Stammdaten (entspricht `show version` o.ä.).

    ``hostname`` ist optional (Default ``""``): manche Vendor zeigen ihn nur im
    Prompt, nicht im `show`-Output — er kommt dann aus dem Inventar (`Device`).
    """

    hostname: str = ""
    vendor: str
    model: str | None = None
    os_version: str | None = None
    serial_number: str | None = None
    device_type: DeviceType


class InterfaceData(BaseModel):
    """Vendor-neutraler Interface-Zustand."""

    name: str
    if_index: int | None = None
    description: str | None = None
    admin_status: AdminStatus = AdminStatus.UNKNOWN
    oper_status: OperStatus = OperStatus.UNKNOWN
    mac_address: str | None = None
    speed_mbps: int | None = None
    mtu: int | None = None
    interface_type: str | None = None


class LldpNeighborData(BaseModel):
    """Ein per LLDP gesehener Nachbar, lokal verankert an einem Interface-Namen."""

    local_interface: str
    remote_chassis_id: str
    remote_port_id: str
    remote_port_description: str | None = None
    remote_system_name: str | None = None
    remote_system_description: str | None = None
    mgmt_address: str | None = None  # Management-IP des Nachbarn (für Autodiscovery-Crawl)


class MacEntryData(BaseModel):
    """Ein Eintrag der MAC-Address-Table, verankert an einem Interface-Namen."""

    mac_address: str
    interface: str
    vlan_id: int | None = None
    entry_type: MacEntryType = MacEntryType.DYNAMIC
