import enum


class Capability(enum.StrEnum):
    """Read/write features an adapter can perform on a device.

    Stored per device in ``Device.capabilities`` (JSONB) and reported by each
    adapter via :meth:`SwitchAdapter.capabilities`. The frontend greys out
    features whose capability an adapter does not advertise.
    """

    READ_SYSTEM_INFO = "read_system_info"
    READ_INTERFACES = "read_interfaces"
    READ_LLDP = "read_lldp"
    READ_MAC_TABLE = "read_mac_table"
    READ_CONFIG = "read_config"  # laufende Konfiguration als Roh-Text (für Backup/Diff)
