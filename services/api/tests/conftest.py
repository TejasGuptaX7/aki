"""Shared pytest config. Sets APP_ENV=dev so test imports don't blow up on
missing prod secrets."""
import os
import sys
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("ALLOW_DEV_AUTH_BYPASS", "true")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aki_test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://postgres:postgres@localhost:5432/aki_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

# Put services/api on the path so `import app.*` works.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
