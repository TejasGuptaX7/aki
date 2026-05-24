"""The worker's SSE parser is pure stdlib. Exercise the standard shapes
without spinning up arq, redis, or Hermes."""

from app.worker import _parse_sse_blocks


def test_yields_complete_blocks_and_keeps_partial_tail():
    s = 'event: hermes.tool.progress\ndata: {"tool":"gmail"}\n\nevent: msg\ndata: pa'
    blocks, tail = _parse_sse_blocks(s)
    assert len(blocks) == 1
    assert blocks[0][0] == "hermes.tool.progress"
    assert blocks[0][1] == '{"tool":"gmail"}'
    assert tail == "event: msg\ndata: pa"


def test_handles_no_event_header():
    s = 'data: {"choices":[]}\n\n'
    blocks, tail = _parse_sse_blocks(s)
    assert len(blocks) == 1
    assert blocks[0][0] is None
    assert tail == ""


def test_multiple_blocks_in_one_call():
    s = "data: 1\n\ndata: 2\n\ndata: 3\n\n"
    blocks, tail = _parse_sse_blocks(s)
    assert [b[1] for b in blocks] == ["1", "2", "3"]
    assert tail == ""
