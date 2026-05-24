"""Integration: retention SQL uses valid Postgres interval syntax."""

from __future__ import annotations


def test_retention_sql_valid():
    """Ensure enforce_retention does not use broken interval ':days days' syntax."""
    import inspect

    from app.retention import enforce_retention

    source = inspect.getsource(enforce_retention)
    assert "interval ':days days'" not in source
    assert "interval '1 day'" in source or "make_interval" in source
