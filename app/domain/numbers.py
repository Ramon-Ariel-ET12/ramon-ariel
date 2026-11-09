"""Deterministic Spanish number understanding.

Field operators dictate numbers as words ("ciento doce", "mil seiscientos veinte",
"uno con cuatro", "cero nueve").  This module is intentionally rule based: the same
text always produces the same number.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

UNITS = {
    "cero": 0, "uno": 1, "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
}
TEENS = {
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintiun": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintisiete": 27,
    "veintiocho": 28, "veintinueve": 29,
}
TENS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}
HUNDREDS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200,
    "trescientos": 300, "trescientas": 300, "cuatrocientos": 400, "cuatrocientas": 400,
    "quinientos": 500, "quinientas": 500, "seiscientos": 600, "seiscientas": 600,
    "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
    "novecientos": 900, "novecientas": 900,
}
NUMBER_WORDS = set(UNITS) | set(TEENS) | set(TENS) | set(HUNDREDS) | {"mil", "millon", "millones"}
CARDINALS = set(UNITS) | set(TEENS) | set(TENS) | set(HUNDREDS)

# ATX: tokens are lowercase words or numbers with an optional decimal part.
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?|[.;:,!?¡¿]")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    text = strip_accents((text or "").lower())
    text = text.replace("º", " ").replace("°", " ")
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize_text(text))


def _numeric_token(token: str) -> tuple[float, bool] | None:
    """Return (value, explicit_decimal) for a numeric token such as 112, 1.4 or 1.620."""
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", token):
        return None
    if re.fullmatch(r"\d+[.,]\d{3}", token):
        return float(token.replace(".", "").replace(",", "")), False
    if re.fullmatch(r"\d+[.,]\d+", token):
        return float(token.replace(",", ".")), True
    # ASR collapses "cero nueve" into "09": a leading zero is a spoken decimal.
    if re.fullmatch(r"0\d", token):
        return int(token) / 10.0, True
    return float(token), False


def _next_significant(tokens: list[str], i: int) -> tuple[int, str] | tuple[None, None]:
    return (i, tokens[i]) if i < len(tokens) else (None, None)


def _compound_number(tokens: list[str], i: int) -> tuple[float, int, bool] | None:
    """Parse a composed cardinal starting at ``tokens[i]``.

    Returns (value, next_index, explicit_decimal).  Composition only advances through
    a valid Spanish order, so "uno tres" is two numbers and then handled as a decimal.
    """
    if i >= len(tokens):
        return None
    first = tokens[i]
    if first == "medio":
        return 0.5, i + 1, False
    if first == "cero":
        return 0.0, i + 1, False
    if first not in NUMBER_WORDS:
        return None
    if first not in CARDINALS and first not in {"mil", "millon", "millones"}:
        return None

    total = 0.0
    current = 0.0
    consumed = False
    explicit = False
    j = i
    while j < len(tokens):
        token = tokens[j]
        if token == "y":
            nxt = tokens[j + 1] if j + 1 < len(tokens) else ""
            if nxt in UNITS and current and current % 10 == 0 and current < 100:
                j += 1
                continue
            break
        if token in ("mil", "millon", "millones"):
            current = (current or 1.0) * (1000.0 if token == "mil" else 1_000_000.0)
            total += current
            current = 0.0
            consumed = True
            j += 1
            continue
        if token in HUNDREDS:
            if current and current >= 100:
                break
            current += HUNDREDS[token]
            consumed = True
            j += 1
            continue
        if token in TENS:
            if current % 100 >= 10:
                break
            current += TENS[token]
            consumed = True
            j += 1
            continue
        if token in TEENS:
            if current % 100 >= 10:
                break
            current += TEENS[token]
            consumed = True
            j += 1
            continue
        if token in UNITS:
            if current % 10 != 0:
                break
            current += UNITS[token]
            consumed = True
            j += 1
            continue
        break

    if not consumed:
        return None
    return total + current, j, explicit


@dataclass(frozen=True)
class NumberMention:
    value: float
    start: int
    end: int
    explicit_decimal: bool = False
    text: str = ""

    @property
    def is_integer(self) -> bool:
        return float(self.value).is_integer()


def parse_numbers(tokens: list[str]) -> list[NumberMention]:
    """Extract every number mentioned in a token list, preserving order.

    Handles spoken decimals ("uno con cuatro", "uno coma tres", "cero nueve",
    "uno y medio") and numeric tokens ("1.4", "1.620").
    """
    mentions: list[NumberMention] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # "medió 59 grados" is a verb, not "medio" (0.5); the same for "mide".
        if token in ("medio", "media", "mide", "midio") and i + 1 < len(tokens):
            following = _numeric_token(tokens[i + 1]) or _compound_number(tokens, i + 1)
            if following is not None:
                i += 1
                continue
        numeric = _numeric_token(token)
        if numeric is not None:
            value, explicit = numeric
            mentions.append(NumberMention(value, i, i + 1, explicit, token))
            i += 1
            continue

        parsed = _compound_number(tokens, i)
        if parsed is None:
            i += 1
            continue

        value, end, explicit = parsed
        # "X con Y" / "X coma Y" / "X punto Y" -> one decimal digit.
        if end < len(tokens) and tokens[end] in ("con", "coma", "punto", "puntoycoma"):
            nxt = _numeric_token(tokens[end + 1]) if end + 1 < len(tokens) else None
            compound = _compound_number(tokens, end + 1) if end + 1 < len(tokens) else None
            if nxt is not None and 0 <= nxt[0] <= 9 and not nxt[1]:
                value = value + nxt[0] / 10.0
                explicit = True
                end += 2
            elif compound is not None and 0 <= compound[0] <= 9:
                value = value + compound[0] / 10.0
                explicit = True
                end = compound[1]
        # "X y medio" -> X.5
        if end + 1 < len(tokens) and tokens[end] == "y" and tokens[end + 1] == "medio":
            value = value + 0.5
            explicit = True
            end += 2
        # "cero nueve" / "uno tres": two adjacent single digits mean a decimal.
        if not explicit and 0 <= value <= 9 and end < len(tokens):
            nxt_word = tokens[end]
            if nxt_word not in ("y", "con", "coma", "punto"):
                nxt = _numeric_token(nxt_word)
                compound = _compound_number(tokens, end)
                if nxt is not None and 0 <= nxt[0] <= 9 and not nxt[1]:
                    value = value + nxt[0] / 10.0
                    explicit = True
                    end += 1
                elif compound is not None and 0 <= compound[0] <= 9 and compound[1] == end + 1:
                    value = value + compound[0] / 10.0
                    explicit = True
                    end = compound[1]

        mentions.append(NumberMention(value, i, end, explicit, " ".join(tokens[i:end])))
        i = end
    return mentions


def parse_first_number(text: str) -> float | None:
    mentions = parse_numbers(tokenize(text))
    return mentions[0].value if mentions else None
