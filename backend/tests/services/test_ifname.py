from netbuddy.services.ifname import normalize_interface_name


def test_os10_eth_forms_match() -> None:
    assert normalize_interface_name("Eth 1/1/1") == normalize_interface_name("ethernet1/1/1")
    assert normalize_interface_name("Eth 1/1/1") == "eth1/1/1"


def test_cisco_gi_forms_match() -> None:
    assert normalize_interface_name("GigabitEthernet1/0/1") == normalize_interface_name("Gi1/0/1")
    assert normalize_interface_name("Gi1/0/1") == "gi1/0/1"


def test_fs_centec_unchanged() -> None:
    # unbekanntes Präfix mit Bindestrich bleibt (nur lowercased)
    assert normalize_interface_name("eth-0-1") == "eth-0-1"


def test_misc() -> None:
    assert normalize_interface_name("TenGigabitEthernet 0/49") == "te0/49"
    assert normalize_interface_name("Vlan10") == "vlan10"
    assert normalize_interface_name("PortChannel5") == "po5"
    assert normalize_interface_name("Port-channel5") == "port-channel5"  # Bindestrich → unverändert
    assert normalize_interface_name("CPU") == "cpu"  # kein führendes Zahlsegment → unverändert
