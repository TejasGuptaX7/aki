"""Brain — shared, embedding-indexed, ACL-aware memory.

Both Hermes (cloud, per-department) and Aki (desktop, per-employee) write to
and retrieve from Brain. Sources carry an ACL snapshot at ingest; retrieval
intersects current-principal principals against that snapshot *after* RRF
fusion. Live ACL re-checks against the source provider are deferred to a
later phase.
"""

from app.brain.hydration import hydrate_messages, persist_turn

__all__ = ["hydrate_messages", "persist_turn"]
