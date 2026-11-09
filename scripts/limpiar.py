"""Retention job (run manually on the plant PC).

    python scripts/limpiar.py [--dias-media 90] [--dias-transcripcion 90]

Keeps the operational record for one year and drops heavy media after the configured
window. It is never in the critical path.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import get_settings
from app.persistence.db import Database


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias-media", type=int, default=90)
    parser.add_argument("--dias-transcripcion", type=int, default=90)
    parser.add_argument("--dias-cola", type=int, default=30)
    parser.add_argument("--dias-uso", type=int, default=365)
    args = parser.parse_args()
    settings = get_settings()
    now = datetime.now(UTC)

    media = Path(settings.media_dir)
    removed = 0
    if media.exists():
        cutoff = (now - timedelta(days=args.dias_media)).timestamp()
        for folder in media.glob("photos/*"):
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
    db = Database(settings.database_url)
    await db.connect()
    try:
        await db.execute("UPDATE notes SET transcript = NULL WHERE received_at < %s",
                         (now - timedelta(days=args.dias_transcripcion),))
        await db.execute("DELETE FROM sync_queue WHERE acked AND created_at < %s",
                         (now - timedelta(days=args.dias_cola),))
        await db.execute("DELETE FROM usage_log WHERE created_at < %s",
                         (now - timedelta(days=args.dias_uso),))
        print(f"medios borrados: {removed}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
