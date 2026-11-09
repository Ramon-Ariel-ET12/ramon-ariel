"""Benchmark the local ASR against scripted notes.

    python scripts/benchmark_asr.py --dir academia2026-tp/datos/voces

The directory must contain ``indice.json`` and the FLAC files described there.
Reports WER overall and per scenario, plus latency.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.findall(r"[a-z0-9]+", text)


def wer(reference: list[str], hypothesis: list[str]) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, start=1):
        current = [i]
        for j, hyp in enumerate(hypothesis, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref != hyp)))
        previous = current
    return previous[-1] / len(reference)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--model", default="var/models/faster-whisper-small")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--limite", type=int, default=0)
    args = parser.parse_args()

    from faster_whisper import WhisperModel

    index = json.loads((args.dir / "indice.json").read_text(encoding="utf-8"))
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=args.threads,
                         local_files_only=True)
    by_scenario: dict[str, list[float]] = {}
    latencies: list[float] = []
    items = list(index.items())
    if args.limite:
        items = items[: args.limite]
    for key, entry in items:
        audio = args.dir / f"{key}.flac"
        if not audio.exists():
            continue
        started = time.perf_counter()
        segments, _info = model.transcribe(str(audio), language="es", beam_size=5, vad_filter=True,
                                           condition_on_previous_text=False)
        hypothesis = " ".join(segment.text for segment in segments)
        latencies.append(time.perf_counter() - started)
        score = wer(normalize(entry["texto"]), normalize(hypothesis))
        by_scenario.setdefault(entry["escenario"], []).append(score)
    total = [score for scores in by_scenario.values() for score in scores]
    print(f"Notas: {len(total)} · WER medio: {sum(total) / len(total):.3f}")
    print(f"Latencia media: {sum(latencies) / len(latencies):.2f} s · máxima: {max(latencies):.2f} s")
    for scenario, scores in sorted(by_scenario.items()):
        print(f"  {scenario:20} n={len(scores):2} WER={sum(scores) / len(scores):.3f}")


if __name__ == "__main__":
    main()
