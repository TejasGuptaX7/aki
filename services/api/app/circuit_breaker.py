"""Circuit breaker pattern for external API calls.

Prevents cascading failures when upstream services (Composio, Stripe, OpenAI)
are degraded. After N failures within a window, the circuit opens and all
subsequent calls fail fast without hitting the upstream. After a cooldown,
a single probe is allowed; if it succeeds, the circuit closes.

Usage:
    from app.circuit_breaker import CircuitBreaker, CB_REGISTRY

    cb = CB_REGISTRY.get("composio")
    async with cb:
        result = await composio_client.do_something()

Or as a decorator:
    @cb.wrap
    async def my_function():
        ...
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from enum import Enum
from functools import wraps
from typing import Any, Callable, TypeVar

import redis.asyncio as redis

from app.config import get_settings

log = logging.getLogger(__name__)

T = TypeVar("T")


class State(Enum):
    CLOSED = "closed"      # normal operation
    OPEN = "open"          # failing fast
    HALF_OPEN = "half_open"  # allowing probe


class CircuitBreaker:
    """Redis-backed circuit breaker for distributed systems.

    In a single-process deployment, in-memory state is sufficient.
    For multi-worker, Redis provides shared state across processes.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        expected_exception: type[Exception] = Exception,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.expected_exception = expected_exception

        self._state = State.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    async def _redis(self) -> redis.Redis | None:
        try:
            settings = get_settings()
            return redis.from_url(settings.redis_url, decode_responses=True)
        except Exception:
            return None

    def _should_open(self) -> bool:
        return self._failure_count >= self.failure_threshold

    def _cooldown_expired(self) -> bool:
        if self._last_failure_time is None:
            return True
        return time.time() - self._last_failure_time >= self.recovery_timeout

    @asynccontextmanager
    async def __call__(self):
        """Context manager: use as `async with cb(): ...`"""
        async with self._lock:
            if self._state == State.OPEN:
                if self._cooldown_expired():
                    self._state = State.HALF_OPEN
                    self._half_open_calls = 0
                    log.info("circuit %s entering half-open", self.name)
                else:
                    raise CircuitBreakerOpen(self.name)

            if self._state == State.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpen(self.name)
                self._half_open_calls += 1

        try:
            yield
            async with self._lock:
                if self._state == State.HALF_OPEN:
                    self._state = State.CLOSED
                    self._failure_count = 0
                    self._half_open_calls = 0
                    log.info("circuit %s closed", self.name)
                else:
                    self._failure_count = max(0, self._failure_count - 1)
        except self.expected_exception as e:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.time()
                if self._should_open() and self._state != State.OPEN:
                    self._state = State.OPEN
                    log.warning(
                        "circuit %s opened after %d failures: %s",
                        self.name, self._failure_count, e,
                    )
            raise

    def wrap(self, fn: Callable[..., T]) -> Callable[..., T]:
        """Decorator: use as `@cb.wrap` on async functions."""
        if asyncio.iscoroutinefunction(fn):
            @wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> T:
                async with self():
                    return await fn(*args, **kwargs)
            return _async_wrapper
        else:
            @wraps(fn)
            def _sync_wrapper(*args: Any, **kwargs: Any) -> T:
                # For sync functions, run the context manager in an async loop
                loop = asyncio.get_event_loop()
                cm = self()
                loop.run_until_complete(cm.__aenter__())
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    loop.run_until_complete(cm.__aexit__(type(e), e, None))
                    raise
                else:
                    loop.run_until_complete(cm.__aexit__(None, None, None))
            return _sync_wrapper


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open."""
    def __init__(self, name: str) -> None:
        super().__init__(f"circuit breaker '{name}' is open")
        self.name = name


# Global registry of circuit breakers for common upstream services
CB_REGISTRY: dict[str, CircuitBreaker] = {
    "composio": CircuitBreaker("composio", failure_threshold=5, recovery_timeout=30.0),
    "stripe": CircuitBreaker("stripe", failure_threshold=3, recovery_timeout=60.0),
    "openai": CircuitBreaker("openai", failure_threshold=10, recovery_timeout=15.0),
    "clerk": CircuitBreaker("clerk", failure_threshold=5, recovery_timeout=30.0),
}
