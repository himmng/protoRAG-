"""GET /api/sessions, GET/DELETE /api/sessions/{sid}."""

import json
import os
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..auth.db import User
from ..auth.deps import current_user
from ..paths import _validate_session, resolve_dirs
from ..rag.chroma import _release_session
from ..rag.history import load_history


router = APIRouter()


@router.get("/api/sessions")
def list_sessions(
    data_dir: Optional[str] = Query(None),
    user: User = Depends(current_user),
):
    db_dir, docs_dir = resolve_dirs(user.user_id, data_dir)
    sessions = []

    if not os.path.exists(db_dir):
        return {"sessions": []}

    for sid in os.listdir(db_dir):
        if not os.path.isdir(os.path.join(db_dir, sid)):
            continue
        hist_path = os.path.join(db_dir, sid, "history.json")
        doc_path = os.path.join(docs_dir, sid)

        has_docs = (
            os.path.exists(doc_path)
            and any(os.path.isfile(os.path.join(doc_path, f)) for f in os.listdir(doc_path))
        ) if os.path.exists(doc_path) else False

        preview = "New Chat"
        timestamp = 0
        if os.path.exists(hist_path):
            try:
                with open(hist_path) as f:
                    hist = json.load(f)
                if hist:
                    last_user = next(
                        (m for m in reversed(hist) if m.get("role") == "user"),
                        hist[-1],
                    )
                    content = last_user.get("content", "")
                    preview = (content[:35] + "...") if len(content) > 35 else (content or "New Chat")
                timestamp = os.path.getmtime(hist_path)
            except Exception:
                preview = "(history corrupted)"

        sessions.append({"id": sid, "preview": preview, "timestamp": timestamp, "is_rag": has_docs})

    sessions.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"sessions": sessions}


@router.get("/api/sessions/{session_id}")
def get_session(
    session_id: str,
    data_dir: Optional[str] = Query(None),
    user: User = Depends(current_user),
):
    _validate_session(session_id)
    db_dir, docs_dir = resolve_dirs(user.user_id, data_dir)
    history = load_history(session_id, db_dir)
    doc_path = os.path.join(docs_dir, session_id)
    docs = [
        f for f in (os.listdir(doc_path) if os.path.exists(doc_path) else [])
        if os.path.isfile(os.path.join(doc_path, f))
    ]
    return {"history": history, "documents": docs}


@router.delete("/api/sessions/{session_id}")
def delete_session(
    session_id: str,
    data_dir: Optional[str] = Query(None),
    user: User = Depends(current_user),
):
    _validate_session(session_id)
    db_dir, docs_dir = resolve_dirs(user.user_id, data_dir)
    db_path = os.path.join(db_dir, session_id, "chromadb")
    _release_session(user.user_id, session_id, db_path)
    for path in [os.path.join(db_dir, session_id), os.path.join(docs_dir, session_id)]:
        if os.path.exists(path):
            shutil.rmtree(path)
    return {"status": "success"}
