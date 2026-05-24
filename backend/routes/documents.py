"""Document download, preview (with Office→PDF), and delete."""

import asyncio
import json
import os
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..auth.db import User
from ..auth.deps import current_user
from ..config import _OFFICE_EXTS, _PREVIEW_DIRNAME
from ..paths import _validate_session, resolve_dirs, safe_join
from ..rag.chroma import _delete_vectors_for_file, _release_session
from ..rag.history import append_system_notice
from ..state import _session_locks


router = APIRouter()


def _soffice_bin() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _preview_cache_path(session_dir: str, filename: str) -> str:
    base = os.path.splitext(filename)[0]
    previews_dir = safe_join(session_dir, _PREVIEW_DIRNAME)
    return safe_join(previews_dir, base + ".pdf")


def _clear_preview_cache_for(session_dir: str, filename: str) -> None:
    try:
        cached = _preview_cache_path(session_dir, filename)
        if os.path.exists(cached):
            os.remove(cached)
    except HTTPException:
        pass


async def _convert_office_to_pdf(src_path: str, session_dir: str, filename: str) -> str:
    soffice = _soffice_bin()
    if not soffice:
        raise HTTPException(
            status_code=503,
            detail="LibreOffice not installed on backend host. Install it to preview Office files (e.g. `sudo apt install libreoffice` or `brew install --cask libreoffice`).",
        )

    cached = _preview_cache_path(session_dir, filename)
    if os.path.exists(cached) and os.path.getmtime(cached) >= os.path.getmtime(src_path):
        return cached

    out_dir = os.path.dirname(cached)
    os.makedirs(out_dir, exist_ok=True)

    # Use a per-conversion user profile so concurrent conversions don't collide
    # on LibreOffice's single-instance lock.
    profile_dir = os.path.join(out_dir, f".lo_profile_{os.getpid()}")
    os.makedirs(profile_dir, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        soffice,
        f"-env:UserInstallation=file://{profile_dir}",
        "--headless", "--convert-to", "pdf",
        "--outdir", out_dir, src_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="LibreOffice conversion timed out")

    if proc.returncode != 0 or not os.path.exists(cached):
        msg = stderr.decode(errors="ignore").strip() or "unknown error"
        raise HTTPException(status_code=500, detail=f"LibreOffice conversion failed: {msg[:300]}")
    return cached


@router.get("/api/sessions/{session_id}/documents/{filename}/preview")
async def preview_document(
    session_id: str,
    filename: str,
    data_dir: Optional[str] = Query(None),
    user: User = Depends(current_user),
):
    _validate_session(session_id)
    _, docs_dir = resolve_dirs(user.user_id, data_dir)
    session_dir = safe_join(docs_dir, session_id)
    safe_filename = os.path.basename(filename)
    file_path = safe_join(session_dir, safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    ext = os.path.splitext(safe_filename.lower())[1]
    if ext in _OFFICE_EXTS:
        pdf_path = await _convert_office_to_pdf(file_path, session_dir, safe_filename)
        return FileResponse(pdf_path, media_type="application/pdf")
    return FileResponse(file_path)


@router.get("/api/sessions/{session_id}/documents/{filename}")
def get_document(
    session_id: str,
    filename: str,
    data_dir: Optional[str] = Query(None),
    user: User = Depends(current_user),
):
    _validate_session(session_id)
    _, docs_dir = resolve_dirs(user.user_id, data_dir)
    session_dir = safe_join(docs_dir, session_id)
    file_path = safe_join(session_dir, os.path.basename(filename))
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@router.delete("/api/sessions/{session_id}/documents/{filename}")
async def delete_document(
    session_id: str,
    filename: str,
    data_dir: Optional[str] = Query(None),
    user: User = Depends(current_user),
):
    _validate_session(session_id)
    db_dir, docs_dir = resolve_dirs(user.user_id, data_dir)

    session_dir = safe_join(docs_dir, session_id)
    safe_filename = os.path.basename(filename)
    file_path = safe_join(session_dir, safe_filename)

    _clear_preview_cache_for(session_dir, safe_filename)

    db_path = safe_join(db_dir, session_id, "chromadb")
    remaining = []

    async with _session_locks[(user.user_id, session_id)]:
        # Remove the file inside the lock so the prev-count snapshot is
        # consistent with the post-state — prevents a concurrent upload from
        # racing in between os.remove and the transition check below.
        file_existed = os.path.exists(file_path)
        if file_existed:
            os.remove(file_path)
            print(f"[DOC] Removed '{safe_filename}' from session '{user.user_id}/{session_id}'")

        _delete_vectors_for_file(db_path, session_id, safe_filename)

        remaining = [
            f for f in (os.listdir(session_dir) if os.path.exists(session_dir) else [])
            if os.path.isfile(os.path.join(session_dir, f))
        ]

        if not remaining and os.path.exists(db_path):
            _release_session(user.user_id, session_id, db_path)
            shutil.rmtree(db_path)
            print(f"[RAG] Wiped ChromaDB for session '{user.user_id}/{session_id}' (no documents left)")

        # Remove the deleted file from the indexed_files tracking in meta.
        meta_path = os.path.join(db_dir, session_id, "embed_meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                meta["indexed_files"] = sorted(
                    x for x in meta.get("indexed_files", []) if x != safe_filename
                )
                with open(meta_path, "w") as f:
                    json.dump(meta, f)
            except Exception:
                pass

        if file_existed and not remaining:
            append_system_notice(
                session_id,
                db_dir,
                "Chat mode resumed — all documents removed. Replies are no longer grounded in any documents.",
            )

    return {"status": "success", "remaining_documents": remaining}
