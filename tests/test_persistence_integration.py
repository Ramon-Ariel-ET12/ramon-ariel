from __future__ import annotations

import os
from datetime import UTC

import pytest

from app.persistence.db import Database
from app.persistence.repository import Repository

URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.integration
async def test_repository_idempotency_and_queue():
    if not URL:
        pytest.skip("set TEST_DATABASE_URL to run persistence integration tests")
    db = Database(URL)
    await db.connect()
    repo = Repository(db)
    note_id = "TEST-NOTE-1"
    from datetime import datetime

    now = datetime.now(UTC)
    first = await repo.create_note(note_id, now, "tester", "rec", None, [], False)
    second = await repo.create_note(note_id, now, "tester", "rec", None, [], False)
    assert first is True and second is False
    await repo.save_part(note_id, "confirmed", [{"tag": "B-101", "variable": "x", "value": 1.0}], None, 1)
    part = await repo.get_part(note_id)
    assert part["status"] == "confirmed"
    await repo.enqueue("sistema/eventos", {"id": "e1"})
    pending = await repo.pending_sync()
    assert pending
    await repo.ack_sync([item["id"] for item in pending])
    assert await repo.pending_count() == 0
    await db.close()
