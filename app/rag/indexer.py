"""Index the plant corpus into pgvector with citable metadata."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from app.config import Settings
from app.integrations.plant_api import PlantClient
from app.persistence.repository import Repository

log = logging.getLogger(__name__)

EMBED_DIM = 384
DEFAULT_TAG_RE = re.compile(r"\b([BF]-\d{3}[AB]?|TK-\d{3}|FT-\d{3})\b", re.IGNORECASE)


def _metadata_by_doc(documents: dict) -> dict:
    """Document metadata plus the equipment → manufacturer map used for order histories."""
    docs: dict[str, dict] = {}
    makers: dict[str, str] = {}
    for item in documents.get("documentos", []):
        info = {"manufacturer": item.get("emisor") or "", "equipment": item.get("equipos") or []}
        docs[item["id"]] = info
        for tag in info["equipment"]:
            if tag and info["manufacturer"]:
                makers[str(tag).upper()] = info["manufacturer"]
    known = sorted({tag for info in docs.values() for tag in info["equipment"]} | set(makers))
    tag_re = (re.compile(r"\b(" + "|".join(re.escape(tag) for tag in known) + r")\b", re.IGNORECASE)
              if known else DEFAULT_TAG_RE)
    return {"docs": docs, "makers": makers, "tag_re": tag_re}


def _chunk(fragment: dict, meta: dict) -> dict:
    doc = fragment["doc"]
    info = meta["docs"].get(doc, {})
    vigente = fragment.get("vigente")
    equipment = [str(tag).upper() for tag in (info.get("equipment") or [])]
    if not equipment:
        # Order histories carry the TAG in their title ("OT-24-0001 B-101 T-B-VAL") but
        # the plant's document metadata has no equipment list for the collection.
        heading = f"{fragment.get('titulo') or ''} {fragment.get('numero') or ''}"
        equipment = sorted({match.group(1).upper() for match in meta["tag_re"].finditer(heading)})
    manufacturer = str(info.get("manufacturer") or "")
    if not manufacturer:
        manufacturer = next((meta["makers"][tag] for tag in equipment if tag in meta["makers"]), "")
    section = str(fragment.get("clave") or "")
    if not section and doc == "historial":
        section = "OT"
    return {
        "id": fragment["id"],
        "citation": fragment["id"],
        "doc": doc,
        "number": str(fragment.get("numero") or ""),
        "title": str(fragment.get("titulo") or ""),
        "section_key": section,
        "page": fragment.get("pagina"),
        "current": True if vigente is None else bool(vigente),
        "manufacturer": manufacturer,
        "equipment": equipment,
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
    try:
        fragments = await plant.fragments()
        documents = await plant.documents()
    except Exception as exc:  # noqa: BLE001
        log.warning("plant corpus unavailable, using bundled snapshot: %s", exc)
        fragments = _bundled_fragments(settings)
        documents = {"documentos": []}
    meta = _metadata_by_doc(documents)
    chunks = [_chunk(fragment, meta) for fragment in fragments]
    if count >= len(chunks):
        # Text and embeddings are already there. Refresh the metadata a newer indexer
        # can derive (equipment/manufacturer for order histories) without re-embedding.
        await repo.rag_refresh_metadata(chunks)
        return count
    import asyncio

    embedder = Embedder(settings.embedding_model)
    texts = [f"{chunk['title']}\n{chunk['text']}" for chunk in chunks]
    embeddings = await asyncio.to_thread(embedder.passages, texts)
    await repo.rag_upsert(chunks, embeddings)
    return len(chunks)
