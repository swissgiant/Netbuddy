"""Passwordstate-Import: Einträge einer Passwortliste als NetBuddy-Credentials übernehmen."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from netbuddy.adapters.base import AdapterError
from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Credential
from netbuddy.services.passwordstate import (
    PasswordstateApi,
    PwImportSummary,
    PwPreviewRow,
    import_entries,
    preview,
)

router = APIRouter(prefix="/passwordstate", tags=["passwordstate"])


async def _pw_credential(session: SessionDep) -> Credential:
    stmt = select(Credential).where(
        Credential.deleted_at.is_(None),
        or_(Credential.name.ilike("%passwordstate%"), Credential.base_url.ilike("%pwst%")),
    )
    cred = (await session.execute(stmt)).scalars().first()
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine Passwordstate-Credential (Name „Passwordstate“, base_url + api_token)",
        )
    return cred


def _api(cred: Credential) -> PasswordstateApi:
    try:
        return PasswordstateApi(cred)
    except AdapterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _list_ids(api: PasswordstateApi, list_id: int | None) -> list[int]:
    ids = [list_id] if list_id is not None else api.list_ids
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine PasswordListID: ?list_id=… angeben oder extra.list_ids in der Credential",
        )
    return ids


@router.get("/preview", response_model=list[PwPreviewRow])
async def preview_import(session: SessionDep, list_id: int | None = None) -> list[PwPreviewRow]:
    """Vorschau ohne Passwörter: was würde angelegt/aktualisiert, welche Geräte verknüpft."""
    cred = await _pw_credential(session)
    entries = []
    async with _api(cred) as api:
        for lid in _list_ids(api, list_id):
            try:
                entries += await api.fetch_list(lid)
            except AdapterError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
                ) from exc
    return await preview(session, entries)


@router.post("/import", response_model=PwImportSummary)
async def run_import(
    session: SessionDep, list_id: int | None = None, dry_run: bool = True
) -> PwImportSummary:
    """Einträge übernehmen (Standard: nur Vorschau-Zusammenfassung, ``dry_run=false`` schreibt)."""
    cred = await _pw_credential(session)
    entries = []
    async with _api(cred) as api:
        for lid in _list_ids(api, list_id):
            try:
                entries += await api.fetch_list(lid)
            except AdapterError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
                ) from exc
    return await import_entries(session, entries, dry_run=dry_run)
