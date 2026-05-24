"""Tiny model-pricing table for back-of-envelope cost capture.

Prices change. Keep these conservative (lean expensive) until we wire actual
billing. The control plane records the resulting `cost_usd` in
audit_log.payload — use it as a signal, not a finance source of truth.

USD per **million** tokens, separately for input vs. output. Models we don't
recognize fall back to OPENAI_DEFAULT, which is gpt-5's rates.
"""

from __future__ import annotations

# USD / 1M tokens, (input, output).
_TABLE: dict[str, tuple[float, float]] = {
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "o3": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
}
_DEFAULT = _TABLE["gpt-5"]


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated USD cost for one chat completion. Cheap and obvious;
    not a substitute for whatever the provider's billing API eventually says."""
    in_rate, out_rate = _TABLE.get(model.lower(), _DEFAULT)
    cost = (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000.0
    return round(cost, 6)
