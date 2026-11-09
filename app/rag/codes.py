"""Manufacturer fault codes translated to the plant catalogue (MBP-4 §6)."""

from __future__ import annotations

import re

MANUFACTURER_TO_INTERNAL = {
    "TX-T01": "F01",
    "TX-T02": "F02",
    "TX-T03": "F03",
    "TX-T04": "F04",
    "TX-T05": "F05",
    "TX-T06": "F06",
    "TX-T07": "F09",
    "TX-T08": "F10",
    "FC-T01": "F07",
    "FC-T02": "F08",
    "FC-T04": "F10",
}
INTERNAL_TO_MANUFACTURER = {
    "F01": ["TX-T01"], "F02": ["TX-T02"], "F03": ["TX-T03"], "F04": ["TX-T04"], "F05": ["TX-T05"],
    "F06": ["TX-T06"], "F07": ["FC-T01"], "F08": ["FC-T02"], "F09": ["TX-T07"], "F10": ["TX-T08", "FC-T04"],
}
CODE_RE = re.compile(r"\b((?:TX|FC)-T\d{2})\b", re.IGNORECASE)


def translate_codes(text: str) -> set[str]:
    """Return the internal F-codes mentioned in a text, directly or through a manufacturer code."""
    found: set[str] = set()
    for match in CODE_RE.finditer(text or ""):
        internal = MANUFACTURER_TO_INTERNAL.get(match.group(1).upper())
        if internal:
            found.add(internal)
    for match in re.finditer(r"\bF(\d{2})\b", text or ""):
        found.add(f"F{match.group(1)}")
    return found
