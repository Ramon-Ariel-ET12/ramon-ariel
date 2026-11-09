"""Cloud replica of plant events. It is deliberately outside the plant network."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="PIA-3 cloud replica")
ITEMS: list[dict] = []
MAX_ITEMS = 20000


@app.get("/health")
def health() -> dict:
    return {"ok": True, "items": len(ITEMS)}


@app.post("/items")
def receive(body: dict) -> dict:
    items = body.get("items") or []
    ITEMS.extend(items)
    if len(ITEMS) > MAX_ITEMS:
        del ITEMS[: len(ITEMS) - MAX_ITEMS]
    return {"ok": True, "received": len(items), "stored": len(ITEMS)}


@app.get("/items")
def list_items(limit: int = 50) -> dict:
    return {"items": ITEMS[-limit:]}
