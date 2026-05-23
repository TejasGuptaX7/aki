# Phase 1 tests

## Pure unit tests (run anywhere)

These pass with just `pytest` + `cryptography`. No DB, no Docker, no Redis:

- `test_chunker.py` — Brain chunker boundary behavior (4 tests).
- `test_dept_runtime.py` — per-(org, dept) container-name and
  workspace-dir isolation (4 tests).

```
pip install pytest cryptography
python -m pytest tests/test_chunker.py tests/test_dept_runtime.py -v
```

## Needs project deps installed (`pip install -r requirements.txt`)

- `test_device_jwt.py` — Ed25519 device JWT round-trip + revocation reject.
  Pulls in `app.auth` which transitively imports `sqlalchemy`.
- `test_migration_imports.py` — parses Alembic 0003 and verifies the chain.
  Pulls in `sqlalchemy`/`pgvector` from the migration.

```
cd services/api
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Still to wire (needs CI Postgres + Redis + Docker)

The plan called for full E2E coverage:

- `test_brain_retrieve` against a seeded Postgres with pgvector
- `test_dept_runtime` actually booting two containers and asserting two
  distinct ports live in Docker
- `test_device_pair` doing the full pair → JWT → /me → revoke → 401 cycle
- `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
  round-trip against a throwaway database

These are gated on CI containers. The unit tests here cover the pure
logic; the integration tests are a Phase 2 follow-up.
