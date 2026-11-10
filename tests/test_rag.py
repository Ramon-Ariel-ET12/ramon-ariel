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


def test_other_model_penalty_does_not_hide_a_section_the_question_names():
    """Ask about PIA-1 and its own section must rank first, not be demoted as a distractor."""
    pia = {"id": "MBP-4 §17.1", "doc": "MBP-4", "titulo": "PIA-1: bombas centrífugas multietapa",
           "clave": "equipos", "vigente": True,
           "texto": "PIA-1: bombas centrífugas multietapa. Presión de succión y descarga."}
    generic = {"id": "MBP-4 §1.1", "doc": "MBP-4", "titulo": "Alcance", "clave": "alcance",
               "vigente": True, "texto": "Bombas centrífugas multietapa presión general"}
    index = HybridIndex([pia, generic], embedder=None)
    assert index.citations("PIA-1 bombas centrífugas multietapa presión", 1) == ["MBP-4 §17.1"]


def test_manufacturer_codes_are_expanded_in_the_lexical_query():
    from app.rag.bm25 import expand_query

    assert "F01" in expand_query("¿Qué significa TX-T01?").split()
    assert expand_query("límite de vibración") == "límite de vibración"


def test_order_history_chunks_get_equipment_and_manufacturer_metadata():
    from app.rag.indexer import _chunk, _metadata_by_doc

    documents = {"documentos": [
        {"id": "TX350-D", "emisor": "Trimax Industrial S.A.", "equipos": ["B-101", "B-102", "B-103"]},
    ]}
    # The order history is attributed to the equipment's maker (GET /api/planta), not to
    # whichever manual lists the equipment.
    meta = _metadata_by_doc(documents, {"B-101": "Trimax Industrial", "B-102": "Trimax Industrial"})
    fragment = {"id": "historial OT-24-0001", "doc": "historial", "numero": "OT-24-0001",
                "titulo": "OT-24-0001 B-101 T-B-VAL", "clave": None, "pagina": None, "vigente": True,
                "texto": "OT-24-0001 · 2024-10-03 · B-101 · T-B-VAL · propio"}
    chunk = _chunk(fragment, meta)
    assert chunk["equipment"] == ["B-101"]
    assert chunk["manufacturer"] == "Trimax Industrial"
    assert chunk["section_key"] == "OT"


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


def test_the_course_evaluator_agrees_with_the_local_copy():
    """The required call is corpus.evaluar.evaluar(buscar, suite); when the plant repo is
    present the two evaluators must produce the same metrics."""
    from evaluacion.retrieval_eval import official_evaluator

    oficial = official_evaluator()
    if oficial is None:
        import pytest

        pytest.skip("plant repository not available (set PLANTA_REPO_DIR)")
    suite, fragments = load()
    hybrid = HybridIndex(fragments, embedder=None)
    ours = evaluate(hybrid.citations, suite)
    theirs = oficial(hybrid.citations, suite)
    for metric in ("hit@1", "hit@5", "recall@5", "mrr"):
        assert abs(ours["total"][metric] - theirs["total"][metric]) <= 0.002
