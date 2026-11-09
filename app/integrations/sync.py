"""Delivery of the plant's outbound items to the cloud replica through the link proxy."""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from app.persistence.repository import Repository

log = logging.getLogger(__name__)


class CloudSync:
    def __init__(self, repo: Repository, url: str, batch: int = 50,
                 client_factory: Callable[[], httpx.AsyncClient] | None = None):
        self.repo = repo
        self.url = url.rstrip("/")
        self.batch = batch
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=8, trust_env=True))

    async def once(self) -> int:
        items = await self.repo.pending_sync(self.batch)
        if not items:
            return 0
        body = {"items": [{"id": item["id"], "topic": item["topic"], "payload": item["payload"]}
                          for item in items]}
        try:
            async with self.client_factory() as client:
                response = await client.post(f"{self.url}/items", json=body)
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("cloud sync failed with %s pending: %s", len(items), exc)
            await self.repo.bump_sync([item["id"] for item in items])
            return 0
        await self.repo.ack_sync([item["id"] for item in items])
        return len(items)
