"""Plant equipment resolution.

Aliases come from the plant API (``GET /api/planta`` -> ``equipos[].nombres``), which is
the authoritative list.  The resolved tag is always one of the plant TAGs; when the
operator says "la bomba" without a qualifier the caller must ask.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import Equipment, PlantSnapshot
from app.domain.numbers import normalize_text

# Max tokens in an alias such as "el de la izquierda".
MAX_ALIAS_TOKENS = 6
TAG_RE = re.compile(r"\b([a-z])-(\d{3}[a-z]?)\b")


def preprocess(text: str) -> str:
    """Make tags tokenisable and normalise the text."""
    lowered = normalize_text(text)
    lowered = TAG_RE.sub(r"\1\2", lowered)
    lowered = re.sub(r"\bdel\b", "de el", lowered)
    lowered = re.sub(r"\bal\b", "a el", lowered)
    return lowered


def _alias_variants(equipment: Equipment) -> set[str]:
    variants = {equipment.tag.lower(), equipment.tag.replace("-", "").lower()}
    for name in equipment.names:
        variants.add(normalize_text(name))
    # The ASR confuses "la" with "a" and "filtro" with "fito"/"frito" in plant noise.
    # These are still the plant's equipment names to the operator.
    if equipment.kind == "bomba":
        number = {"B-101": "uno", "B-102": "dos", "B-103": "tres"}.get(equipment.tag)
        if number:
            variants.add(f"a {number}")
    if equipment.kind == "filtro":
        letter = "a" if equipment.tag.upper().endswith("A") else "b"
        for word in ("fito", "frito"):
            variants.add(f"{word} {letter}")
            variants.add(f"el {word} {letter}")
    # The plant list spells "bomba uno"; operators also say "bomba 1".
    for name in list(variants):
        parts = name.split()
        if len(parts) == 2 and parts[0] in ("bomba", "la", "el"):
            variants.add(f"{parts[0]} {parts[1]}")
    return {v for v in variants if v}


@dataclass(frozen=True)
class Mention:
    tag: str
    start: int
    end: int
    alias: str


class EquipmentIndex:
    def __init__(self, snapshot: PlantSnapshot):
        self.snapshot = snapshot
        self.aliases: dict[tuple[str, ...], str] = {}
        for tag, equipment in snapshot.equipment.items():
            for alias in _alias_variants(equipment):
                tokens = tuple(preprocess(alias).split())
                if tokens:
                    self.aliases[tokens] = tag
        self.max_tokens = max((len(key) for key in self.aliases), default=1)

    def _match_at(self, tokens: list[str], start: int) -> Mention | None:
        for size in range(min(self.max_tokens, len(tokens) - start), 0, -1):
            key = tuple(tokens[start:start + size])
            tag = self.aliases.get(key)
            if tag:
                return Mention(tag, start, start + size, " ".join(key))
        return None

    def find_mentions(self, tokens: list[str]) -> list[Mention]:
        found: list[Mention] = []
        i = 0
        while i < len(tokens):
            mention = self._match_at(tokens, i)
            if mention:
                found.append(mention)
                i = mention.end
            else:
                i += 1
        return found

    def mask(self, tokens: list[str], mentions: list[Mention]) -> list[str]:
        """Replace equipment aliases by a placeholder so numbers inside names are not read as values."""
        masked = list(tokens)
        for mention in reversed(mentions):
            masked[mention.start:mention.end] = [f"<eq:{mention.tag}>"]
        return masked

    def ambiguous_equipment(self, text: str) -> list[str] | None:
        """Return candidates when the operator uses a bare family name.

        "la bomba" without one/two/three and "el filtro" without A/B are ambiguous.
        """
        normal = " " + normalize_text(text) + " "
        if re.search(r"\b(la|una|esa) bomba\b", normal) and not re.search(
            r"\b(bomba (uno|dos|tres|1|2|3)|la (uno|dos|tres)|b-?10[123])\b", normal
        ):
            return self.snapshot.pumps()
        if re.search(r"\b(el|ese|un|del) filtro\b", normal) and not re.search(
            r"\b(filtro [ab]|el (primario|secundario|grueso|fino)|el de la (izquierda|derecha)|f-?201[ab])\b", normal
        ):
            return self.snapshot.filters()
        return None

    def family_for(self, variable: str) -> list[str]:
        if variable in ("presion_diferencial",):
            return self.snapshot.filters()
        if variable in (
            "presion_descarga_local",
            "temperatura_rodamiento_ir",
            "goteo_empaquetadura",
            "nivel_aceite_visor",
            "estado_correas",
            "ruido",
            "estado",
        ):
            return self.snapshot.pumps()
        return []

    def tag_from_text(self, text: str) -> str | None:
        tokens = preprocess(text).split()
        mentions = self.find_mentions(tokens)
        return mentions[0].tag if len({m.tag for m in mentions}) == 1 else None
