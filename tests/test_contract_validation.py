from __future__ import annotations

import pytest
from planta_contrato import EstadoSistema, EventoSistema, FilaParte, MensajeTablet, OrdenSistema
from pydantic import ValidationError

from app.domain.events import note_events
from app.domain.parser import parse_transcript
from app.publisher import Publisher
from app.tools.contracts import InventoryItem


def test_fila_parte_rejects_hora_and_photos():
    with pytest.raises(ValidationError):
        FilaParte(tag="B-101", variable="presion_descarga_local", valor=112, unidad="kg/cm2",
                  hora="2026-11-03T08:00:00-03:00")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        FilaParte(tag="B-101", variable="presion_descarga_local", valor=112, foto="/x.jpg")  # type: ignore[call-arg]


def test_tool_models_reject_extra():
    with pytest.raises(ValidationError):
        InventoryItem(codigo="X", nombre="Y", costo_usd=1, stock={}, color="rojo")  # type: ignore[call-arg]


def test_sample_contract_messages_are_valid(snapshot, ts):
    draft = parse_transcript("La uno está en ciento doce de descarga.", snapshot, note_id="N", ts=ts)
    event = note_events(draft, snapshot, ts)[0]
    EventoSistema.model_validate(event)
    MensajeTablet.model_validate({
        "id": "TAB-N-0", "ts": "2026-11-03T08:00:00-03:00", "nota_ids": ["N"],
        "texto": "Borrador", "pantalla": {"titulo": "Parte", "filas": [row.to_contract() for row in draft.rows]},
        "espera_respuesta": True, "audio_url": None,
    })
    OrdenSistema.model_validate({
        "id": "oid", "ts": "2026-11-03T08:00:00-03:00", "estado": "PendienteAprobacion", "equipo": "B-101",
        "evento_ids": ["e1"], "tareas": ["T-B-EMP"], "detiene_equipo": True, "reduce_inyeccion": False,
        "ejecutor": "propio", "repuestos": [{"codigo": "TX-EMP-KIT", "cantidad": 1}],
        "motivo": "reduce la inyección", "habilita": None, "monto_habilita_usd": None,
    })
    EstadoSistema.model_validate({"ts": "2026-11-03T08:00:00-03:00", "sistema": "Test", "enlace_ok": True,
                                 "pendientes_sincronizar": 0})


class FakeMqtt:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos=1):
        self.sent.append((topic, payload))


class FakeRepo:
    def __init__(self):
        self.items = []

    async def enqueue(self, topic, payload):
        self.items.append((topic, payload))


async def test_publisher_refuses_invalid_messages():
    mqtt, repo = FakeMqtt(), FakeRepo()
    publisher = Publisher(mqtt, repo)  # type: ignore[arg-type]
    assert await publisher.publish("sistema/eventos", {"id": "x"}) is False
    assert mqtt.sent == []
    valid = {"id": "x", "ts": "2026-11-03T08:00:00-03:00", "tipo": "SinNovedad", "equipo": None,
             "origen": "parte", "parte_id": "N", "nota_ids": ["N"], "resumen": "ok"}
    assert await publisher.publish("sistema/eventos", valid) is True
    assert mqtt.sent and repo.items
