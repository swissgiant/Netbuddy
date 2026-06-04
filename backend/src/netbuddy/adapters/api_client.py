from types import TracebackType
from typing import Any, Protocol

import httpx


class ApiClient(Protocol):
    """Minimaler async HTTP-JSON-Client, den API-Adapter nutzen (fake-bar in Tests)."""

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any: ...


class HttpxApiClient:
    """`ApiClient` auf httpx-Basis; async Context-Manager managt den Connection-Pool.

    Für Controller-APIs (UniFi/Meraki/…). Token wird als Header gesetzt (Default `X-API-KEY`,
    via `header_name` überschreibbar). `verify=False` als pragmatischer Default für On-Prem-
    Controller mit Self-Signed-Zertifikat (read-only).
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        header_name: str = "X-API-KEY",
        verify: bool = False,
    ) -> None:
        headers = {header_name: token} if token else None
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers, verify=verify)

    async def __aenter__(self) -> "HttpxApiClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()
