"""Verify the per-(org, dept) keying surface of agent_runtime without booting
real containers. We only check the pure helpers that produce names and dirs."""
from pathlib import Path
from uuid import uuid4

from app.agent_runtime import _container_name, _dept_dir


def test_container_name_distinct_per_department():
    org_id = uuid4()
    dept_a = uuid4()
    dept_b = uuid4()
    assert _container_name(org_id, dept_a) != _container_name(org_id, dept_b)
    # Same dept must reproduce the same name (idempotent ensure_running).
    assert _container_name(org_id, dept_a) == _container_name(org_id, dept_a)


def test_container_name_distinct_per_org():
    dept_id = uuid4()
    org_a = uuid4()
    org_b = uuid4()
    assert _container_name(org_a, dept_id) != _container_name(org_b, dept_id)


def test_container_name_within_docker_limit():
    # Docker name max length is 253. Ours uses 8-char uuid prefixes plus
    # a small literal prefix; should be well under.
    name = _container_name(uuid4(), uuid4())
    assert name.startswith("aki-hermes-")
    assert len(name) < 64


def test_dept_dir_isolation(tmp_path, monkeypatch):
    """Two departments under one org get distinct workspace directories."""
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "hermes_data_dir", str(tmp_path))

    org = uuid4()
    a = _dept_dir(org, uuid4())
    b = _dept_dir(org, uuid4())
    assert a != b
    assert Path(a).exists()
    assert Path(b).exists()
