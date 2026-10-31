"""Turn the policy manual PDF into section-level chunks.

The manual is short and organised in numbered sections ("4.1 Direito de Arrependimento"),
so each numbered heading becomes one chunk. That keeps a rule and its conditions together,
which matters more here than a fixed chunk size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .data import DATA_DIR

PDF_PATH = DATA_DIR / "politicas_da_loja.pdf"
HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\.?\s+([A-ZÀ-Ú].{2,80})$")
PAGE_NOISE = re.compile(r"^(Empório da Música\s+Manual de Políticas e Procedimentos|Página \d+)$")


@dataclass(frozen=True)
class Chunk:
    number: str
    title: str
    text: str

    @property
    def top_level(self) -> str:
        return self.number.split(".")[0]


def _clean_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for page in PdfReader(str(path)).pages:
        # Layout mode keeps words together and table rows on one line; the default
        # mode emits one token per line for this PDF.
        for raw in (page.extract_text(extraction_mode="layout") or "").splitlines():
            line = re.sub(r"\s{2,}", "  ", raw.replace("​", "")).strip()
            if line and not PAGE_NOISE.match(line):
                lines.append(line)
    return lines


def load_chunks(path: Path = PDF_PATH) -> list[Chunk]:
    chunks: list[Chunk] = []
    number = title = ""
    body: list[str] = []

    def flush() -> None:
        if number and body:
            chunks.append(Chunk(number, title, "\n".join(body).strip()))

    top = 0  # last top-level section seen, to reject numbered list items like "5. Fechamento"
    for line in _clean_lines(path):
        match = HEADING.match(line)
        if match:
            first = int(match.group(1).split(".")[0])
            is_sub = "." in match.group(1)
            if (is_sub and first != top) or (not is_sub and first != top + 1):
                match = None
        if match:
            top = first
            flush()
            number, title, body = match.group(1), match.group(2).strip(), []
        elif number:
            body.append(line)
    flush()
    return chunks


if __name__ == "__main__":
    for chunk in load_chunks():
        print(f"[{chunk.number}] {chunk.title} ({len(chunk.text)} chars)")
