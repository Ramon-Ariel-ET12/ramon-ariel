"""Optional local language model for unusual free-text replies.

It never decides approval, never touches the safety path and never runs when disabled.
Its output is validated against a strict schema before use.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sos un intérprete de respuestas de operadores de planta.
Recibís lo que contestó un operador y el borrador que se le mostró.
Devolvés SOLO JSON con la forma {"acciones": [...]} usando estas acciones:
- {"action":"set","tag":"B-101","value":115.0,"unit":"kg/cm2"}
- {"action":"add","tag":"F-201A","value":1.5,"unit":"kg/cm2"}
- {"action":"remove","tag":"TK-301"}
- {"action":"move","from":"B-102","to":"B-101","value":112.0}
- {"action":"unit","tag":"F-201B","unit":"kg/cm2"}
No inventes valores ni equipos que no aparezcan en el texto. Si no entendés, devolvé {"acciones": []}."""


class LLMAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["set", "add", "remove", "move", "unit"]
    tag: str | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    value: float | None = None
    unit: str | None = None


class LLMReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acciones: list[LLMAction] = Field(default_factory=list)


class LocalLLM:
    def __init__(self, model_id: str, enabled: bool = False):
        self.model_id = model_id
        self.enabled = enabled
        self._pipeline = None
        self._tokenizer = None

    def load(self) -> bool:
        if not self.enabled:
            return False
        if self._pipeline is not None:
            return True
        try:
            from langchain_huggingface import HuggingFacePipeline
            from transformers import AutoTokenizer

            self._pipeline = HuggingFacePipeline.from_model_id(
                model_id=self.model_id,
                task="text-generation",
                pipeline_kwargs={"max_new_tokens": 220, "do_sample": False, "repetition_penalty": 1.05},
            )
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
            log.info("local llm %s loaded", self.model_id)
            return True
        except Exception:  # noqa: BLE001
            log.exception("local llm unavailable; deterministic reader remains active")
            self._pipeline = None
            return False

    def _run(self, prompt: str) -> tuple[str, int, int]:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        template = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", "{entrada}")])
        chain = template | self._pipeline | StrOutputParser()
        output = chain.invoke({"entrada": prompt})
        input_tokens = len(self._tokenizer.encode(prompt)) if self._tokenizer else 0
        output_tokens = len(self._tokenizer.encode(output)) if self._tokenizer else 0
        return output, input_tokens, output_tokens

    async def interpret_reply(self, text: str, rows: list[dict]) -> tuple[list[dict] | None, dict]:
        if not self.load():
            return None, {}
        prompt = f"Borrador: {json.dumps(rows, ensure_ascii=False)}\nRespuesta del operador: {text}"
        started = time.perf_counter()
        output, input_tokens, output_tokens = await asyncio.to_thread(self._run, prompt)
        latency = int((time.perf_counter() - started) * 1000)
        usage = {"model": self.model_id, "task": "reply", "input_tokens": input_tokens,
                 "output_tokens": output_tokens, "latency_ms": latency, "cost_usd": 0.0}
        try:
            start = output.find("{")
            end = output.rfind("}")
            parsed = LLMReply.model_validate(json.loads(output[start:end + 1]))
            actions = []
            for action in parsed.acciones:
                payload = action.model_dump(exclude_none=True)
                if "from_" in payload:
                    payload["from"] = payload.pop("from_")
                actions.append(payload)
            return actions, usage
        except Exception:  # noqa: BLE001
            log.warning("local llm returned unusable output: %s", output[:200])
            return None, usage
