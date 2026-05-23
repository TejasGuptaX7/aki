"""The Alembic env can't import a broken migration. Verify 0003 imports
cleanly and exposes the standard {upgrade, downgrade, revision, down_revision}
surface. Doesn't run SQL — that requires a live Postgres.

Module name starts with a digit so we use importlib.util directly rather
than import_module (which follows identifier rules)."""
import importlib.util
from pathlib import Path


def test_migration_0003_imports():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "0003_dept_jobs_brain.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0003", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0003"
    assert mod.down_revision == "0002"
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


def test_migration_0001_still_intact():
    """Catches a downstream rename that would break the chain."""
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "0001_initial.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0001", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0001"
    assert mod.down_revision is None
