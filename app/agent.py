"""LangChain core for the note pipeline.

The chain is deterministic by design: safety detection and extraction are ordinary
code.  An optional local language model is used only to read unusual free-text replies.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.runnables import RunnableLambda, RunnableParallel

from app.domain.models import PartDraft, PlantSnapshot
from app.domain.parser import parse_transcript
from app.domain.safety import detect_safety
from app.processing.replies import ReplyReading, read_reply


@dataclass
class AgentInput:
    transcript: str
    note_id: str
    ts: object
    photos: list[str]


class NoteAgent:
    def __init__(self, snapshot: PlantSnapshot):
        self.snapshot = snapshot
        self.chain = RunnableParallel(
            safety=RunnableLambda(self._safety),
            draft=RunnableLambda(self._extract),
        )

    def _safety(self, data: AgentInput) -> str | None:
        code, _ = detect_safety(data.transcript)
        return code

    def _extract(self, data: AgentInput) -> PartDraft:
        return parse_transcript(data.transcript, self.snapshot, note_id=data.note_id,
                                ts=data.ts, photos=data.photos)  # type: ignore[arg-type]

    def analyze(self, transcript: str, note_id: str, ts, photos: list[str]) -> tuple[PartDraft, str | None]:
        result = self.chain.invoke(AgentInput(transcript, note_id, ts, list(photos or [])))
        return result["draft"], result["safety"]

    def read_reply(self, text: str, kind: str) -> ReplyReading:
        return read_reply(text, self.snapshot, kind)
