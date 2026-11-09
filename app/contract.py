"""Wire contract models, re-exported from the provided package.

The models are installed with pip from ``planta_contrato``; they are never copied into
this repository.
"""

from __future__ import annotations

from typing import Any

try:
    from planta_contrato import (  # noqa: F401
        Calidad,
        EstadoEnergia,
        EstadoOrden,
        EstadoSistema,
        EventoSistema,
        FilaParte,
        LecturaSensor,
        MensajeTablet,
        NotaCierre,
        NotaRecorrida,
        OrdenSistema,
        Pantalla,
        Repuesto,
        RespuestaOperador,
        TipoEvento,
        Topicos,
    )
except ImportError as exc:  # pragma: no cover - installation problem
    raise RuntimeError(
        "planta_contrato is not installed. Install the provided package with pip "
        "(see README: PLANTA_CONTRATO_DIR or the documented git source)."
    ) from exc

from pydantic import ValidationError

TOPIC_MODELS: dict[str, type] = {
    "sistema/eventos": EventoSistema,
    "sistema/ordenes": OrdenSistema,
    "sistema/estado": EstadoSistema,
    "sistema/tablet": MensajeTablet,
}

PLANT_MODELS: dict[str, type] = {
    "planta/recorridas": NotaRecorrida,
    "planta/respuestas": RespuestaOperador,
    "planta/cierres": NotaCierre,
    "planta/energia": EstadoEnergia,
}


def validate_message(topic: str, payload: dict) -> tuple[bool, str | None]:
    model = TOPIC_MODELS.get(topic)
    if model is None:
        return False, f"tópico desconocido: {topic}"
    try:
        model.model_validate(payload)
        return True, None
    except ValidationError as exc:
        return False, exc.errors(include_url=False).__repr__()


def validate_plant_message(topic: str, payload: dict) -> tuple[bool, str | None]:
    if topic.startswith("planta/sensores/"):
        model = LecturaSensor
    else:
        model = PLANT_MODELS.get(topic)
    if model is None:
        return True, None
    try:
        model.model_validate(payload)
        return True, None
    except ValidationError as exc:
        return False, exc.errors(include_url=False).__repr__()


def dump(model: Any) -> dict:
    return model.model_dump(mode="json")
