"""Passwordstate-Import: Einträge einer Passwortliste als NetBuddy-Credentials übernehmen.

Mehrere Passwordstate-Credentials (Name enthält „Passwordstate“, je Passwortliste ein API-Key)
werden alle berücksichtigt: mit ``?list_id=`` wird die Credential genommen, deren Key für diese
Liste gilt; ohne ``list_id`` werden alle in ``extra`` hinterlegten Listen geholt.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from netbuddy.adapters.base import AdapterError
from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Credential
from netbuddy.services.passwordstate import (
    PasswordstateApi,
    PwEntry,
    PwImportSummary,
    PwList,
    PwPreviewRow,
    import_entries,
    preview,
)

router = APIRouter(prefix="/passwordstate", tags=["passwordstate"])


async def _pw_credentials(session: SessionDep) -> list[Credential]:
    stmt = (
        select(Credential)
        .where(
            Credential.deleted_at.is_(None),
            or_(Credential.name.ilike("%passwordstate%"), Credential.base_url.ilike("%pwst%")),
        )
        .order_by(Credential.name)
    )
    creds = list((await session.execute(stmt)).scalars())
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine Passwordstate-Credential (Name „Passwordstate…“, base_url + api_token)",
        )
    return creds


async def _collect(creds: list[Credential], list_id: int | None) -> list[PwEntry]:
    """Einträge holen: mit list_id die passende Credential, sonst alle hinterlegten Listen."""
    entries: list[PwEntry] = []
    errors: list[str] = []
    for cred in creds:
        try:
            api = PasswordstateApi(cred)
        except AdapterError as exc:
            errors.append(f"{cred.name}: {exc}")
            continue
        ids = [list_id] if list_id is not None else api.list_ids
        async with api:
            for lid in ids:
                try:
                    entries += await api.fetch_list(lid)
                    if list_id is not None:
                        return entries
                except AdapterError as exc:
                    errors.append(f"{cred.name}: {exc}")
    if entries:
        return entries
    if list_id is None and not any(PasswordstateApi(c).list_ids for c in creds if c.api_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine PasswordListID: ?list_id=… angeben oder im Credential-Formularfeld "
            "(site / org_id / account_id, mehrere mit Komma) hinterlegen; mit System-Wide-Key "
            "zeigt „Listen“ die IDs",
        )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="; ".join(errors) or "Passwordstate lieferte keine Einträge",
    )


@router.get("/lists", response_model=list[PwList])
async def list_lists(session: SessionDep) -> list[PwList]:
    """Alle Passwortlisten mit ID (braucht einen System-Wide-API-Key, Listen-Keys nicht)."""
    errors: list[str] = []
    for cred in await _pw_credentials(session):
        try:
            async with PasswordstateApi(cred) as api:
                return await api.fetch_lists()
        except AdapterError as exc:
            errors.append(f"{cred.name}: {exc}")
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(errors))


@router.get("/preview", response_model=list[PwPreviewRow])
async def preview_import(session: SessionDep, list_id: int | None = None) -> list[PwPreviewRow]:
    """Vorschau ohne Passwörter: was würde angelegt/aktualisiert, welche Geräte verknüpft."""
    entries = await _collect(await _pw_credentials(session), list_id)
    return await preview(session, entries)


@router.post("/import", response_model=PwImportSummary)
async def run_import(
    session: SessionDep, list_id: int | None = None, dry_run: bool = True
) -> PwImportSummary:
    """Einträge übernehmen (Standard: nur Zusammenfassung, ``dry_run=false`` schreibt)."""
    entries = await _collect(await _pw_credentials(session), list_id)
    return await import_entries(session, entries, dry_run=dry_run)
