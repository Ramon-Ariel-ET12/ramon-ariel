"""Local speech-to-text with faster-whisper.

The model is baked into the image; at runtime the plant has no internet.  Loading is
lazy so unit tests and tooling do not need the model.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DOMAIN_PROMPT = (
    "Parte de recorrida de una planta de inyeccion de agua. Bombas B-101, B-102, B-103. "
    "Filtros F-201A y F-201B. Presion de descarga, presion diferencial, gotas por minuto, "
    "empaquetadura, rodamiento, correas, pulmon, kilos, psi, bar."
)


@dataclass
class Transcription:
    text: str
    duration_s: float
    latency_ms: int
    model: str


class Transcriber:
    def __init__(self, model: str, threads: int = 4, beam_size: int = 5):
        self.model_name = model
        self.threads = threads
        self.beam_size = beam_size
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        started = time.perf_counter()
        local_only = Path(self.model_name).exists()
        self._model = WhisperModel(
            self.model_name,
            device="cpu",
            compute_type="int8",
            cpu_threads=self.threads,
            local_files_only=local_only,
        )
        log.info("asr model %s loaded in %.1fs", self.model_name, time.perf_counter() - started)

    def warmup(self) -> None:
        self.load()
        assert self._model is not None
        silent = Path("/tmp/pia-warmup.wav")
        if not silent.exists():
            import wave

            with wave.open(str(silent), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(b"\x00\x00" * 8000)
        self.transcribe(silent)

    def transcribe(self, path: Path | str, on_partial=None) -> Transcription:
        self.load()
        assert self._model is not None
        started = time.perf_counter()
        segments, info = self._model.transcribe(
            str(path),
            language="es",
            beam_size=self.beam_size,
            vad_filter=True,
            initial_prompt=DOMAIN_PROMPT,
            condition_on_previous_text=False,
        )
        # The generator yields each segment as it is decoded: handing the partial text to
        # the caller lets the safety detector fire before the whole audio is finished.
        parts: list[str] = []
        for segment in segments:
            cleaned = segment.text.strip()
            if not cleaned:
                continue
            parts.append(cleaned)
            if on_partial is not None:
                try:
                    on_partial(" ".join(parts))
                except Exception:  # noqa: BLE001
                    log.warning("partial transcript callback failed", exc_info=True)
        text = " ".join(parts).strip()
        latency = int((time.perf_counter() - started) * 1000)
        return Transcription(text=text, duration_s=float(getattr(info, "duration", 0.0)),
                             latency_ms=latency, model=self.model_name)
