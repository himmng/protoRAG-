"""ChromaDB lifecycle and the per-session vectorstore cache.

The cache and release helpers exist to work around two ChromaDB quirks:

1. `SharedSystemClient` caches systems by exact `persist_directory` string, so
   wiping the directory while a cached system still holds SQLite/HNSW handles
   leaves the next `PersistentClient(path=…)` returning the dead system. We
   pop the cache entry and `system.stop()` before any rmtree.
2. Constructing a fresh `Chroma` wrapper per request churns the in-memory HNSW
   segment (`sync_threshold=1000` — small collections live only in RAM) and
   races writes against reads, surfacing as `Error finding id`. Reusing one
   wrapper per session keeps that segment stable.
"""

import os
import traceback

import chromadb
from langchain_chroma import Chroma

from ..paths import collection_name_for


# (user_id, session_id) → (embedding_model_name, db_path, Chroma).
# db_path is part of the cached value (not the key) so a mid-session change to
# the user's data directory invalidates the cached wrapper instead of silently
# writing to the old path.
_session_vectorstores: dict[tuple[str, str], tuple[str, str, "Chroma"]] = {}


def _chroma_client(db_path: str) -> chromadb.PersistentClient:
    os.makedirs(db_path, exist_ok=True)
    return chromadb.PersistentClient(path=db_path)


def _release_chroma_system(db_path: str) -> None:
    """Force-release the cached ChromaDB system for this path.

    Required before wiping a directory whose system is currently cached —
    otherwise the next PersistentClient hands back the dead system, whose
    stale handles cause SQLITE_READONLY_DIRECTORY (code 1032) on the first
    write to the rebuilt db.
    """
    try:
        from chromadb.api.shared_system_client import SharedSystemClient
        with SharedSystemClient._refcount_lock:
            system = SharedSystemClient._identifier_to_system.pop(db_path, None)
            SharedSystemClient._identifier_to_refcount.pop(db_path, None)
        if system is not None:
            system.stop()
            print(f"[RAG] Released cached ChromaDB system for '{db_path}'")
    except Exception as e:
        print(f"[RAG] Could not release ChromaDB system for '{db_path}': {e}")


def _release_session(user_id: str, session_id: str, db_path: str) -> None:
    """Drop the cached Chroma for this user/session and force-release the system.

    Call before any operation that wipes or recreates the on-disk database
    (corruption recovery, re-upload, session/document delete) — otherwise the
    next get_vectorstore() returns a Chroma whose handles point at the now-
    deleted directory.
    """
    key = (user_id, session_id)
    cached = _session_vectorstores.pop(key, None)
    if cached is not None:
        try:
            cached[2]._client.close()
        except Exception as e:
            print(f"[RAG] Error closing cached Chroma for '{user_id}/{session_id}': {e}")
        # Also release the system at the cached path in case it differs
        # from db_path (data dir was changed mid-session).
        if cached[1] != db_path:
            _release_chroma_system(cached[1])
    _release_chroma_system(db_path)


def get_vectorstore(db_path: str, embeddings, user_id: str, session_id: str) -> Chroma:
    """Return a per-(user,session) cached Chroma, reused across requests.

    The cache is invalidated when either the embedding model or the on-disk
    db_path changes — the embedding function and persist_directory are bound
    at Chroma construction, so a stale wrapper would silently embed new uploads
    with the wrong model or write to the wrong directory.
    """
    key = (user_id, session_id)
    model = getattr(embeddings, "model", "") or ""
    cached = _session_vectorstores.get(key)
    if cached is not None and cached[0] == model and cached[1] == db_path:
        return cached[2]

    if cached is not None:
        try:
            cached[2]._client.close()
        except Exception:
            pass
        if cached[1] != db_path:
            _release_chroma_system(cached[1])
        _session_vectorstores.pop(key, None)

    os.makedirs(db_path, exist_ok=True)
    vs = Chroma(
        persist_directory=db_path,
        embedding_function=embeddings,
        collection_name=collection_name_for(session_id),
    )
    _session_vectorstores[key] = (model, db_path, vs)
    return vs


def _delete_vectors_for_file(db_path: str, session_id: str, filename: str) -> int:
    """
    Delete all vectors tagged with doc_filename==filename using the raw ChromaDB
    client — no embedding function required, so no dimension-mismatch errors.
    """
    if not os.path.exists(db_path):
        return 0
    try:
        client = _chroma_client(db_path)
        col_name = collection_name_for(session_id)
        try:
            collection = client.get_collection(col_name)
        except Exception:
            return 0  # collection doesn't exist yet

        result = collection.get(where={"doc_filename": filename})
        ids = result.get("ids", [])
        if ids:
            collection.delete(ids=ids)
            print(f"[RAG] Deleted {len(ids)} vectors for '{filename}'")
        return len(ids)
    except Exception as e:
        print(f"[RAG] Warning: could not delete vectors for '{filename}': {e}")
        traceback.print_exc()
        return 0


def _count_vectors(db_path: str, session_id: str) -> int:
    if not os.path.exists(db_path):
        return 0
    try:
        collection = _chroma_client(db_path).get_collection(collection_name_for(session_id))
        return collection.count()
    except Exception:
        return 0


def flush_all_vectorstores() -> None:
    """Close all cached Chroma instances so HNSW state is flushed to disk."""
    for key, (_, _, vs) in list(_session_vectorstores.items()):
        try:
            vs._client.close()
        except Exception as e:
            print(f"[RAG] Error closing Chroma for '{key}' on shutdown: {e}")
    _session_vectorstores.clear()
