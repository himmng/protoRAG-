"""Path validation, traversal-safe joins, and per-user data resolution."""

import os
from typing import Optional

from fastapi import HTTPException

from .config import DATA_DIR, _UUID_RE


def _validate_session(session_id: str):
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")


def _validate_user_id(user_id: str):
    # User ids are server-issued uuid4s; same shape as session ids.
    if not _UUID_RE.match(user_id):
        raise HTTPException(status_code=400, detail="Invalid user id")


def safe_join(base: str, *paths: str) -> str:
    base_real = os.path.realpath(base)
    candidate = os.path.realpath(os.path.join(base, *paths))
    if not candidate.startswith(base_real + os.sep) and candidate != base_real:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


def _effective_data_dir(custom: Optional[str]) -> str:
    """Return the data dir to use: custom override (expanded ~) or DATA_DIR default."""
    if custom and custom.strip():
        return os.path.expanduser(custom.strip())
    return DATA_DIR


def resolve_dirs(user_id: str, data_dir: Optional[str] = None):
    """Return (db_dir, docs_dir) rooted under the user's per-data-dir folder.

    Layout: `{data_dir}/users/{user_id}/{db,documents}/session/`. Both
    directories are created on first call.
    """
    _validate_user_id(user_id)
    base = _effective_data_dir(data_dir)
    user_root = safe_join(base, "users", user_id)
    db_dir = os.path.join(user_root, "db", "session")
    docs_dir = os.path.join(user_root, "documents", "session")
    try:
        os.makedirs(db_dir, exist_ok=True)
        os.makedirs(docs_dir, exist_ok=True)
    except OSError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create data directory '{base}': {e}",
        )
    return db_dir, docs_dir


def collection_name_for(session_id: str) -> str:
    return f"col_{session_id}"
