"""Chunker is pure — no external deps. Cover the three split paths."""

from app.brain.chunker import chunk_text


def test_short_input_yields_one_chunk():
    chunks = chunk_text("hello world", target_tokens=100)
    assert len(chunks) == 1
    assert chunks[0].content == "hello world"
    assert chunks[0].index == 0


def test_paragraph_split_emits_multiple_chunks():
    # Two paragraphs, each ~500 chars, target 100 tokens (=400 chars).
    p1 = "alpha " * 100
    p2 = "bravo " * 100
    chunks = chunk_text(p1 + "\n\n" + p2, target_tokens=100, overlap_chars=20)
    assert len(chunks) >= 2
    assert "alpha" in chunks[0].content
    # Last chunk should contain the bravo paragraph somewhere.
    assert any("bravo" in c.content for c in chunks)


def test_no_content_lost_at_paragraph_boundaries():
    # Concatenating chunks should reproduce all source tokens.
    text = "\n\n".join(f"para-{i} " * 50 for i in range(5))
    chunks = chunk_text(text, target_tokens=80, overlap_chars=0)
    rebuilt = " ".join(c.content for c in chunks)
    for i in range(5):
        assert f"para-{i}" in rebuilt


def test_oversize_paragraph_falls_back_to_sentences():
    # Single huge paragraph, multiple sentences. Should not crash and should
    # subdivide into more than one chunk.
    sentence = "x" * 200 + "."
    text = " ".join([sentence] * 5)
    chunks = chunk_text(text, target_tokens=50, overlap_chars=0)
    assert len(chunks) >= 2
