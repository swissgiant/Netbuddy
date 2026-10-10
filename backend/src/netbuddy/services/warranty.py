"""Hersteller-Garantie-/Service-Lookup über den Service-Tag (vorgesehen, Creds folgen).

Alex' Vorgabe: Service-Beginn und „Service abgelaufen" sollen über den Service-Tag von der
Hersteller-API kommen — gemischt **Dell** (TechDirect / Warranty API) und **HPE** sowie weitere.
Das reine Geräte-Passwort reicht dafür nicht; es braucht ein API-Konto je Hersteller (OAuth
Client-ID/Secret), das als :class:`~netbuddy.db.models.Credential` hinterlegt wird
(``name`` z.B. ``"Dell TechDirect"`` / ``"HPE Warranty"``, ``api_token``/``extra.client_secret``).

Dieses Modul kapselt die Provider hinter einem einheitlichen Protokoll, damit die Spalten im
Datenmodell schon stehen und der Lookup nur noch „eingestöpselt" wird, sobald die Konten da sind.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from netbuddy.db.models import Credential, WarrantyStatus


@dataclass(frozen=True)
class WarrantyResult:
    provider: str
    service_start: date | None
    service_end: date | None
    status: WarrantyStatus


class WarrantyProvider(Protocol):
    """Ein Hersteller-Lookup. `vendor_match` sagt, ob er für einen Service-Tag zuständig ist."""

    name: str

    def vendor_match(self, vendor: str | None) -> bool: ...

    async def lookup(self, service_tag: str) -> WarrantyResult | None: ...


class DellWarrantyProvider:
    """Dell TechDirect Warranty API (OAuth2). Creds als Credential „Dell TechDirect".

    Endpunkt (Dokumentation): ``POST https://apigtwb2c.us.dell.com/auth/oauth/v2/token`` für das
    Bearer-Token, dann ``GET /PROD/sbil/scomm/v5/warranty?servicetags=<tag>``. Hier erst
    aktiviert, wenn die Credential vorliegt — bis dahin liefert :meth:`lookup` ``None``.
    """

    name = "Dell TechDirect"

    def __init__(self, credential: Credential | None) -> None:
        self._credential = credential

    def vendor_match(self, vendor: str | None) -> bool:
        return bool(vendor and "dell" in vendor.lower())

    async def lookup(self, service_tag: str) -> WarrantyResult | None:
        if self._credential is None:
            return None
        raise NotImplementedError("Dell-Warranty-Lookup aktivieren, sobald Creds da sind")


class HpeWarrantyProvider:
    """HPE Warranty-Lookup. Creds als Credential „HPE Warranty"."""

    name = "HPE Warranty"

    def __init__(self, credential: Credential | None) -> None:
        self._credential = credential

    def vendor_match(self, vendor: str | None) -> bool:
        return bool(vendor and ("hpe" in vendor.lower() or "hewlett" in vendor.lower()))

    async def lookup(self, service_tag: str) -> WarrantyResult | None:
        if self._credential is None:
            return None
        raise NotImplementedError("HPE-Warranty-Lookup aktivieren, sobald HPE-Creds da sind")


def build_providers(creds_by_name: dict[str, Credential]) -> list[WarrantyProvider]:
    """Baut die verfügbaren Provider; fehlt das Konto, bleibt der Provider inaktiv (lookup→None)."""
    return [
        DellWarrantyProvider(creds_by_name.get("Dell TechDirect")),
        HpeWarrantyProvider(creds_by_name.get("HPE Warranty")),
    ]
