from typing import Annotated

from fastapi import APIRouter, Query

from netbuddy.api.deps import SessionDep
from netbuddy.services.locate import LocateResult, locate

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[LocateResult])
async def search_endpoints(
    session: SessionDep, q: Annotated[str, Query(min_length=1)]
) -> list[LocateResult]:
    """Findet (End-)Geräte per MAC / Name / IP und liefert Switch + Port, wo sie hängen."""
    return await locate(session, q)
