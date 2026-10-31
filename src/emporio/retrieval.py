"""BM25 retrieval over the policy sections.

The manual has about 25 short sections, so a dependency-free BM25 is enough and keeps
the project easy to run. Section titles are repeated in the indexed text so a question
that uses the section's own words ("devolução", "frete") ranks it first.
"""

from __future__ import annotations

import math
from collections import Counter

from .policies import Chunk, load_chunks
from .text import tokens

STOPWORDS = set(
    "a o as os um uma de do da dos das em no na nos nas por para com sem e ou que se ao aos "
    "eu meu minha voces voce posso pode quero como qual quais tem ter ha foi ser sao".split()
)

# Words customers use that the manual words differently.
SYNONYMS = {
    "devolver": "devolucao", "devolvo": "devolucao", "devolva": "devolucao",
    "arrependi": "arrependimento", "arrependimento": "arrependimento",
    "trocar": "troca", "trocas": "troca",
    "entregar": "entrega", "entregas": "entrega", "frete": "frete",
    "parcelar": "parcelamento", "parcelas": "parcelamento", "parcela": "parcelamento",
    "pagar": "pagamento", "pagamentos": "pagamento",
    "horarios": "horario", "aberto": "horario", "abre": "horario", "fecha": "horario",
    "defeito": "defeito", "quebrou": "defeito", "garantia": "garantia",
}


def _terms(text: str) -> list[str]:
    return [SYNONYMS.get(t, t) for t in tokens(text) if t not in STOPWORDS]


class PolicyIndex:
    def __init__(self, chunks: list[Chunk] | None = None, k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks if chunks is not None else load_chunks()
        self.k1, self.b = k1, b
        docs = [_terms(f"{c.title} {c.title} {c.text}") for c in self.chunks]
        self._tf = [Counter(d) for d in docs]
        self._len = [len(d) for d in docs]
        self._avg = sum(self._len) / len(self._len)
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        q = _terms(query)
        scored = []
        for chunk, tf, length in zip(self.chunks, self._tf, self._len):
            score = 0.0
            for term in q:
                if term not in tf:
                    continue
                freq = tf[term]
                norm = freq * (self.k1 + 1) / (freq + self.k1 * (1 - self.b + self.b * length / self._avg))
                score += self._idf.get(term, 0.0) * norm
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]
