"""Rate limiter wiring.

slowapi's in-memory backend is fine for a single-process dev/staging API.
For multi-worker production, configure with a Redis storage_uri so limits
hold across workers:

    Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)

We don't switch automatically because misconfigured Redis in dev breaks
local testing in confusing ways. Production deploy should set this
explicitly.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address


limiter = Limiter(key_func=get_remote_address)
