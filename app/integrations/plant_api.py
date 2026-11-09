"""HTTP client for the plant simulator API.

Plant calls are direct (NO_PROXY): they never leave the plant network.  Only the cloud
replica client goes through the link proxy.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class PlantUnavailable(RuntimeError):
    pass


class PlantClient:
    def __init__(self, base_url: str, timeout: float = 10.0, link_control_url: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.link_control_url = (link_control_url or "").rstrip("/")

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        last: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, trust_env=False) as client:
                    response = await client.request(method, url, **kwargs)
                    response.raise_for_status()
                    if response.headers.get("content-type", "").startswith("application/json"):
                        return response.json()
                    return response.content
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last = exc
                await asyncio.sleep(0.4 * (attempt + 1))
        raise PlantUnavailable(f"{method} {url}: {last}")

    async def get_json(self, path: str, **kwargs) -> Any:
        return await self._request("GET", path, **kwargs)

    async def get_bytes(self, path: str) -> bytes:
        payload = await self._request("GET", path)
        return payload if isinstance(payload, bytes) else str(payload).encode()

    async def download(self, url: str) -> bytes:
        return await self.get_bytes(url)

    async def definition(self) -> dict:
        return await self.get_json("/api/planta")

    async def state(self) -> dict:
        return await self.get_json("/api/estado")

    async def historian(self, tag: str, variable: str, desde: str | None = None,
                        hasta: str | None = None) -> list[dict]:
        params = {}
        if desde:
            params["desde"] = desde
        if hasta:
            params["hasta"] = hasta
        return await self.get_json(f"/api/historian/{tag}/{variable}", params=params)

    async def order_history(self, equipment: str | None = None) -> list[dict]:
        params = {"equipo": equipment} if equipment else {}
        return await self.get_json("/api/historial-ordenes", params=params)

    async def documents(self) -> dict:
        return await self.get_json("/api/documentos")

    async def document(self, doc_id: str) -> dict:
        return await self.get_json(f"/api/documentos/{doc_id}")

    async def fragments(self) -> list[dict]:
        import json

        raw = await self.get_bytes("/documentos/fragmentos.jsonl")
        return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]

    async def retrieval_suite(self) -> list[dict]:
        return await self.get_json("/documentos/evaluacion/retrieval.json")

    async def link_state(self) -> bool:
        """Control port of the link simulator; never proxied."""
        if not self.link_control_url:
            return True
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                response = await client.get(f"{self.link_control_url}/estado")
                response.raise_for_status()
                return bool(response.json().get("arriba", True))
        except httpx.HTTPError:
            return False
