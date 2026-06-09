import csv
import functools
import importlib.resources

from netbuddy.services.hosts import normalize_mac


@functools.lru_cache(maxsize=1)
def _oui_table() -> dict[str, str]:
    """OUI (6 Hex) → Herstellername. Quelle: gebündelte IEEE/Wireshark-`manuf`-Ableitung."""
    path = importlib.resources.files("netbuddy.adapters") / "data" / "oui.csv"
    table: dict[str, str] = {}
    for row in csv.reader(path.read_text(encoding="utf-8").splitlines()):
        if len(row) >= 2:
            table[row[0]] = row[1]
    return table


def vendor_for_mac(mac: str) -> str | None:
    """Rät den Hersteller aus dem OUI-Anteil einer MAC (None, wenn keine gültige MAC/kein Treffer).

    Nützlich, um LLDP-Nachbarn/Endgeräte einzuordnen, auch wenn sie keine system-description
    melden (z.B. „FS.com", „Dell Inc.", „Fortinet" → Switch/Firewall-Vermutung).
    """
    canonical = normalize_mac(mac)
    if not canonical:
        return None
    return _oui_table().get(canonical[:6])
