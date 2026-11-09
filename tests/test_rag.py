from __future__ import annotations

from pathlib import Path

from app.rag.bm25 import BM25, HybridIndex, metadata_weight
from evaluacion.retrieval_eval import evaluate, load, old_before_new

ROOT = Path(__file__).resolve().parent.parent


def test_bm25_baseline_matches_documented_order_of_magnitude():
    suite, fragments = load()
    assert len(suite) == 71
    bm25 = BM25(fragments)
    result = evaluate(lambda query, k: [citation for citation, _ in bm25.search(query, k)], suite)
    assert result["total"]["hit@5"] >= 0.80
    assert result["total"]["recall@5"] >= 0.60


def test_hybrid_without_vectors_keeps_baseline_and_metadata_filters():
    suite, fragments = load()
    hybrid = HybridIndex(fragments, embedder=None)
    result = evaluate(hybrid.citations, suite)
    assert result["total"]["hit@5"] >= 0.80
    assert result["total"]["recall@5"] >= 0.60
    assert old_before_new(result["preguntas"]) <= 10


def test_metadata_prefers_current_revision():
    current = {"title": "Límites de operación", "text": "vibración 7,1 mm/s", "current": True,
               "doc": "TX350-D", "equipment": []}
    old = {"title": "Límites de operación", "text": "vibración 7,1 mm/s", "current": False,
           "doc": "TX350-C", "equipment": []}
    assert metadata_weight(current, "límite de vibración", set()) > metadata_weight(old, "límite de vibración", set())


def test_metadata_penalises_other_models():
    own = {"title": "Cambio de cartuchos", "text": "FC-48 cada 1,5 kg/cm2", "current": True, "doc": "FC48-3",
           "equipment": []}
    other = {"title": "Cambio de cartuchos TX-500", "text": "FC-96", "current": True, "doc": "FC48-3",
             "equipment": []}
    assert metadata_weight(own, "cambio de cartuchos", set()) > metadata_weight(other, "cambio de cartuchos", set())


def test_evaluate_metrics_on_synthetic_suite():
    suite = [{"id": "q1", "pregunta": "x", "tipo": "limites", "relevantes": ["A §1"], "distractores": ["B §1"]}]
    result = evaluate(lambda query, k: ["B §1", "A §1"], suite, ks=(1, 2))
    assert result["total"]["hit@1"] == 0.0
    assert result["total"]["hit@2"] == 1.0
    assert result["total"]["recall@2"] == 1.0
    assert result["preguntas"][0]["mrr"] == 0.5


def test_manufacturer_codes_translate_to_plant_catalogue():
    from app.rag.codes import translate_codes

    assert translate_codes("TX-T01 y FC-T02") == {"F01", "F08"}
    assert translate_codes("falla F09 por cavitación") == {"F09"}
    assert translate_codes("sin códigos") == set()


def test_part_evaluator_comparison():
    from evaluacion.evaluar_parte import close

    assert close(112, 112, "kg/cm2", "kg/cm2")
    assert close(1610, 1620, "psi", "psi")
    assert not close(112, 115, "kg/cm2", "kg/cm2")
    assert not close(112, 112, "psi", "kg/cm2")
    assert close(1620, 115.0, "psi", "kg/cm2")
