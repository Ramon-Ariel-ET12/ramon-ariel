"""PostgreSQL access with a small async pool and idempotent migrations."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)
SCHEMA = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: AsyncConnectionPool | None = None

    async def connect(self, attempts: int = 40, delay: float = 1.5) -> None:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                self.pool = AsyncConnectionPool(conninfo=self.url, min_size=1, max_size=6, open=False,
                                                kwargs={"row_factory": dict_row})
                await self.pool.open(wait=True, timeout=8)
                await self.migrate()
                log.info("database connected")
                return
            except Exception as exc:  # noqa: BLE001
                last = exc
                if self.pool is not None:
                    try:
                        await self.pool.close()
                    except Exception:  # noqa: BLE001
                        pass
                log.warning("database not ready (attempt %s): %s", attempt + 1, exc)
                await asyncio.sleep(delay)
        raise RuntimeError(f"database unavailable: {last}")

    async def migrate(self) -> None:
        assert self.pool is not None
        script = SCHEMA.read_text(encoding="utf-8")
        statements = [part.strip() for part in script.split(";") if part.strip()]
        async with self.pool.connection() as conn:
            for statement in statements:
                await conn.execute(statement)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    async def execute(self, sql: str, params: tuple | list = ()) -> None:
        assert self.pool is not None
        async with self.pool.connection() as conn:
            await conn.execute(sql, params)

    async def fetch(self, sql: str, params: tuple | list = ()) -> list[dict]:
        assert self.pool is not None
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return await cur.fetchall()

    async def fetchrow(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = await self.fetch(sql, params)
        return rows[0] if rows else None

    async def health(self) -> bool:
        try:
            row = await self.fetchrow("SELECT 1 AS ok")
            return bool(row and row["ok"] == 1)
        except Exception:  # noqa: BLE001
            return False
