"""
Nouveautés de chaque version, lues dans NOUVEAUTES.md (embarqué dans l'exe).

Format : une section « ## 1.2.3 » par version, de la plus récente à la plus
ancienne.
"""

from __future__ import annotations

import re

from core import config

NOTES_FILE = "NOUVEAUTES.md"
_SECTION = re.compile(r"^## +v?(\d+(?:\.\d+)*)\b[^\n]*$", re.M)


def _key(version: str) -> tuple[int, ...]:
    numbers = tuple(int(n) for n in re.findall(r"\d+", str(version))[:4])
    return numbers + (0,) * max(0, 3 - len(numbers))


def sections(text: str) -> list[tuple[str, str]]:
    """[(version, texte de sa section)] dans l'ordre du fichier."""
    found = list(_SECTION.finditer(text))
    result = []
    for n, match in enumerate(found):
        end = found[n + 1].start() if n + 1 < len(found) else len(text)
        result.append((match.group(1), text[match.end():end].strip()))
    return result


def notes_between(text: str, since: str | None, upto: str) -> list[tuple[str, str]]:
    """Sections des versions postérieures à `since` (exclue) jusqu'à `upto`
    (incluse), de la plus récente à la plus ancienne ; toutes si `since` est vide."""
    low = _key(since) if since else None
    high = _key(upto)
    chosen = [(v, body) for v, body in sections(text)
              if _key(v) <= high and (low is None or _key(v) > low)]
    return sorted(chosen, key=lambda item: _key(item[0]), reverse=True)


def load_notes() -> str:
    try:
        return config.resource_path(NOTES_FILE).read_text(encoding="utf-8")
    except OSError:
        return ""


def as_markdown(chosen: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"### Version {version}\n\n{body}" for version, body in chosen)
