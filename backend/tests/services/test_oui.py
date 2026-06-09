import pytest

from netbuddy.services.oui import vendor_for_mac


@pytest.mark.parametrize(
    ("mac", "needle"),
    [
        ("64:9d:99:2f:89:66", "Fs Com"),  # FS.com (live von bls-sw-53 bestätigt)
        ("b0:4f:13:39:0e:c0", "Dell"),  # BLS-SW-* Switches
        ("8c:47:be:00:00:01", "Dell"),  # SW1
        ("1c:6a:1b:4a:83:41", "Ubiquiti"),  # BLS-SW-68
        ("d4:76:a0:00:00:01", "Fortinet"),  # BLS-FW1/FW2 Firewalls
        ("0800.2b01.0203", "Digital Equipment"),  # anderes Trennformat → trotzdem aufgelöst
    ],
)
def test_vendor_for_mac_known(mac: str, needle: str) -> None:
    vendor = vendor_for_mac(mac)
    assert vendor is not None
    assert needle.lower() in vendor.lower()


def test_vendor_for_mac_invalid_or_unknown() -> None:
    assert vendor_for_mac("BLS-CLIENT1-DE") is None  # keine MAC (LLDP-chassis = Name)
    assert vendor_for_mac("ffffff") is None  # zu kurz
