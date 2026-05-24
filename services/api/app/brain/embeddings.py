"""Async OpenAI embeddings client for Brain.

Batches up to 100 inputs per request. No retries beyond httpx defaults — the
caller decides what to do on failure (skip + retry next sync, surface to
the user, etc.).
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.config import get_settings

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
BATCH_SIZE = 100


async def embed(texts: Sequence[str]) -> list[list[float]]:
    """Embed `texts`. Returns one vector per input in input order."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for embeddings")

    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            r = await client.post(
                OPENAI_EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": settings.embedding_model, "input": batch},
            )
            r.raise_for_status()
            data = r.json()
            # Response order matches input order per OpenAI contract.
            for item in data.get("data", []):
                out.append(item["embedding"])
    return out
