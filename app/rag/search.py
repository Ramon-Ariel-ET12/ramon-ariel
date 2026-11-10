"""Manual retrieval: pgvector hybrid in production, in-memory hybrid offline."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import Settings
from app.domain.equipment import EquipmentIndex, preprocess
from app.domain.models import PlantSnapshot
from app.domain.numbers import tokenize
from app.persistence.repository import Repository
from app.rag.bm25 import HybridIndex, expand_query, metadata_weight, rrf
from app.rag.indexer import Embedder

log = logging.getLogger(__name__)


def equipment_tags(query: str, snapshot: PlantSnapshot) -> set[str]:
    index = EquipmentIndex(snapshot)
    return {mention.tag for mention in index.find_mentions(tokenize(preprocess(query)))}


class ManualSearch:
    def __init__(self, repo: Repository, settings: Settings, snapshot: PlantSnapshot):
        self.repo = repo
        self.settings = settings
        self.snapshot = snapshot
        self.embedder = Embedder(settings.embedding_model)
        self._memory: HybridIndex | None = None

    def _bundled(self) -> list[dict]:
        path = Path(self.settings.evaluation_dir) / "fragmentos.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _memory_index(self) -> HybridIndex:
        if self._memory is None:
            self._memory = HybridIndex(self._bundled(), self.embedder)
        return self._memory

    async def search(self, query: str, k: int = 8) -> list[dict]:
        tags = equipment_tags(query, self.snapshot)
        try:
            if await self.repo.rag_count() > 0:
                return await self._search_db(query, k, tags)
        except Exception as exc:  # noqa: BLE001
            log.warning("database retrieval failed, using memory: %s", exc)
        return self._memory_index().search(query, k, tags)

    async def _search_db(self, query: str, k: int, tags: set[str]) -> list[dict]:
        lexical_rows = await self.repo.rag_lexical(expand_query(query), 40)
        rankings = [[row["citation"] for row in lexical_rows]]
        rows_by_citation = {row["citation"]: row for row in lexical_rows}
        try:
            import asyncio

            query_vector = await asyncio.to_thread(self.embedder.query, query)
            vector_rows = await self.repo.rag_vector(query_vector, 40)
            rankings.append([row["citation"] for row in vector_rows])
            rows_by_citation.update({row["citation"]: row for row in vector_rows})
        except Exception as exc:  # noqa: BLE001
            log.warning("vector search unavailable: %s", exc)
        fused = rrf(rankings, weights=[1.0, 0.1])
        ranked = []
        for citation, score in fused.items():
            row = rows_by_citation[citation]
            if row.get("current") is False:
                continue
            chunk = {"title": row.get("title", ""), "text": row.get("text", ""),
                     "section_key": row.get("section_key", ""), "current": True,
                     "doc": row.get("doc", ""),
                     "equipment": row.get("equipment") or [],
                     "manufacturer": row.get("manufacturer") or ""}
            ranked.append((score * metadata_weight(chunk, query, tags), citation, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            {"citation": citation, "score": round(score, 6), "doc": row.get("doc", ""),
             "title": row.get("title", ""), "current": bool(row.get("current", True)),
             "text": row.get("text", "")}
            for score, citation, row in ranked[:k]
        ]
