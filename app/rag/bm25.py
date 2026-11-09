"""BM25 baseline (same tokenisation family as the course baseline) and hybrid search."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

STOPWORDS = set(
    """a al algo como con cual cuales cuando de del el ella en es esta este esto hay la las le lo los mas me
    mi muy no o otra otras para pero por que se si sin sobre su sus un una uno y ya ante hace hacer tiene son fue ser
    puede qué cuál cuáles cómo cuánto cuántos dónde""".split()
)
OTHER_MODEL_RE = re.compile(r"tx-?250|tx-?500|fc-?24|fc-?96|pia-?1|pia-?2", re.IGNORECASE)


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return [token[:6] for token in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text) if token not in STOPWORDS]


class BM25:
    def __init__(self, fragments: list[dict], k1: float = 1.4, b: float = 0.75):
        self.ids = [fragment["id"] for fragment in fragments]
        self.docs = [Counter(tokens(f"{fragment.get('titulo', '')} {fragment['texto']}")) for fragment in fragments]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.average = sum(self.lengths) / len(self.lengths) if self.lengths else 1.0
        df = Counter(token for doc in self.docs for token in doc)
        n = len(self.docs)
        self.idf = {token: math.log(1 + (n - count + 0.5) / (count + 0.5)) for token, count in df.items()}
        self.k1, self.b = k1, b

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        q = tokens(query)
        scored: list[tuple[float, int]] = []
        for index, doc in enumerate(self.docs):
            score = 0.0
            for token in q:
                if token in doc:
                    tf = doc[token]
                    score += self.idf[token] * tf * (self.k1 + 1) / (
                        tf + self.k1 * (1 - self.b + self.b * self.lengths[index] / self.average)
                    )
            if score > 0:
                scored.append((score, index))
        scored.sort(reverse=True)
        return [(self.ids[index], score) for score, index in scored[:k]]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    numerator = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return numerator / (na * nb) if na and nb else 0.0


def rrf(lists: list[list[str]], k: int = 60, weights: list[float] | None = None) -> dict[str, float]:
    fused: dict[str, float] = {}
    for index, ranking in enumerate(lists):
        weight = weights[index] if weights else 1.0
        for rank, citation in enumerate(ranking):
            fused[citation] = fused.get(citation, 0.0) + weight / (k + rank + 1)
    return fused


def metadata_weight(chunk: dict, query: str, equipment_tags: set[str]) -> float:
    weight = 1.0
    current = chunk.get("current", chunk.get("vigente", True))
    if current is False:
        weight *= 0.6
    # Only the section title identifies "other models" sections; legitimate sections
    # often mention TX-250/TX-500 in passing and must not be penalised.
    heading = f"{chunk.get('title', '')} {chunk.get('section_key', '')}"
    if OTHER_MODEL_RE.search(heading):
        weight *= 0.55
    chunk_equipment = {str(tag).lower() for tag in (chunk.get("equipment") or [])}
    if chunk_equipment & {tag.lower() for tag in equipment_tags}:
        weight *= 1.2
    if equipment_tags and not (chunk_equipment & {tag.lower() for tag in equipment_tags}):
        if chunk.get("doc", "").startswith("historial"):
            weight *= 0.8
    return weight


@dataclass
class HybridIndex:
    fragments: list[dict]
    embedder: object | None = None
    _bm25: BM25 | None = None
    _vectors: list[list[float]] | None = None

    def __post_init__(self):
        self._bm25 = BM25(self.fragments)
        self.by_id = {fragment["id"]: fragment for fragment in self.fragments}

    def _ensure_vectors(self) -> bool:
        if self._vectors is not None:
            return True
        if self.embedder is None:
            return False
        try:
            texts = [f"{fragment.get('titulo', '')}\n{fragment['texto']}" for fragment in self.fragments]
            self._vectors = self.embedder.passages(texts)
            return True
        except Exception:  # noqa: BLE001
            self._vectors = None
            return False

    def search(self, query: str, k: int = 10, equipment_tags: set[str] | None = None) -> list[dict]:
        equipment_tags = equipment_tags or set()
        lexical = [citation for citation, _ in self._bm25.search(query, 30)]
        rankings = [lexical]
        if self._ensure_vectors():
            query_vector = self.embedder.query(query)
            scored = [(cosine(query_vector, vector), fragment["id"])
                      for vector, fragment in zip(self._vectors, self.fragments, strict=False)]
            scored.sort(reverse=True)
            rankings.append([citation for _, citation in scored[:30]])
        fused = rrf(rankings, weights=[1.0, 0.1])
        reranked = []
        for citation, score in fused.items():
            fragment = self.by_id[citation]
            chunk = {"title": fragment.get("titulo", ""), "text": fragment["texto"],
                     "section_key": fragment.get("clave", ""), "doc": fragment.get("doc", ""),
                     "current": fragment.get("vigente") is not False, "equipment": []}
            reranked.append((score * metadata_weight(chunk, query, equipment_tags), citation))
        reranked.sort(reverse=True)
        return [
            {
                "citation": citation,
                "score": round(score, 6),
                "doc": self.by_id[citation].get("doc", ""),
                "title": self.by_id[citation].get("titulo", ""),
                "current": self.by_id[citation].get("vigente") is not False,
                "text": self.by_id[citation]["texto"],
            }
            for score, citation in reranked[:k]
        ]

    def citations(self, query: str, k: int = 10) -> list[str]:
        return [hit["citation"] for hit in self.search(query, k)]
