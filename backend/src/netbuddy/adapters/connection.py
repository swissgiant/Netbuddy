from pydantic import BaseModel, SecretStr

from netbuddy.db.models import Credential, Device

# adapter_id → Scrapli-Plattform. ``"generic"`` = kein Core-Treiber → AsyncGenericDriver
# (read-only `show` braucht keine Vendor-Privilege-Logik). Wächst mit jedem Vendor.
_SCRAPLI_PLATFORM = {
    "cisco_ios": "cisco_iosxe",
    "dell_os10": "generic",
    "dell_os6": "generic",
    "fs_centec": "generic",
    "fs_ruijie": "generic",
}

# Diese Adapter brauchen Privileged-Exec (`enable`), bevor Pager-Abschaltung/Reads sauber
# laufen (Dell OS6: `terminal length 0` existiert nur im Enable-Mode, User-Exec paged).
_ENABLE_REQUIRED = {"dell_os6"}

# Paging beim Öffnen abschalten — der GenericDriver kennt Dells/FS' Prompt nicht und würde
# sonst bei langen Ausgaben am `--More--`-Pager hängen (ScrapliTimeout). Core-Treiber (Cisco)
# erledigen das selbst, daher hier nur die generic-Vendors. Reine Session-Einstellung, keine
# Konfig-Änderung → mit „read-only first" vereinbar.
_PAGING_DISABLE = {
    "dell_os10": "terminal length 0",
    "dell_os6": "terminal length 0",
    "fs_centec": "terminal length 0",
    "fs_ruijie": "terminal length 0",
}


class ConnectionParams(BaseModel):
    """Transiente, in-memory Verbindungsdaten für einen SSH-Transport.

    Wird aus :class:`~netbuddy.db.models.Device` + :class:`~netbuddy.db.models.Credential`
    abgeleitet (siehe :func:`params_from_credential`). Passwörter stecken in
    ``SecretStr``, damit sie nicht versehentlich in Logs/Reprs landen — erst der
    Transport packt sie kurz vor dem Verbindungsaufbau aus.
    """

    host: str
    port: int = 22
    username: str
    password: SecretStr | None = None
    enable_password: SecretStr | None = None
    platform: str
    # Scrapli-Transport: "asyncssh" (Default) oder "asynctelnet" (alte Geräte ohne SSH,
    # z.B. Dell OS6 in Werkskonfig). Gesteuert über Credential.extra["transport"]="telnet".
    transport: str = "asyncssh"
    # Befehl zum Abschalten des Pagers beim Öffnen (None = Treiber regelt es selbst).
    paging_command: str | None = None
    # Vor dem Paging-Befehl in den Privileged-Mode wechseln (`enable`, z.B. Dell OS6).
    enable_required: bool = False


def _platform_for(adapter_id: str) -> str:
    try:
        return _SCRAPLI_PLATFORM[adapter_id]
    except KeyError as exc:
        raise ValueError(f"Keine Scrapli-Plattform für adapter_id {adapter_id!r}") from exc


def _transport_and_port(credential: Credential) -> tuple[str, int]:
    """Transport + Port aus der Credential.

    Der Port entscheidet: 22 → SSH, 23 → Telnet (klassische Zuordnung). Bei anderen
    Ports gewinnt das explizite `extra["transport"]` ("ssh"/"telnet", aus der
    GUI-Protokollauswahl); ohne Angabe Default SSH.
    """
    extra = credential.extra or {}
    explicit = str(extra.get("transport", "")).lower()
    port = credential.ssh_port
    if explicit == "telnet":
        return "asynctelnet", (port if port != 22 else 23)
    if explicit == "ssh":
        return "asyncssh", port
    if port == 23:
        return "asynctelnet", port
    return "asyncssh", port


def onboarding_params(device: Device, credential: Credential) -> ConnectionParams:
    """Wie :func:`params_from_credential`, aber erzwingt die `generic`-Plattform.

    Für assistiertes Onboarding eines (noch) unbekannten Geräts: funktioniert ohne dass
    `device.adapter_id` schon einem Vendor zugeordnet ist.
    """
    transport, port = _transport_and_port(credential)
    return ConnectionParams(
        host=str(device.mgmt_ip),
        port=port,
        username=credential.username or "",
        password=SecretStr(credential.password) if credential.password is not None else None,
        enable_password=(
            SecretStr(credential.enable_password)
            if credential.enable_password is not None
            else None
        ),
        platform="generic",
        transport=transport,
        paging_command="terminal length 0",
    )


def params_from_credential(device: Device, credential: Credential) -> ConnectionParams:
    """Leitet :class:`ConnectionParams` aus einem Gerät und einem Credential ab.

    Reine Mapping-Funktion, kein I/O. Das Passwort wird durch den
    ``EncryptedString``-Spaltentyp beim Lesen bereits entschlüsselt.
    """
    transport, port = _transport_and_port(credential)
    return ConnectionParams(
        host=str(device.mgmt_ip),
        port=port,
        username=credential.username or "",
        password=SecretStr(credential.password) if credential.password is not None else None,
        enable_password=(
            SecretStr(credential.enable_password)
            if credential.enable_password is not None
            else None
        ),
        platform=_platform_for(device.adapter_id),
        transport=transport,
        paging_command=_PAGING_DISABLE.get(device.adapter_id),
        enable_required=device.adapter_id in _ENABLE_REQUIRED,
    )
