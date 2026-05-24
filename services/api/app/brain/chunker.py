"""Tiny token-budget chunker. Approximate, no LangChain dependency.

Token-count estimate uses a 4-chars-per-token heuristic (close enough for
English; we don't ship `tiktoken`). Splits on paragraph boundaries first,
then on sentence boundaries, then on whitespace, then forced character-
window cuts as a last resort. Adds `overlap_chars` of trailing context to
the next chunk to preserve coherence.
"""

from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 4  # rough approximation


@dataclass(frozen=True)
class Chunk:
    index: int
    content: str
    token_count: int


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def chunk_text(
    text: str,
    *,
    target_tokens: int = 800,
    overlap_chars: int = 100,
) -> list[Chunk]:
    """Split `text` into chunks of roughly `target_tokens` tokens."""
    text = text.strip()
    if not text:
        return []

    budget = target_tokens * CHARS_PER_TOKEN
    # First, break into the smallest reasonable units that all individually
    # fit the budget. Then greedy-pack them into chunks.
    units = _atomize(text, budget)

    chunks: list[Chunk] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf.strip():
            chunks.append(
                Chunk(index=len(chunks), content=buf.strip(), token_count=_approx_tokens(buf))
            )

    def emit_and_seed_overlap():
        nonlocal buf
        flush()
        buf = buf[-overlap_chars:] if overlap_chars and buf and chunks else ""

    for unit in units:
        sep = "\n\n" if buf and unit.startswith("\n") is False else ""
        candidate = (buf + sep + unit) if buf else unit
        if len(candidate) <= budget:
            buf = candidate
        else:
            emit_and_seed_overlap()
            buf = (buf + sep + unit) if buf else unit

    flush()
    return chunks


def _atomize(text: str, budget: int) -> list[str]:
    """Return a list of atomic units (each <= budget chars). Tries paragraph,
    then sentence, then whitespace, then forced char-window splits."""
    out: list[str] = []
    for paragraph in [p for p in text.split("\n\n") if p.strip()]:
        if len(paragraph) <= budget:
            out.append(paragraph)
            continue
        for sentence in _split_sentences(paragraph):
            if len(sentence) <= budget:
                out.append(sentence)
                continue
            # Whitespace pack: build words up to budget then emit.
            cur = ""
            for w in sentence.split():
                candidate = (cur + " " + w) if cur else w
                if len(candidate) > budget:
                    if cur:
                        out.append(cur)
                    # If a single word exceeds budget (rare; URLs, base64),
                    # force-split by characters.
                    if len(w) > budget:
                        for i in range(0, len(w), budget):
                            out.append(w[i : i + budget])
                        cur = ""
                    else:
                        cur = w
                else:
                    cur = candidate
            if cur:
                out.append(cur)
    return out


def _split_sentences(text: str) -> list[str]:
    """Cheap sentence splitter: break after . ! ? followed by whitespace.
    Good enough for chunking; we're not parsing English."""
    out: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(text):
        cur.append(text[i])
        if text[i] in ".!?":
            j = i + 1
            while j < len(text) and text[j] == ")":
                cur.append(text[j])
                j += 1
            if j < len(text) and text[j].isspace():
                out.append("".join(cur).strip())
                cur = []
                i = j
                continue
        i += 1
    tail = "".join(cur).strip()
    if tail:
        out.append(tail)
    return out
