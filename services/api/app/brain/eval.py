"""Brain recall@k evaluator.

Loads a labeled set (`tests/brain/recall.yml`), runs each query through an
in-process RRF retrieval, and reports recall@k. Used as both a one-shot
script and the engine behind unit tests.

The retrieval is hand-rolled here (no Postgres) so the eval can run on a
laptop with just Python + cachetools + an embedder. Production retrieval
in `brain/retrieval.py` uses pgvector + tsvector; this evaluator is the
"is the embedding actually capturing meaning" check, deliberately simpler.

The embedder is a callable injected at runtime so tests can stub it.
Default is `app.brain.embeddings.embed`.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True)
class EvalResult:
    k: int
    queries: int
    hits: int
    misses: int

    @property
    def recall_at_k(self) -> float:
        if not self.queries:
            return 0.0
        return self.hits / self.queries

    def as_dict(self) -> dict:
        return {
            "k": self.k,
            "queries": self.queries,
            "hits": self.hits,
            "misses": self.misses,
            "recall_at_k": round(self.recall_at_k, 4),
        }


def _load_yaml(path: Path) -> dict:
    """Minimal YAML loader. We only support what `recall.yml` actually uses:
    top-level mapping with `sources:` (list of {id,title,body}) and
    `queries:` (list of {q, expect: [ids]}). No tags, no anchors.
    Avoid a PyYAML hard dependency for the eval script."""
    try:
        import yaml

        return yaml.safe_load(path.read_text()) or {}
    except ImportError:
        return _miniyaml(path.read_text())


def _miniyaml(text: str) -> dict:
    """Walk the file producing a dict for `sources` + `queries`. Handles
    list items with `- key: value` and folded `|` block scalars."""
    out: dict = {"sources": [], "queries": []}
    current_section: str | None = None
    current_item: dict = {}
    in_block: tuple[str, list[str]] | None = None
    base_indent: int = 0

    for raw in text.splitlines():
        if raw.startswith("#") or not raw.strip():
            if in_block:
                in_block[1].append("")
            continue

        line = raw.rstrip("\n")
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if in_block:
            key, lines = in_block
            if indent > base_indent:
                lines.append(line[base_indent + 2 :])
                continue
            current_item[key] = "\n".join(lines).strip("\n")
            in_block = None

        if stripped.endswith(":") and indent == 0:
            current_section = stripped[:-1]
            out.setdefault(current_section, [])
            continue

        if stripped.startswith("- "):
            current_item = {}
            out[current_section].append(current_item)
            stripped = stripped[2:].strip()
            indent_after = indent + 2
        else:
            indent_after = indent

        if ": " in stripped:
            k, _, v = stripped.partition(": ")
            v = v.strip()
            if v == "|":
                in_block = (k.strip(), [])
                base_indent = indent_after
            elif v.startswith("[") and v.endswith("]"):
                current_item[k.strip()] = [s.strip() for s in v[1:-1].split(",") if s.strip()]
            else:
                v = v.strip('"').strip("'")
                current_item[k.strip()] = v
        elif stripped.endswith(":"):
            current_item[stripped[:-1]] = None

    if in_block:
        key, lines = in_block
        current_item[key] = "\n".join(lines).strip("\n")
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def run_eval(
    spec_path: Path,
    *,
    k: int = 5,
    embedder: Embedder | None = None,
) -> EvalResult:
    """Load the spec, embed sources + queries, score, report recall@k."""
    spec = _load_yaml(spec_path)
    sources = spec.get("sources") or []
    queries = spec.get("queries") or []

    if not sources or not queries:
        return EvalResult(k=k, queries=0, hits=0, misses=0)

    if embedder is None:
        from app.brain.embeddings import embed

        embedder = embed

    source_texts = [f"{s.get('title','')}\n\n{s.get('body','')}" for s in sources]
    source_vecs = await embedder(source_texts)

    query_texts = [q["q"] for q in queries]
    query_vecs = await embedder(query_texts)

    hits = 0
    misses = 0
    for q, qv in zip(queries, query_vecs, strict=False):
        scored = sorted(
            ((_cosine(qv, sv), sources[i]["id"]) for i, sv in enumerate(source_vecs)),
            reverse=True,
        )
        top_ids = {sid for _, sid in scored[:k]}
        expect: Iterable[str] = q.get("expect") or []
        if any(e in top_ids for e in expect):
            hits += 1
        else:
            misses += 1

    return EvalResult(k=k, queries=len(queries), hits=hits, misses=misses)


def main():
    """CLI entrypoint: python -m app.brain.eval [path/to/recall.yml]"""
    import argparse
    import asyncio
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "spec",
        nargs="?",
        default="tests/brain/recall.yml",
        help="path to the recall.yml spec",
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="exit nonzero if recall@k is below this",
    )
    args = parser.parse_args()

    result = asyncio.run(run_eval(Path(args.spec), k=args.k))
    print(json.dumps(result.as_dict(), indent=2))
    if result.recall_at_k < args.threshold:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
