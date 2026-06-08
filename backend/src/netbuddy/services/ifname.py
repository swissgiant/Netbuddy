import re

# Lange/kurze Präfix-Schreibweisen → kanonische Kurzform. Damit referenzieren LLDP/MAC denselben
# Port wie die Interface-Liste (OS10 „Eth 1/1/1" vs „ethernet1/1/1"; Cisco „GigabitEthernet1/0/1"
# vs „Gi1/0/1") statt im Graph doppelte Interfaces zu erzeugen.
_PREFIX: dict[str, str] = {
    "ethernet": "eth",
    "eth": "eth",
    "gigabitethernet": "gi",
    "gi": "gi",
    "tengigabitethernet": "te",
    "tengige": "te",
    "te": "te",
    "fortygigabitethernet": "fo",
    "hundredgige": "hu",
    "twentyfivegige": "twe",
    "fastethernet": "fa",
    "fa": "fa",
    "management": "mgmt",
    "mgmt": "mgmt",
    "port-channel": "po",
    "portchannel": "po",
    "po": "po",
    "vlan": "vlan",
    "vl": "vlan",
    "loopback": "lo",
    "lo": "lo",
}

_SPLIT = re.compile(r"^([a-z]+)(\d.*)$")


def normalize_interface_name(name: str) -> str:
    """Kanonischer Schlüssel für einen Interface-Namen (vendor-tolerant, ohne Leerzeichen).

    Trennt das führende Buchstaben-Präfix von der Nummer und mappt das Präfix auf eine
    Kurzform. Unbekannte Präfixe (z.B. FS `eth-0-1`) bleiben unverändert (nur lowercased,
    Leerzeichen entfernt) — innerhalb eines Vendors sind die ohnehin konsistent.
    """
    compact = name.strip().lower().replace(" ", "")
    match = _SPLIT.match(compact)
    if match is None:
        return compact
    alpha, rest = match.group(1), match.group(2)
    return _PREFIX.get(alpha, alpha) + rest
