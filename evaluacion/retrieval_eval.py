"""Recall@k evaluation of the manual retriever against the provided suite."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from app.rag.bm25 import BM25, HybridIndex
from app.rag.indexer import Embedder

HERE = Path(__file__).resolve().parent


def load() -> tuple[list[dict], list[dict]]:
    suite = json.loads((HERE / "retrieval.json").read_text(encoding="utf-8"))
    fragments = [json.loads(line) for line in (HERE / "fragmentos.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    return suite, fragments


def evaluate(buscar: Callable[[str, int], list[str]], suite: list[dict], ks=(1, 3, 5, 10)) -> dict:
    kmax = max(max(ks), 20)
    rows = []
    for question in suite:
        result = buscar(question["pregunta"], kmax)
        relevant = set(question["relevantes"])
        distractors = set(question.get("distractores", []))
        pos_rel = next((index for index, citation in enumerate(result) if citation in relevant), None)
        row = {"id": question["id"], "tipo": question["tipo"], "relevantes": sorted(relevant),
               "mrr": 1 / (pos_rel + 1) if pos_rel is not None else 0.0, "top": result[:5]}
        for k in ks:
            top = result[:k]
            row[f"hit@{k}"] = float(any(citation in relevant for citation in top))
            row[f"recall@{k}"] = len(relevant & set(top)) / len(relevant) if relevant else 0.0
            pos_dis = next((index for index, citation in enumerate(top) if citation in distractors), None)
            row[f"distractor@{k}"] = float(pos_dis is not None and (pos_rel is None or pos_dis < pos_rel))
        rows.append(row)
    metrics = [name for name in rows[0] if "@" in name or name == "mrr"] if rows else []
    total = {metric: round(sum(row[metric] for row in rows) / len(rows), 3) for metric in metrics}
    by_type: dict[str, dict] = {}
    for kind in sorted({row["tipo"] for row in rows}):
        subset = [row for row in rows if row["tipo"] == kind]
        by_type[kind] = {"n": len(subset), **{metric: round(sum(row[metric] for row in subset) / len(subset), 3)
                                              for metric in metrics if metric.startswith(("recall@", "hit@"))}}
    return {"n": len(rows), "total": total, "por_tipo": by_type, "preguntas": rows}


def old_before_new(rows: list[dict], ks: int = 5) -> int:
    """Version traps: a listed distractor (e.g. superseded TX350-C) ranks above every relevant section.

    This is the same definition as the course's ``distractor@k`` metric, so the number is
    comparable with the documented baseline ("one in ten questions").
    """
    return sum(1 for row in rows if row.get(f"distractor@{ks}"))


def official_evaluator():
    """The course's evaluator, ``corpus.evaluar.evaluar``, when the plant repo is available.

    The assignment asks for that exact call. The plant repository is not part of this
    submission, so the path is resolved from ``PLANTA_REPO_DIR`` or the two usual
    sibling locations; when it is missing the local ``evaluate`` (same methodology,
    verified against it) is used and the report says so.
    """
    import os
    import sys

    bases: list[Path] = []
    if os.environ.get("PLANTA_REPO_DIR"):
        bases.append(Path(os.environ["PLANTA_REPO_DIR"]))
    bases += [HERE.parent / "academia2026-tp", HERE.parent.parent / "academia2026-tp"]
    for base in bases:
        planta = base / "planta"
        if (planta / "corpus" / "evaluar.py").exists():
            if str(planta) not in sys.path:
                sys.path.insert(0, str(planta))
            from corpus.evaluar import evaluar as oficial

            return oficial
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5, 10])
    parser.add_argument("--model", default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    parser.add_argument("--sin-vectores", action="store_true", help="solo BM25 + metadatos")
    parser.add_argument("--salida", type=Path, default=HERE / "informe_retrieval.json")
    parser.add_argument("--verificar", action="store_true",
                        help="exit non-zero when the hybrid is below the documented BM25 baseline")
    args = parser.parse_args()

    suite, fragments = load()
    baseline = BM25(fragments)
    base_eval = evaluate(lambda query, k: [citation for citation, _ in baseline.search(query, k)], suite, args.k)
    embedder = None if args.sin_vectores else Embedder(args.model)
    hybrid = HybridIndex(fragments, embedder)
    hybrid_eval = evaluate(hybrid.citations, suite, args.k)

    # The required call: corpus.evaluar.evaluar(buscar, suite).
    oficial = official_evaluator()
    oficial_eval = oficial(hybrid.citations, suite, args.k) if oficial else None
    if oficial_eval is not None:
        # Hard guard: the two evaluators must agree, otherwise one of them is wrong.
        for metric in ("hit@5", "recall@5", "mrr"):
            left = round(hybrid_eval["total"][metric], 3)
            right = round(oficial_eval["total"][metric], 3)
            assert abs(left - right) <= 0.002, f"{metric}: local={left} oficial={right}"

    report = {
        "n_preguntas": len(suite),
        "evaluador": ("corpus.evaluar.evaluar" if oficial_eval is not None
                      else "evaluacion.retrieval_eval.evaluate (copia local; corpus.evaluar no disponible)"),
        "baseline_bm25": {"total": base_eval["total"], "rev_c_antes_que_d": old_before_new(base_eval["preguntas"])},
        "hibrido": {"total": hybrid_eval["total"], "por_tipo": hybrid_eval["por_tipo"],
                    "rev_c_antes_que_d": old_before_new(hybrid_eval["preguntas"])},
        "referencia_bm25_curso": {"hit@5": 0.85, "recall@5": 0.66, "rev_c_antes_que_d": "1 de cada 10"},
        "preguntas": [{"id": row["id"], "top": row["top"]} for row in hybrid_eval["preguntas"]],
    }
    if oficial_eval is not None:
        report["hibrido"]["total_corpus_evaluar"] = oficial_eval["total"]
    args.salida.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Preguntas: {report['n_preguntas']} · evaluador: {report['evaluador']}")
    print("BM25 base:", json.dumps(report["baseline_bm25"]["total"], ensure_ascii=False))
    print("Hibrido:  ", json.dumps(report["hibrido"]["total"], ensure_ascii=False))
    if oficial_eval is not None:
        print("corpus.evaluar.evaluar:", json.dumps(oficial_eval["total"], ensure_ascii=False))
    print("Rev. C antes que D -> base:", report["baseline_bm25"]["rev_c_antes_que_d"],
          "| hibrido:", report["hibrido"]["rev_c_antes_que_d"])
    for kind, metrics in report["hibrido"]["por_tipo"].items():
        print(f"  {kind:14} n={metrics['n']:2}  " + "  ".join(f"{k}={v}" for k, v in metrics.items() if k != "n"))
    print(f"Informe: {args.salida}")

    if args.verificar:
        total = report["hibrido"]["total"]
        fallas = []
        if total["hit@5"] < 0.85:
            fallas.append(f"hit@5 {total['hit@5']} < 0.85")
        if total["recall@5"] < 0.66:
            fallas.append(f"recall@5 {total['recall@5']} < 0.66")
        if report["hibrido"]["rev_c_antes_que_d"] != 0:
            fallas.append(f"Rev. C antes que D en {report['hibrido']['rev_c_antes_que_d']} preguntas")
        if fallas:
            print("FALLA la verificación de recuperación:", "; ".join(fallas))
            raise SystemExit(1)
        print("OK: recuperación por encima de la línea de base BM25 y sin trampas de versión")


if __name__ == "__main__":
    main()
