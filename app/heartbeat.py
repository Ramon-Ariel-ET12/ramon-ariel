"""Heartbeat payload, separated for testability."""

from __future__ import annotations

from datetime import UTC, datetime


async def heartbeat_payload(system_name: str, link_up: bool, pending: int) -> dict:
    return {
        "ts": datetime.now(UTC).isoformat(),
        "sistema": system_name,
        "enlace_ok": link_up,
        "pendientes_sincronizar": pending,
    }
