"""Index the plant corpus into pgvector with citable metadata."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from app.config import Settings
from app.integrations.plant_api import PlantClient
from app.persistence.repository import Repository

log = logging.getLogger(__name__)

EMBED_DIM = 384


def _metadata_by_doc(documents: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in documents.get("documentos", []):
        result[item["id"]] = {
            "manufacturer": item.get("emisor") or "",
            "equipment": item.get("equipos") or [],
        }
    return result


def _chunk(fragment: dict, meta: dict[str, dict]) -> dict:
    doc = fragment["doc"]
    info = meta.get(doc, {})
    vigente = fragment.get("vigente")
    return {
        "id": fragment["id"],
        "citation": fragment["id"],
        "doc": doc,
        "number": str(fragment.get("numero") or ""),
        "title": str(fragment.get("titulo") or ""),
        "section_key": str(fragment.get("clave") or ""),
        "page": fragment.get("pagina"),
        "current": True if vigente is None else bool(vigente),
        "manufacturer": str(info.get("manufacturer") or ""),
        "equipment": list(info.get("equipment") or []),
        "text": fragment["texto"],
        "content_hash": hashlib.sha1(fragment["texto"].encode("utf-8")).hexdigest()[:16],
    }


def _bundled_fragments(settings: Settings) -> list[dict]:
    path = Path(settings.evaluation_dir) / "fragmentos.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Embedder:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def passages(self, texts: list[str]) -> list[list[float]]:
        model = self.load()
        return [list(map(float, vector)) for vector in model.embed([f"passage: {text}" for text in texts])]

    def query(self, text: str) -> list[float]:
        model = self.load()
        return list(map(float, next(iter(model.embed([f"query: {text}"])))))


async def ensure_index(repo: Repository, plant: PlantClient, settings: Settings) -> int:
    count = await repo.rag_count()
    if count >= 701:
        return count
    try:
        fragments = await plant.fragments()
        documents = await plant.documents()
    except Exception as exc:  # noqa: BLE001
        log.warning("plant corpus unavailable, using bundled snapshot: %s", exc)
        fragments = _bundled_fragments(settings)
        documents = {"documentos": []}
    meta = _metadata_by_doc(documents)
    chunks = [_chunk(fragment, meta) for fragment in fragments]
    import asyncio

    embedder = Embedder(settings.embedding_model)
    texts = [f"{chunk['title']}\n{chunk['text']}" for chunk in chunks]
    embeddings = await asyncio.to_thread(embedder.passages, texts)
    await repo.rag_upsert(chunks, embeddings)
    return len(chunks)
