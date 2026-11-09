"""Tune the hybrid fusion on the provided suite (development tool)."""

from __future__ import annotations

import json
from pathlib import Path

from app.rag.bm25 import BM25, cosine, rrf

HERE = Path("/app/evaluacion") if Path("/app/evaluacion").exists() else Path(__file__).resolve().parent.parent / "evaluacion"


def load():
    suite = json.loads((HERE / "retrieval.json").read_text(encoding="utf-8"))
    fragments = [json.loads(line) for line in (HERE / "fragmentos.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    return suite, fragments


def evaluate(buscar, suite, ks=(1, 3, 5, 10)):
    rows = []
    for question in suite:
        result = buscar(question["pregunta"], 20)
        relevant, distractors = set(question["relevantes"]), set(question.get("distractores", []))
        pos_rel = next((i for i, c in enumerate(result) if c in relevant), None)
        row = {"id": question["id"], "mrr": 1 / (pos_rel + 1) if pos_rel is not None else 0.0,
               "relevantes": sorted(relevant), "top": result[:5]}
        for k in ks:
            top = result[:k]
            row[f"hit@{k}"] = float(any(c in relevant for c in top))
            row[f"recall@{k}"] = len(relevant & set(top)) / len(relevant)
            pos_dis = next((i for i, c in enumerate(top) if c in distractors), None)
            row[f"distractor@{k}"] = float(pos_dis is not None and (pos_rel is None or pos_dis < pos_rel))
        rows.append(row)
    total = {m: round(sum(r[m] for r in rows) / len(rows), 3) for m in rows[0] if "@" in m or m == "mrr"}
    return total, rows


def rev_c(rows, ks=5):
    count = 0
    for row in rows:
        relevant = set(row["relevantes"])
        if not any(c.startswith("TX350-D") for c in relevant):
            continue
        top = row["top"][:ks]
        pos_rel = next((i for i, c in enumerate(top) if c in relevant), None)
        pos_c = next((i for i, c in enumerate(top) if c.startswith("TX350-C")), None)
        if pos_c is not None and (pos_rel is None or pos_c < pos_rel):
            count += 1
    return count


def main():
    suite, fragments = load()
    bm25 = BM25(fragments)
    by_id = {f["id"]: f for f in fragments}
    from app.rag.indexer import Embedder

    embedder = Embedder("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    texts = [f"{f.get('titulo', '')}\n{f['texto']}" for f in fragments]
    vectors = embedder.passages(texts)
    base_total, base_rows = evaluate(lambda q, k: [c for c, _ in bm25.search(q, k)], suite)
    print("BM25", base_total, "revC", rev_c(base_rows))

    def make(vector_weight, current_penalty, other_penalty, title_only):
        def search(query, k):
            lex = [c for c, _ in bm25.search(query, 30)]
            qv = embedder.query(query)
            scored = sorted(((cosine(qv, v), f) for v, f in zip(vectors, fragments, strict=False)),
                            key=lambda item: item[0], reverse=True)
            vec = [f["id"] for _, f in scored[:30]]
            fused = rrf([lex, vec], weights=[1.0, vector_weight])
            ranked = []
            for citation, score in fused.items():
                fragment = by_id[citation]
                title = f"{fragment.get('titulo', '')} {fragment.get('clave', '')}".lower()
                body = fragment["texto"].lower()
                weight = 1.0
                if fragment.get("vigente") is False:
                    weight *= current_penalty
                import re
                other = re.compile(r"tx-?250|tx-?500|fc-?24|fc-?96|pia-?1|pia-?2")
                if other.search(title if title_only else title + " " + body):
                    weight *= other_penalty
                ranked.append((score * weight, citation))
            ranked.sort(reverse=True)
            return [c for _, c in ranked[:k]]
        return search

    for vw in (0.05, 0.1, 0.2, 0.25):
        for cp in (0.6,):
            for op in (0.55,):
                total, rows = evaluate(make(vw, cp, op, True), suite)
                print(f"vw={vw} cp={cp} op={op} title_only -> hit@5={total['hit@5']} recall@5={total['recall@5']} "
                      f"mrr={total['mrr']} revC={rev_c(rows)} dist@5={total['distractor@5']}")


if __name__ == "__main__":
    main()
