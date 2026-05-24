"""Process-wide mutable state shared between routes and background tasks."""

import asyncio
from collections import defaultdict


# (user_id, session_id) → asyncio.Lock. Serialises mutating ops on a session's
# RAG store so concurrent uploads / deletes can't corrupt the on-disk ChromaDB.
# Keyed by both ids so two users that happen to choose the same session UUID
# don't share a lock.
_session_locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)
