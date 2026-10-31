"""Small text helpers shared by the tools."""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """Lowercase and strip accents so "Violão" matches "violao"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")
