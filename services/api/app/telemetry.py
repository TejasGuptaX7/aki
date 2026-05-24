"""OpenTelemetry instrumentation for the Aki API.

Provides automatic tracing for:
- LLM calls (model, tokens, latency, cost)
- Tool calls (name, params, result, success/failure)
- Brain retrieval (query, k, latency, sources)
- Agent runtime (container lifecycle)
- Database queries (via SQLAlchemy instrumentation)

Usage:
    from app.telemetry import get_tracer, trace_llm_call, trace_tool_call

    with trace_llm_call(tracer, model="gpt-5", messages=msgs) as span:
        response = await hermes_chat(...)
        span.set_attribute("llm.usage.prompt_tokens", ...)
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from app.config import get_settings

log = logging.getLogger(__name__)


_RESOURCE = Resource.create({
    SERVICE_NAME: "aki-api",
    SERVICE_VERSION: "0.1.0",
    "deployment.environment": get_settings().app_env,
})

_provider: TracerProvider | None = None


def init_telemetry() -> TracerProvider:
    """Initialize the OpenTelemetry tracer provider.

    Call once at application startup. Uses OTLP HTTP exporter by default;
    falls back to console exporter if no collector is configured.
    """
    global _provider
    if _provider is not None:
        return _provider

    _provider = TracerProvider(resource=_RESOURCE)

    # Try OTLP HTTP exporter; fallback to console if misconfigured
    try:
        otlp_endpoint = get_settings().otlp_endpoint
        if otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            _provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info("OpenTelemetry OTLP exporter configured: %s", otlp_endpoint)
    except Exception:
        log.warning("OTLP exporter not configured; traces will not be exported externally")

    trace.set_tracer_provider(_provider)

    # Instrument SQLAlchemy for automatic DB query tracing
    try:
        SQLAlchemyInstrumentor().instrument()
    except Exception:
        log.warning("SQLAlchemy instrumentation failed")

    return _provider


def get_tracer(name: str = "aki-api") -> trace.Tracer:
    """Get a named tracer."""
    if _provider is None:
        init_telemetry()
    return trace.get_tracer(name)


@contextmanager
def trace_llm_call(
    tracer: trace.Tracer,
    *,
    model: str,
    messages: list[dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
) -> Generator[Span, None, None]:
    """Context manager for tracing an LLM call."""
    with tracer.start_as_current_span("llm.chat") as span:
        span.set_attribute("llm.system", "OpenAI")
        span.set_attribute("llm.request.model", model)
        span.set_attribute("llm.request.type", "chat")
        if temperature is not None:
            span.set_attribute("llm.request.temperature", temperature)
        if max_tokens is not None:
            span.set_attribute("llm.request.max_tokens", max_tokens)
        if messages:
            span.set_attribute("llm.request.num_messages", len(messages))
        if org_id:
            span.set_attribute("org.id", org_id)
        if user_id:
            span.set_attribute("user.id", user_id)

        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_tool_call(
    tracer: trace.Tracer,
    *,
    tool_name: str,
    tool_params: dict | None = None,
    org_id: str | None = None,
) -> Generator[Span, None, None]:
    """Context manager for tracing a tool call."""
    with tracer.start_as_current_span(f"tool.{tool_name}") as span:
        span.set_attribute("tool.name", tool_name)
        if tool_params:
            # Truncate to avoid huge spans
            span.set_attribute("tool.params", str(tool_params)[:1000])
        if org_id:
            span.set_attribute("org.id", org_id)

        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_retrieval(
    tracer: trace.Tracer,
    *,
    query: str,
    k: int,
    org_id: str | None = None,
) -> Generator[Span, None, None]:
    """Context manager for tracing a Brain retrieval."""
    with tracer.start_as_current_span("brain.retrieve") as span:
        span.set_attribute("brain.query", query[:500])
        span.set_attribute("brain.k", k)
        if org_id:
            span.set_attribute("org.id", org_id)

        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextmanager
def trace_container_lifecycle(
    tracer: trace.Tracer,
    *,
    org_id: str,
    dept_id: str,
    action: str,  # "ensure_running", "boot", "shutdown", "hibernate"
) -> Generator[Span, None, None]:
    """Context manager for tracing container lifecycle operations."""
    with tracer.start_as_current_span(f"hermes.{action}") as span:
        span.set_attribute("hermes.org_id", org_id)
        span.set_attribute("hermes.dept_id", dept_id)
        span.set_attribute("hermes.action", action)

        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def set_span_attributes_from_usage(span: Span, usage: dict[str, Any]) -> None:
    """Helper to set standard LLM usage attributes on a span."""
    if "prompt_tokens" in usage:
        span.set_attribute("llm.usage.prompt_tokens", usage["prompt_tokens"])
    if "completion_tokens" in usage:
        span.set_attribute("llm.usage.completion_tokens", usage["completion_tokens"])
    if "total_tokens" in usage:
        span.set_attribute("llm.usage.total_tokens", usage["total_tokens"])
