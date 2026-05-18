"""POST /api/upload — save a file, chunk it, and index into ChromaDB."""

import json
import os
import shutil
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ..auth.db import User
from ..auth.deps import current_user
from ..config import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, ChatConfig
from ..paths import _validate_session, resolve_dirs, safe_join
from ..rag.chroma import _release_session, get_vectorstore
from ..rag.embeddings import get_embeddings
from ..rag.loaders import get_text_splitter, load_document
from ..state import _session_locks


router = APIRouter()


@router.post("/api/upload")
async def upload_document(
    session_id: str = Form(...),
    provider: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(...),
    model_name: str = Form(...),
    embedding_model: str = Form(...),
    data_dir: Optional[str] = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    try:
        _validate_session(session_id)

        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return {"status": "error", "message": f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}

        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            return {"status": "error", "message": f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)."}

        config = ChatConfig(
            provider=provider, base_url=base_url, api_key=api_key,
            model_name=model_name, embedding_model=embedding_model,
        )

        db_dir, docs_dir = resolve_dirs(user.user_id, data_dir)
        session_doc_path = safe_join(docs_dir, session_id)
        os.makedirs(session_doc_path, exist_ok=True)

        filename = os.path.basename(file.filename or "upload")
        file_path = safe_join(session_doc_path, filename)
        with open(file_path, "wb") as f:
            f.write(content)

        docs = load_document(file_path, filename)
        splits = get_text_splitter().split_documents(docs)
        for chunk in splits:
            chunk.metadata["doc_filename"] = filename

        if not splits:
            return {"status": "warning", "message": f"'{filename}' was saved but produced 0 text chunks — it may be empty, image-only, or unsupported internally. RAG will not work for this file."}

        db_path = safe_join(db_dir, session_id, "chromadb")

        async with _session_locks[(user.user_id, session_id)]:
            embeddings = get_embeddings(config)

            # Read existing meta (tracks which filenames are already indexed).
            # Using a plain JSON file avoids opening a second ChromaDB client to
            # do the re-upload check — dual PersistentClient instances on the same
            # path cause SQLite WAL conflicts that crash the upsert.
            meta_path = os.path.join(db_dir, session_id, "embed_meta.json")
            meta: dict = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path) as f:
                        meta = json.load(f)
                except Exception:
                    pass

            indexed_files: set = set(meta.get("indexed_files", []))
            is_reupload = filename in indexed_files

            if is_reupload:
                # Wipe the ChromaDB directory entirely so the rebuild starts from a
                # clean slate — no ghost HNSW entries, no lock conflicts. Release
                # the cached Chroma first so its handles aren't pointing at a
                # deleted dir when get_vectorstore() reopens below.
                _release_session(user.user_id, session_id, db_path)
                if os.path.exists(db_path):
                    shutil.rmtree(db_path)
                    print(f"[RAG] Wiped ChromaDB for rebuild (re-upload of '{filename}')")

            # Single LangChain client for all indexing in this request.
            vectorstore = get_vectorstore(db_path, embeddings, user.user_id, session_id)
            vectorstore.add_documents(splits)
            indexed_files.add(filename)

            if is_reupload:
                for other in os.listdir(session_doc_path):
                    if other == filename or not os.path.isfile(os.path.join(session_doc_path, other)):
                        continue
                    try:
                        other_docs = load_document(os.path.join(session_doc_path, other), other)
                        other_splits = get_text_splitter().split_documents(other_docs)
                        for chunk in other_splits:
                            chunk.metadata["doc_filename"] = other
                        vectorstore.add_documents(other_splits)
                        indexed_files.add(other)
                        print(f"[RAG] Re-indexed '{other}' during rebuild")
                    except Exception as e:
                        print(f"[RAG] Could not re-index '{other}': {e}")

            print(f"[RAG] Indexed {len(splits)} chunks for '{filename}'")

            os.makedirs(os.path.dirname(meta_path), exist_ok=True)
            with open(meta_path, "w") as f:
                json.dump({
                    "embedding_model": config.embedding_model,
                    "provider": config.provider,
                    "indexed_files": sorted(indexed_files),
                }, f)

        return {"status": "success", "message": f"Indexed {filename} ({len(splits)} chunks)."}

    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}
