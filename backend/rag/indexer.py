"""Background re-indexing after an HNSW corruption event."""

import json
import os
import shutil

from ..config import ChatConfig
from ..state import _session_locks
from .chroma import _release_session, get_vectorstore
from .embeddings import get_embeddings
from .loaders import get_text_splitter, load_document


async def _rebuild_index_background(
    user_id: str,
    session_id: str,
    db_path: str,
    docs_dir: str,
    db_dir: str,
    config: ChatConfig,
):
    """Re-index all session documents after a corruption event.

    The corrupted system is already released by chat()'s exception handler via
    _release_chroma_system. We call it again here as belt-and-suspenders before
    the wipe — guarantees no cached system holds open handles on the directory
    we're about to delete.
    """
    session_doc_path = os.path.join(docs_dir, session_id)
    doc_files = sorted(
        f for f in (os.listdir(session_doc_path) if os.path.exists(session_doc_path) else [])
        if os.path.isfile(os.path.join(session_doc_path, f))
    )

    async with _session_locks[(user_id, session_id)]:
        _release_session(user_id, session_id, db_path)
        if os.path.exists(db_path):
            try:
                shutil.rmtree(db_path)
                print(f"[RAG] Wiped corrupted ChromaDB for session '{user_id}/{session_id}'")
            except Exception as e:
                print(f"[RAG] Could not wipe ChromaDB: {e}")

        meta_path = os.path.join(db_dir, session_id, "embed_meta.json")

        if not doc_files:
            try:
                if os.path.exists(meta_path):
                    with open(meta_path) as f:
                        _m = json.load(f)
                    _m.pop("corrupted", None)
                    with open(meta_path, "w") as f:
                        json.dump(_m, f)
            except Exception:
                pass
            return

        rebuilt: list[str] = []
        try:
            embeddings = get_embeddings(config)
            vs = get_vectorstore(db_path, embeddings, user_id, session_id)
            for doc_file in doc_files:
                try:
                    rdocs = load_document(os.path.join(session_doc_path, doc_file), doc_file)
                    rsplits = get_text_splitter().split_documents(rdocs)
                    for chunk in rsplits:
                        chunk.metadata["doc_filename"] = doc_file
                    vs.add_documents(rsplits)
                    rebuilt.append(doc_file)
                    print(f"[RAG] Background-rebuilt '{doc_file}' ({len(rsplits)} chunks)")
                except Exception as e:
                    print(f"[RAG] Background-rebuild failed for '{doc_file}': {e}")
        except Exception as e:
            print(f"[RAG] Background-rebuild aborted: {e}")
            try:
                if os.path.exists(meta_path):
                    with open(meta_path) as f:
                        _m = json.load(f)
                    _m.pop("corrupted", None)
                    with open(meta_path, "w") as f:
                        json.dump(_m, f)
            except Exception:
                pass
            return

        try:
            existing_meta: dict = {}
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    existing_meta = json.load(f)
            existing_meta["indexed_files"] = sorted(rebuilt)
            existing_meta.pop("corrupted", None)
            os.makedirs(os.path.dirname(meta_path), exist_ok=True)
            with open(meta_path, "w") as f:
                json.dump(existing_meta, f)
        except Exception:
            pass
        print(f"[RAG] Background rebuild complete for '{user_id}/{session_id}': {rebuilt}")
