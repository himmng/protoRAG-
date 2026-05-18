"""POST /api/chat — RAG retrieval + LLM streaming via SSE."""

import asyncio
import json
import os
import traceback

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..auth.db import User
from ..auth.deps import current_user
from ..config import ChatRequest
from ..paths import _validate_session, resolve_dirs
from ..rag.chroma import _release_session, get_vectorstore
from ..rag.embeddings import get_embeddings
from ..rag.history import load_history, save_history
from ..rag.indexer import _rebuild_index_background
from ..rag.llm import get_llm
from ..rag.mentions import parse_at_mentions
from ..state import _session_locks


router = APIRouter()


@router.post("/api/chat")
async def chat(request: ChatRequest, user: User = Depends(current_user)):
    _validate_session(request.session_id)
    session_id = request.session_id
    raw_message = request.message
    config = request.config

    db_dir, docs_dir = resolve_dirs(user.user_id, request.data_dir)
    mentioned_files, query = parse_at_mentions(raw_message)
    if not query:
        query = raw_message

    db_path = os.path.join(db_dir, session_id, "chromadb")
    context = ""
    retrieval_warning = ""

    if os.path.exists(db_path):
        try:
            meta_path = os.path.join(db_dir, session_id, "embed_meta.json")
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = json.load(f)
                if meta.get("embedding_model") != config.embedding_model:
                    retrieval_warning = (
                        f"\n\n> ⚠️ **RAG skipped — embedding model mismatch**: "
                        f"documents indexed with `{meta['embedding_model']}` "
                        f"but settings use `{config.embedding_model}`. "
                        "Re-upload your documents to fix this."
                    )
                    raise ValueError("embedding model mismatch")

                if meta.get("corrupted"):
                    retrieval_warning = (
                        "\n\n> ⚠️ **RAG index is being rebuilt** — "
                        "please ask your question again in a moment."
                    )
                    raise ValueError("index being rebuilt")

            embeddings = get_embeddings(config)
            vectorstore = get_vectorstore(db_path, embeddings, user.user_id, session_id)

            # Count through the already-open LangChain client — avoids opening a
            # second raw PersistentClient whose SQLite WAL snapshot may not include
            # vectors written by the LangChain client, breaking incremental uploads.
            total = vectorstore._collection.count()
            if total == 0:
                raise ValueError("empty collection — no vectors indexed yet")

            k = min(8, total)
            fetch_k = min(30, max(k + 1, total))

            docs = []
            if mentioned_files:
                session_doc_path = os.path.join(docs_dir, session_id)
                available = set(
                    f for f in (os.listdir(session_doc_path) if os.path.exists(session_doc_path) else [])
                    if os.path.isfile(os.path.join(session_doc_path, f))
                )
                valid = [f for f in mentioned_files if f in available]
                missing = [f for f in mentioned_files if f not in available]

                if missing:
                    retrieval_warning += (
                        "\n\n> ⚠️ **Document(s) not found in this session**: "
                        + ", ".join(f"`{f}`" for f in missing)
                    )

                if valid:
                    where_filter = (
                        {"doc_filename": {"$eq": valid[0]}}
                        if len(valid) == 1
                        else {"doc_filename": {"$in": valid}}
                    )
                    # ChromaDB Rust backend crashes with MMR + where filter — use
                    # plain similarity_search which goes through a different code path.
                    docs = vectorstore.similarity_search(query, k=k, filter=where_filter)
                    print(f"[RAG] @filter {where_filter} → {len(docs)} chunks")
            else:
                docs = vectorstore.max_marginal_relevance_search(query, k=k, fetch_k=fetch_k)
                sources = list({d.metadata.get("doc_filename", "?") for d in docs})
                print(f"[RAG] MMR → {len(docs)} chunks from {sources}")

            if docs:
                grouped: dict[str, list[str]] = {}
                for d in docs:
                    src = d.metadata.get("doc_filename", "unknown")
                    grouped.setdefault(src, []).append(d.page_content)
                context = "\n\n---\n\n".join(
                    f"### Source: {src}\n" + "\n\n".join(chunks)
                    for src, chunks in grouped.items()
                )

        except Exception as e:
            print(f"[RAG] Retrieval error: {e}")
            traceback.print_exc()
            if "Error finding id" in str(e):
                # Mark the index as corrupted so subsequent requests skip RAG
                # while the background task wipes and rebuilds. Release the
                # cached Chroma *now* so its SQLite/HNSW handles are closed
                # before the rebuild wipes the directory — otherwise the next
                # PersistentClient hits SQLITE_READONLY_DIRECTORY (1032).
                _release_session(user.user_id, session_id, db_path)
                meta_path = os.path.join(db_dir, session_id, "embed_meta.json")
                try:
                    _m: dict = {}
                    if os.path.exists(meta_path):
                        with open(meta_path) as f:
                            _m = json.load(f)
                    _m["indexed_files"] = []
                    _m["corrupted"] = True
                    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
                    with open(meta_path, "w") as f:
                        json.dump(_m, f)
                except Exception:
                    pass

                asyncio.create_task(
                    _rebuild_index_background(
                        user.user_id, session_id, db_path, docs_dir, db_dir, config
                    )
                )
                retrieval_warning = (
                    "\n\n> ⚠️ **RAG index was corrupted.** "
                    "Your documents are being re-indexed in the background — "
                    "please ask your question again in a moment."
                )
            elif not retrieval_warning:
                retrieval_warning = f"\n\n> ⚠️ **RAG retrieval failed**: {e}"

    history = load_history(session_id, db_dir)

    session_doc_path = os.path.join(docs_dir, session_id)
    session_docs = sorted(
        f for f in (os.listdir(session_doc_path) if os.path.exists(session_doc_path) else [])
        if os.path.isfile(os.path.join(session_doc_path, f))
    )
    doc_list_note = (
        f"The user has uploaded {len(session_docs)} document(s) to this session: "
        + ", ".join(f'"{d}"' for d in session_docs)
        + "."
    ) if session_docs else "No documents have been uploaded to this session yet."

    sys_prompt = (
        "You are a helpful and intelligent AI assistant. "
        f"{doc_list_note} "
        "When answering from document context, always specify which document your answer comes from."
    )
    messages = [SystemMessage(content=sys_prompt)]
    for msg in history[-10:]:
        role = msg.get("role", "")
        if role == "user":
            messages.append(HumanMessage(content=msg.get("content", "")))
        elif role == "assistant":
            messages.append(AIMessage(content=msg.get("content", "")))

    if context:
        source_note = f"(filtered to: {', '.join(mentioned_files)})" if mentioned_files else ""
        all_docs_line = (
            f"Session documents ({len(session_docs)}): {', '.join(session_docs)}.\n"
            "The excerpts below are the most relevant chunks retrieved for this query.\n\n"
        ) if session_docs else ""
        augmented = (
            f"{all_docs_line}"
            f"Retrieved context {source_note}:\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n"
            "Answer using the context above and cite which document(s) your answer comes from. "
            "For questions about how many documents are in the session or their names, "
            "use the full session document list stated above — not just what was retrieved.\n\n"
            f"User Query: {query}"
        )
        messages.append(HumanMessage(content=augmented))
    else:
        messages.append(HumanMessage(content=query))

    llm = get_llm(config)
    lock = _session_locks[(user.user_id, session_id)]

    async def generate():
        full_response = ""
        try:
            async for chunk in llm.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    full_response += token
                    yield f"data: {json.dumps({'content': token})}\n\n"
        except Exception as e:
            err = f"\n\n**Connection Error:** {e}"
            full_response += err
            yield f"data: {json.dumps({'content': err})}\n\n"

        if retrieval_warning:
            full_response += retrieval_warning
            yield f"data: {json.dumps({'content': retrieval_warning})}\n\n"

        async with lock:
            current = load_history(session_id, db_dir)
            current.append({"role": "user", "content": query})
            current.append({"role": "assistant", "content": full_response})
            save_history(session_id, current, db_dir)

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
