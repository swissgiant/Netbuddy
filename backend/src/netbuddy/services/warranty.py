"""Hersteller-Garantie-/Service-Lookup über den Service-Tag (vorgesehen, Creds folgen).

Alex' Vorgabe: Service-Beginn und „Service abgelaufen" sollen über den Service-Tag von der
Hersteller-API kommen — gemischt **Dell** (TechDirect / Warranty API) und **HPE** sowie weitere.
Das reine Geräte-Passwort reicht dafür nicht; es braucht ein API-Konto je Hersteller (OAuth
Client-ID/Secret), das als :class:`~netbuddy.db.models.Credential` hinterlegt wird
(``name`` z.B. ``"Dell TechDirect"`` / ``"HPE Warranty"``, ``api_token``/``extra.client_secret``).

Dieses Modul kapselt die Provider hinter einem einheitlichen Protokoll, damit die Spalten im
Datenmodell schon stehen und der Lookup nur noch „eingestöpselt" wird, sobald die Konten da sind.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import httpx
from loguru import logger

from netbuddy.db.models import Credential, WarrantyStatus

_UA = {"User-Agent": "Mozilla/5.0"}


@dataclass(frozen=True)
class WarrantyResult:
    provider: str
    service_start: date | None
    service_end: date | None
    status: WarrantyStatus


def _parse_date(value: Any) -> date | None:
    """Dell liefert ISO-Strings (``2021-08-15T00:00:00`` / ``...Z``) — Zeitanteil abschneiden."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _ci(obj: dict[str, Any], *names: str) -> Any:
    """Case-insensitiver Key-Zugriff (Dell mischt camelCase/PascalCase)."""
    lower = {k.lower(): v for k, v in obj.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


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
    _TOKEN_URL = "https://apigtwb2c.us.dell.com/auth/oauth/v2/token"
    _WARRANTY_URL = "https://apigtwb2c.us.dell.com/PROD/sbil/scomm/v5/warranty"

    def __init__(self, credential: Credential | None) -> None:
        self._credential = credential
        self._token: str | None = None
        self._token_exp: datetime = datetime.now(UTC)

    def vendor_match(self, vendor: str | None) -> bool:
        return bool(vendor and "dell" in vendor.lower())

    async def _bearer(self, client: httpx.AsyncClient) -> str:
        if self._token and datetime.now(UTC) < self._token_exp:
            return self._token
        assert self._credential is not None
        extra = self._credential.extra or {}
        secret = self._credential.password or str(extra.get("client_secret") or "")
        resp = await client.post(
            str(extra.get("token_url") or self._TOKEN_URL),
            data={
                "grant_type": "client_credentials",
                "client_id": self._credential.api_token or "",
                "client_secret": secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = str(body["access_token"])
        # Token ist 1 h gültig -> mit Puffer 55 min cachen.
        self._token_exp = datetime.now(UTC) + timedelta(
            seconds=int(body.get("expires_in", 3600)) - 300
        )
        return self._token

    def _to_result(self, asset: dict[str, Any]) -> WarrantyResult:
        ents = _ci(asset, "entitlements", "Entitlements") or []
        ends = [d for e in ents if (d := _parse_date(_ci(e, "endDate", "EndDate")))]
        starts = [d for e in ents if (d := _parse_date(_ci(e, "startDate", "StartDate")))]
        ship = _parse_date(_ci(asset, "shipDate", "ShipDate"))
        end = max(ends) if ends else None
        start = ship or (min(starts) if starts else None)
        if end is None:
            status = WarrantyStatus.UNKNOWN
        elif end >= date.today():
            status = WarrantyStatus.ACTIVE
        else:
            status = WarrantyStatus.EXPIRED
        return WarrantyResult(
            provider=self.name, service_start=start, service_end=end, status=status
        )

    async def lookup_many(self, service_tags: list[str]) -> dict[str, WarrantyResult]:
        """Batch-Abfrage (Dell erlaubt bis ~100 Tags je Call, komma-separiert)."""
        if self._credential is None or not service_tags:
            return {}
        extra = self._credential.extra or {}
        url = str(extra.get("warranty_url") or self._WARRANTY_URL)
        out: dict[str, WarrantyResult] = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._bearer(client)
            for i in range(0, len(service_tags), 100):
                batch = service_tags[i : i + 100]
                resp = await client.get(
                    url,
                    params={"servicetags": ",".join(batch)},
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                assets = (
                    data
                    if isinstance(data, list)
                    else (_ci(data, "assetWarrantyResponse", "entitlements", "assets") or [])
                )
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    tag = _ci(asset, "serviceTag", "ServiceTag", "id")
                    if tag:
                        out[str(tag).upper()] = self._to_result(asset)
        return out

    async def lookup(self, service_tag: str) -> WarrantyResult | None:
        if self._credential is None:
            return None
        return (await self.lookup_many([service_tag])).get(service_tag.upper())


class HpeWarrantyProvider:
    """HPE Warranty-Lookup. Creds als Credential „HPE Warranty"."""

    name = "HPE Warranty"

    def __init__(self, credential: Credential | None) -> None:
        self._credential = credential

    def vendor_match(self, vendor: str | None) -> bool:
        return bool(vendor and ("hpe" in vendor.lower() or "hewlett" in vendor.lower()))

    async def lookup(self, service_tag: str) -> WarrantyResult | None:
        # Noch nicht implementiert (keine freie HPE-Warranty-API) -> ruhig None, nie crashen.
        if self._credential is not None:
            logger.warning("HPE-Warranty-Lookup noch nicht implementiert (Credential vorhanden)")
        return None


class LenovoWarrantyProvider:
    """Lenovo Support-Warranty-API. Credential „Lenovo Warranty", ``api_token`` = ClientID.

    Endpoint ``https://supportapi.lenovo.com/v2.5/warranty`` (GET ``?Serial=<sn>`` einzeln bzw.
    POST ``Serial=<sn1,sn2,…>`` als Batch), Auth über den Header ``ClientID`` (KEIN Bearer).
    ClientID ist nicht self-service → über den Lenovo-Partner-/Account-Manager. Antwort je Gerät:
    ``Serial, Product, InWarranty, Purchased, Shipped, Warranty[{Start,End,Name,Type}]``.
    """

    name = "Lenovo Warranty"
    _URL = "https://supportapi.lenovo.com/v2.5/warranty"

    def __init__(self, credential: Credential | None) -> None:
        self._credential = credential

    def vendor_match(self, vendor: str | None) -> bool:
        return bool(vendor and "lenovo" in vendor.lower())

    def _to_result(self, item: dict[str, Any]) -> WarrantyResult:
        warr = _ci(item, "Warranty", "warranty") or []
        ends = [d for w in warr if (d := _parse_date(_ci(w, "End", "end")))]
        starts = [d for w in warr if (d := _parse_date(_ci(w, "Start", "start")))]
        ship = _parse_date(_ci(item, "Shipped", "shipped")) or _parse_date(
            _ci(item, "Purchased", "purchased")
        )
        end = max(ends) if ends else None
        start = ship or (min(starts) if starts else None)
        in_warr = _ci(item, "InWarranty", "inWarranty")
        if in_warr is True or (end is not None and end >= date.today()):
            status = WarrantyStatus.ACTIVE
        elif end is not None:
            status = WarrantyStatus.EXPIRED
        else:
            status = WarrantyStatus.UNKNOWN
        return WarrantyResult(
            provider=self.name, service_start=start, service_end=end, status=status
        )

    def _result(self, start: date | None, end: date | None) -> WarrantyResult:
        if end is not None and end >= date.today():
            status = WarrantyStatus.ACTIVE
        elif end is not None:
            status = WarrantyStatus.EXPIRED
        else:
            status = WarrantyStatus.UNKNOWN
        return WarrantyResult(
            provider=self.name, service_start=start, service_end=end, status=status
        )

    @staticmethod
    def _json_array_after(html: str, key: str) -> list[dict[str, Any]]:
        """Balanced-Bracket-Extraktion des Arrays hinter ``"key":`` aus der Support-Seite."""
        i = html.find(f'"{key}"')
        if i < 0:
            return []
        j = html.find("[", i)
        if j < 0:
            return []
        depth = 0
        for k in range(j, len(html)):
            if html[k] == "[":
                depth += 1
            elif html[k] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(html[j : k + 1])
                        return parsed if isinstance(parsed, list) else []
                    except Exception:
                        return []
        return []

    async def _public_one(
        self, client: httpx.AsyncClient, serial: str
    ) -> WarrantyResult | None:
        """Konto-frei: öffentliche pcsupport-Seite parsen (Base-/UpgradeWarranties)."""
        try:
            mse = await client.get(
                "https://pcsupport.lenovo.com/us/en/api/v4/mse/getproducts",
                params={"productId": serial},
                headers=_UA,
            )
            rows = mse.json()
            pid = rows[0]["Id"] if rows else None
            if not pid:
                return None
            page = await client.get(
                f"https://pcsupport.lenovo.com/us/en/products/{pid.lower()}/warranty", headers=_UA
            )
            html = page.text
            warr = self._json_array_after(html, "BaseWarranties") + self._json_array_after(
                html, "UpgradeWarranties"
            )
            starts = [d for w in warr if (d := _parse_date(_ci(w, "Start", "StartDate")))]
            ends = [d for w in warr if (d := _parse_date(_ci(w, "End", "EndDate")))]
            if not starts and not ends:
                return None
            return self._result(min(starts) if starts else None, max(ends) if ends else None)
        except Exception as exc:
            logger.warning(f"Lenovo Public-Lookup {serial}: {type(exc).__name__}")
            return None

    async def lookup_many(self, service_tags: list[str]) -> dict[str, WarrantyResult]:
        if not service_tags:
            return {}
        out: dict[str, WarrantyResult] = {}
        # Mit ClientID -> offizielle API (Batch); sonst konto-frei über die öffentliche Seite.
        if self._credential and self._credential.api_token:
            extra = self._credential.extra or {}
            url = str(extra.get("warranty_url") or self._URL)
            headers = {"ClientID": self._credential.api_token, "Accept": "application/json"}
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    url, data={"Serial": ",".join(service_tags)}, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data if isinstance(data, list) else [data]:
                    if isinstance(item, dict) and (sn := _ci(item, "Serial", "serial")):
                        out[str(sn).upper()] = self._to_result(item)
            return out
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:

            async def one(tag: str) -> None:
                async with sem:
                    r = await self._public_one(client, tag)
                if r:
                    out[tag.upper()] = r

            await asyncio.gather(*[one(t) for t in service_tags])
        return out

    async def lookup(self, service_tag: str) -> WarrantyResult | None:
        # Lenovo geht auch ohne Credential (öffentliche Seite) -> keine None-Schranke.
        return (await self.lookup_many([service_tag])).get(service_tag.upper())


def build_providers(creds_by_name: dict[str, Credential]) -> list[WarrantyProvider]:
    """Baut die verfügbaren Provider; fehlt das Konto, bleibt der Provider inaktiv (lookup→None)."""
    return [
        DellWarrantyProvider(creds_by_name.get("Dell TechDirect")),
        HpeWarrantyProvider(creds_by_name.get("HPE Warranty")),
        LenovoWarrantyProvider(creds_by_name.get("Lenovo Warranty")),
    ]


@dataclass
class WarrantySummary:
    checked: int = 0
    active: int = 0
    expired: int = 0
    unknown: int = 0
    no_provider: int = 0  # Vendor ohne aktives Hersteller-Konto
    errors: list[str] = field(default_factory=list)
    oldest: list[str] = field(default_factory=list)  # "hostname: shipdate" der ältesten


async def enrich_warranty(session: Any, *, sites: list[str] | None = None) -> WarrantySummary:
    """Zieht Service-Beginn/-Ende je Service-Tag von der Hersteller-API und schreibt sie auf
    ``PhysicalServer``. Ohne hinterlegtes Hersteller-Konto bleibt der jeweilige Vendor inaktiv.
    """
    from sqlalchemy import select

    from netbuddy.db.models import Site
    from netbuddy.db.models.physical_server import PhysicalServer

    summary = WarrantySummary()
    creds = {
        c.name: c
        for c in (await session.execute(select(Credential).where(Credential.deleted_at.is_(None))))
        .scalars()
        .all()
        if c.name in ("Dell TechDirect", "HPE Warranty", "Lenovo Warranty")
    }
    providers = build_providers(creds)

    conds = [PhysicalServer.deleted_at.is_(None), PhysicalServer.service_tag.isnot(None)]
    if sites:
        ids = set(
            (await session.execute(select(Site.id).where(Site.name.in_(sites)))).scalars().all()
        )
        conds.append(PhysicalServer.site_id.in_(ids))
    servers = (await session.execute(select(PhysicalServer).where(*conds))).scalars().all()

    now = datetime.now(UTC)
    for provider in providers:
        group = [s for s in servers if provider.vendor_match(s.vendor) and s.service_tag]
        if not group:
            continue
        tags = [str(s.service_tag) for s in group]
        results: dict[str, WarrantyResult] = {}
        try:
            lookup_many = getattr(provider, "lookup_many", None)
            if lookup_many is not None:
                results = await lookup_many(tags)
            else:
                for tag in tags:
                    r = await provider.lookup(tag)
                    if r:
                        results[tag.upper()] = r
        except Exception as exc:  # Provider inaktiv/Fehler -> nicht die ganze Inventur kippen
            summary.errors.append(f"{provider.name}: {type(exc).__name__}: {str(exc)[:80]}")
            continue
        if not results and creds.get(provider.name) is None:
            summary.no_provider += len(group)
            continue
        for srv in group:
            res = results.get(str(srv.service_tag).upper())
            if res is None:
                continue
            srv.warranty_provider = res.provider
            srv.warranty_start = res.service_start
            srv.warranty_end = res.service_end
            srv.warranty_status = res.status
            srv.warranty_checked_at = now
            summary.checked += 1
            if res.status == WarrantyStatus.ACTIVE:
                summary.active += 1
            elif res.status == WarrantyStatus.EXPIRED:
                summary.expired += 1
            else:
                summary.unknown += 1
            if res.service_start:
                summary.oldest.append(f"{srv.hostname}: {res.service_start.isoformat()}")

    summary.oldest.sort(key=lambda x: x.split(": ")[-1])
    summary.oldest = summary.oldest[:10]
    await session.commit()
    return summary
