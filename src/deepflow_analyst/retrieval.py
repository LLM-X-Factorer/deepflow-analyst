"""X · few-shot example retrieval (BM25).

A tiny BM25-over-characters retriever for injecting similar solved
question→SQL pairs into the Writer's system prompt. The goal is to give
the LLM concrete precedent for structurally hard patterns (self-join,
DISTINCT ON, 5-way join chain) that it gets wrong zero-shot.

Design choices:
- **BM25 over CJK + alnum character unigrams/bigrams**. Keeps the module
  zero-config: no tokenizer model, no language detection, no embedding
  API. Good enough for a ~30-example bank of short questions.
- **Bank is independent of the golden dataset**. Overlap would be data
  leakage into the eval loop; `test_retrieval.py` asserts no question
  string is shared. Upgrade to pgvector/Milvus + real embeddings is a
  W11 teaching exercise; the retrieval interface here stays the same.
"""

from __future__ import annotations

import itertools
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

_CJK_RE = re.compile(r"[一-鿿]")
_ALNUM_RE = re.compile(r"[a-z0-9]+")

EXAMPLES_PATH = Path(__file__).resolve().parent / "fewshot" / "examples.jsonl"


@dataclass(frozen=True)
class Example:
    question: str
    sql: str


def _tokenize(text: str) -> list[str]:
    """Mixed unigram + bigram tokens for CJK, lowercased word tokens for Latin.

    Characters outside CJK / ASCII alnum are dropped. The mixed scheme
    keeps single-character signal (好, 最) while also capturing short
    Chinese compounds (销售, 曲风) — both help BM25 find relevant neighbors
    on short queries.
    """
    lowered = text.lower()
    tokens: list[str] = []
    # CJK unigrams
    cjk_chars = _CJK_RE.findall(lowered)
    tokens.extend(cjk_chars)
    # CJK bigrams
    tokens.extend(a + b for a, b in itertools.pairwise(cjk_chars))
    # Latin alphanumeric words
    tokens.extend(_ALNUM_RE.findall(lowered))
    return tokens


def load_examples(path: Path = EXAMPLES_PATH) -> list[Example]:
    out: list[Example] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        d = json.loads(line)
        out.append(Example(question=d["question"], sql=d["sql"]))
    return out


class ExampleBank:
    def __init__(self, examples: list[Example]) -> None:
        if not examples:
            raise ValueError("ExampleBank requires at least one example")
        self._examples = examples
        self._bm25 = BM25Okapi([_tokenize(ex.question) for ex in examples])

    @property
    def size(self) -> int:
        return len(self._examples)

    def top_k(self, query: str, k: int = 3) -> list[Example]:
        if k <= 0:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
        return [self._examples[i] for i, score in ranked[:k] if score > 0]


_bank_lock = threading.Lock()
_cached_bank: ExampleBank | None = None


def get_default_bank() -> ExampleBank:
    """Load and cache the bundled example bank on first access."""
    global _cached_bank
    with _bank_lock:
        if _cached_bank is None:
            _cached_bank = ExampleBank(load_examples())
        return _cached_bank


def format_examples_block(examples: list[Example]) -> str:
    """Render a compact Markdown-free block for the Writer prompt.

    One example per entry; each has a ``Q:`` line and a ``SQL:`` line.
    No labels like "Example 1" — the LLM doesn't need the numbering, and
    extra tokens in the system prompt are paid on every call.
    """
    parts: list[str] = []
    for ex in examples:
        parts.append(f"Q: {ex.question}\nSQL: {ex.sql}")
    return "\n\n".join(parts)
