"""Brain retrieval pipeline integration.

Since retrieve needs a real DB with pgvector, we mock the DB session and
verify the SQL query construction and function signature.
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.brain import retrieval
from app.brain.retrieval import BrainHit, retrieve


@pytest.mark.asyncio
async def test_retrieve_signature():
    """Verify the public signature hasn't drifted."""
    sig = inspect.signature(retrieve)
    params = list(sig.parameters)
    assert params[0] == "db"
    assert params[1] == "org_id"
    assert "query" in sig.parameters
    assert "principals" in sig.parameters
    assert "k" in sig.parameters
    assert "scope_filter" in sig.parameters
    assert sig.parameters["k"].default == 8
    assert sig.parameters["scope_filter"].default is None


@pytest.mark.asyncio
async def test_retrieve_empty_query():
    """Empty query should short-circuit to []."""
    mock_db = AsyncMock()
    result = await retrieve(mock_db, uuid4(), query="   ", principals=[])
    assert result == []
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_query_contains_expected_clauses(monkeypatch):
    """Mock the DB and verify both vector and BM25 SQL contain expected clauses."""
    org_id = uuid4()
    query_text = "quarterly revenue"
    principals = [str(uuid4()), str(uuid4())]

    calls = []

    async def fake_execute(stmt, params=None):
        calls.append((str(stmt), params))
        # Return empty results for both vector and BM25 queries
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        return mock_result

    mock_db = AsyncMock()
    mock_db.execute = fake_execute

    monkeypatch.setattr(retrieval, "embed", AsyncMock(return_value=[[0.1, 0.2, 0.3]]))
    monkeypatch.setattr(retrieval, "rerank", lambda q, passages, top_k: [])
    monkeypatch.setattr(retrieval, "is_allowed", AsyncMock(return_value=True))

    result = await retrieve(
        mock_db, org_id, query=query_text, principals=principals, k=4, scope_filter="org"
    )

    assert result == []
    assert len(calls) >= 2

    vector_sql, vector_params = calls[0]
    bm25_sql, bm25_params = calls[1]

    # Vector query assertions
    assert "brain_chunks" in vector_sql
    assert "brain_sources" in vector_sql
    assert "embedding <=>" in vector_sql
    assert str(org_id) == vector_params.get("org")
    assert vector_params.get("scope_filter") == "org"

    # BM25 query assertions
    assert "brain_chunks" in bm25_sql
    assert "brain_sources" in bm25_sql
    assert "ts_rank_cd" in bm25_sql
    assert "plainto_tsquery" in bm25_sql
    assert query_text == bm25_params.get("q")
    assert bm25_params.get("scope_filter") == "org"


@pytest.mark.asyncio
async def test_retrieve_acl_filter_and_rerank(monkeypatch):
    """Verify ACL filtering and reranking paths are hit."""
    org_id = uuid4()
    chunk_id = uuid4()
    source_id = uuid4()

    fake_row = {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "content": "hello world",
        "title": "Doc",
        "acl_principals": [str(uuid4())],
        "kind": "slack",
        "origin": "slack",
        "uri": "https://example.com",
        "scope": "org",
        "scope_id": None,
        "distance": 0.1,
    }

    async def fake_execute(stmt, params=None):
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [fake_row]
        return mock_result

    mock_db = AsyncMock()
    mock_db.execute = fake_execute

    monkeypatch.setattr(retrieval, "embed", AsyncMock(return_value=[[0.1, 0.2, 0.3]]))
    monkeypatch.setattr(
        retrieval, "rerank", lambda q, passages, top_k: [(0, 0.99)]
    )
    monkeypatch.setattr(retrieval, "is_allowed", AsyncMock(return_value=True))

    result = await retrieve(
        mock_db, org_id, query="hello", principals=fake_row["acl_principals"], k=1
    )

    assert len(result) == 1
    assert isinstance(result[0], BrainHit)
    assert result[0].chunk_id == chunk_id
    assert result[0].source_id == source_id
    assert result[0].content == "hello world"
    assert result[0].score == 0.99
