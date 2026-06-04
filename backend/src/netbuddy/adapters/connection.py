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


def _platform_for(adapter_id: str) -> str:
    try:
        return _SCRAPLI_PLATFORM[adapter_id]
    except KeyError as exc:
        raise ValueError(f"Keine Scrapli-Plattform für adapter_id {adapter_id!r}") from exc


def params_from_credential(device: Device, credential: Credential) -> ConnectionParams:
    """Leitet :class:`ConnectionParams` aus einem Gerät und einem Credential ab.

    Reine Mapping-Funktion, kein I/O. Das Passwort wird durch den
    ``EncryptedString``-Spaltentyp beim Lesen bereits entschlüsselt.
    """
    return ConnectionParams(
        host=device.mgmt_ip,
        port=credential.ssh_port,
        username=credential.username or "",
        password=SecretStr(credential.password) if credential.password is not None else None,
        enable_password=(
            SecretStr(credential.enable_password)
            if credential.enable_password is not None
            else None
        ),
        platform=_platform_for(device.adapter_id),
    )
