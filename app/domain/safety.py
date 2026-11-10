"""Local unsafe-condition detector (S1..S4).

Runs on the transcript before any model or network call, so the emergency notice is
raised within the plant even when the link is down.  Negations are honoured: a report
of "goteo por la empaquetadura" is not a pressurised water leak.
"""

from __future__ import annotations

import re

from app.domain.numbers import normalize_text

S1 = "S1"
S2 = "S2"
S3 = "S3"
S4 = "S4"

_SAFETY_PATTERNS: dict[str, list[str]] = {
    S1: [
        r"agua (a )?presion",
        r"chorro de agua",
        r"proyeccion de agua",
        r"sale agua (a presion|para todos lados|con fuerza)",
        r"agua para todos lados",
        r"nube de agua",
        r"rompio (algo )?(en|la) (la )?descarga",
        r"fuga (de agua )?(a )?presion",
        r"revento (la|el) (descarga|niple|linea)",
        # A ruptured fitting is a pressurised-water projection even when the operator
        # does not add "sale agua a presion". An ASR may drop that half of the sentence.
        r"se (rompio|corto|salio|aflojo) (el|la|un) (niple|brida|caño|cano|linea|union|acople|codo)",
        r"(rompio|revento) (el|la) (niple|brida|caño|cano|union|codo)",
        r"pierde agua (a presion|para todos lados)",
    ],
    # The ASR usually glues "a gas" into "agas" ("olor agas"); the pattern accepts both.
    S2: [r"olor\s*(a\s*)?g[ae]s", r"huele\s*(a\s*)?gas\b", r"hay gas", r"fuga de gas",
         r"perdida de gas", r"escape de gas", r"detecto gas", r"se siente gas"],
    S3: [
        r"\bhumo\b",
        r"\bfuego\b",
        r"olor (a )?quemado",
        r"se (esta )?quemando",
        r"se incendia",
        r"se (prendio|prendió) fuego",
        r"prendido fuego",
        r"esta ardiendo",
        r"chispas?",
    ],
    S4: [
        r"persona lesionada",
        r"se golpeo",
        r"sangrando",
        r"esta sangrando",
        r"herido",
        r"herida",
        r"lesionado",
        r"se corto (la|el) mano",
        r"se lastimo",
        r"inconsciente",
        r"se desmayo",
        r"(el|un|mi) (compañero|companero|operador|tecnico) no responde",
    ],
}

_NEGATIONS = ("no hay", "no se ve", "no huele", "sin olor", "sin humo", "sin fuego", "no sale", "no tiene", "para nada")
_NEGATION_TAIL = re.compile(r"\b(sin|ni)\s+$")


def _plain(text: str) -> str:
    """Punctuation-insensitive text: the ASR writes "sale agua, presión" with stray commas."""
    normal = normalize_text(text)
    normal = re.sub(r"[.,;:!?¡¿\"'()\[\]]", " ", normal)
    return re.sub(r"\s+", " ", normal).strip()


def _negated(text: str, match: re.Match[str]) -> bool:
    window = text[max(0, match.start() - 28):match.start()]
    if any(negation in window for negation in _NEGATIONS):
        return True
    # "sin humo ni fuego": the negation is the single word in front of the match.
    return bool(_NEGATION_TAIL.search(window))


def detect_safety(transcript: str) -> tuple[str | None, str | None]:
    """Return (code, evidence) for the first unsafe condition, or (None, None)."""
    text = _plain(transcript)
    for code, patterns in _SAFETY_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                if not _negated(text, match):
                    return code, match.group(0)
    return None, None


def emergency_text(code: str, equipment: str | None) -> str:
    """Operator-facing message. The plant reads it aloud on the tablet."""
    equipo = f" en {equipment}" if equipment else ""
    return (
        f"CONDICION INSEGURA {code}{equipo}. Aplique el procedimiento de emergencia: "
        "alerte por radio al supervisor de turno, asegure la zona y no se acerque. "
        "La alerta de seguridad ya quedo registrada."
    )
