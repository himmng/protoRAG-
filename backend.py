import asyncio
import os
import json
import re
import shutil
import traceback
from collections import defaultdict

import chromadb
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

app = FastAPI(title="protoRAG+ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.environ.get("DEFAULT_DATA_DIR", "./data")
MAX_HISTORY_ENTRIES = 200
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".json", ".yaml", ".yml"}
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


# ── Validation & path helpers ─────────────────────────────────────────────────

def _validate_session(session_id: str):
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")


def safe_join(base: str, *paths: str) -> str:
    base_real = os.path.realpath(base)
    candidate = os.path.realpath(os.path.join(base, *paths))
    if not candidate.startswith(base_real + os.sep) and candidate != base_real:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


def resolve_dirs():
    db_dir = os.path.join(DATA_DIR, "db", "session")
    docs_dir = os.path.join(DATA_DIR, "documents", "session")
    os.makedirs(db_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)
    return db_dir, docs_dir


def collection_name_for(session_id: str) -> str:
    return f"col_{session_id}"


# ── Provider / config ─────────────────────────────────────────────────────────

class ChatConfig(BaseModel):
    provider: str
    base_url: str
    api_key: str
    model_name: str
    embedding_model: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    config: ChatConfig


def _safe_api_key(key: str) -> str:
    """Return 'dummy' for blank/none keys (OpenAI-compat servers ignore it anyway)."""
    return key.strip() if key and key.strip().lower() not in ("", "none") else "dummy"


def normalise_base_url(provider: str, base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url
    if provider.lower() in ("ollama", "lmstudio"):
        return url + "/v1"
    return url


def get_embeddings(config: ChatConfig) -> OpenAIEmbeddings:
    """
    All providers use OpenAI-compatible embeddings.
    For Anthropic (which has no embedding API), base_url must point to a local
    embedding service, e.g. http://localhost:11434/v1 (Ollama).
    """
    if config.provider.lower() == "anthropic":
        embed_url = config.base_url.rstrip("/")
        embed_key = "dummy"
    else:
        embed_url = normalise_base_url(config.provider, config.base_url)
        embed_key = _safe_api_key(config.api_key)

    return OpenAIEmbeddings(
        model=config.embedding_model,
        openai_api_base=embed_url,
        openai_api_key=embed_key,
        check_embedding_ctx_length=False,
    )


def get_llm(config: ChatConfig):
    provider = config.provider.lower()

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise RuntimeError(
                "langchain-anthropic not installed. Run: pip install langchain-anthropic"
            )
        return ChatAnthropic(
            model=config.model_name,
            anthropic_api_key=config.api_key,
            streaming=True,
            max_tokens=8192,
        )

    # All OpenAI-compatible providers: Ollama, LM Studio, LiteLLM, OpenAI, Custom
    base_url = normalise_base_url(config.provider, config.base_url)
    api_key = _safe_api_key(config.api_key)
    return ChatOpenAI(
        model=config.model_name,
        openai_api_base=base_url,
        openai_api_key=api_key,
        streaming=True,
    )


# ── ChromaDB helpers ──────────────────────────────────────────────────────────

def _chroma_client(db_path: str) -> chromadb.PersistentClient:
    os.makedirs(db_path, exist_ok=True)
    return chromadb.PersistentClient(path=db_path)


def get_vectorstore(db_path: str, embeddings, session_id: str) -> Chroma:
    os.makedirs(db_path, exist_ok=True)
    return Chroma(
        persist_directory=db_path,
        embedding_function=embeddings,
        collection_name=collection_name_for(session_id),
    )


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


# ── Document loading ──────────────────────────────────────────────────────────

def load_document(file_path: str, filename: str):
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        try:
            from langchain_community.document_loaders import PyPDFLoader
            return PyPDFLoader(file_path).load()
        except ImportError:
            raise RuntimeError("pypdf required for PDF. Run: pip install pypdf")
    from langchain_community.document_loaders import TextLoader
    return TextLoader(file_path, autodetect_encoding=True).load()


def get_text_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)


# ── History helpers ───────────────────────────────────────────────────────────

def load_history(session_id: str, db_dir: str) -> list:
    path = os.path.join(db_dir, session_id, "history.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_history(session_id: str, history: list, db_dir: str):
    path = os.path.join(db_dir, session_id, "history.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(history[-MAX_HISTORY_ENTRIES:], f)


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_document(
    session_id: str = Form(...),
    provider: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(...),
    model_name: str = Form(...),
    embedding_model: str = Form(...),
    file: UploadFile = File(...),
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

        db_dir, docs_dir = resolve_dirs()
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

        db_path = safe_join(db_dir, session_id, "chromadb")

        async with _session_locks[session_id]:
            # Remove stale vectors for this file before re-indexing
            _delete_vectors_for_file(db_path, session_id, filename)

            embeddings = get_embeddings(config)
            vectorstore = get_vectorstore(db_path, embeddings, session_id)
            vectorstore.add_documents(splits)

            meta_path = os.path.join(db_dir, session_id, "embed_meta.json")
            os.makedirs(os.path.dirname(meta_path), exist_ok=True)
            with open(meta_path, "w") as f:
                json.dump({
                    "embedding_model": config.embedding_model,
                    "provider": config.provider,
                }, f)

        print(f"[RAG] Indexed {len(splits)} chunks for '{filename}' in session '{session_id}'")
        return {"status": "success", "message": f"Indexed {filename} ({len(splits)} chunks)."}

    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ── @mention parsing ──────────────────────────────────────────────────────────

def parse_at_mentions(message: str) -> tuple[list[str], str]:
    pattern = r'@"([^"]+)"|@(\S+)'
    mentions = [m.group(1) or m.group(2) for m in re.finditer(pattern, message)]
    cleaned = re.sub(pattern, "", message).strip()
    return mentions, cleaned


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(request: ChatRequest):
    _validate_session(request.session_id)
    session_id = request.session_id
    raw_message = request.message
    config = request.config

    db_dir, docs_dir = resolve_dirs()
    mentioned_files, query = parse_at_mentions(raw_message)
    if not query:
        query = raw_message

    db_path = os.path.join(db_dir, session_id, "chromadb")
    context = ""
    retrieval_warning = ""

    if os.path.exists(db_path) and _count_vectors(db_path, session_id) > 0:
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

            embeddings = get_embeddings(config)
            vectorstore = get_vectorstore(db_path, embeddings, session_id)

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
                    retriever = vectorstore.as_retriever(
                        search_type="mmr",
                        search_kwargs={"k": 8, "fetch_k": 30, "filter": where_filter},
                    )
                    docs = retriever.invoke(query)
                    print(f"[RAG] @filter {where_filter} → {len(docs)} chunks")
            else:
                docs = vectorstore.max_marginal_relevance_search(query, k=8, fetch_k=30)
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
            if not retrieval_warning:
                retrieval_warning = f"\n\n> ⚠️ **RAG retrieval failed**: {e}"

    history = load_history(session_id, db_dir)

    sys_prompt = (
        "You are a helpful and intelligent AI assistant. "
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
        augmented = (
            f"Context from the user's uploaded documents {source_note}:\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n"
            "Answer ONLY from the context above. Cite the source document(s).\n\n"
            f"User Query: {query}"
        )
        messages.append(HumanMessage(content=augmented))
    else:
        messages.append(HumanMessage(content=query))

    llm = get_llm(config)
    lock = _session_locks[session_id]

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


# ── Session management ────────────────────────────────────────────────────────

@app.get("/api/sessions")
def list_sessions():
    db_dir, docs_dir = resolve_dirs()
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


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    _validate_session(session_id)
    db_dir, docs_dir = resolve_dirs()
    history = load_history(session_id, db_dir)
    doc_path = os.path.join(docs_dir, session_id)
    docs = [
        f for f in (os.listdir(doc_path) if os.path.exists(doc_path) else [])
        if os.path.isfile(os.path.join(doc_path, f))
    ]
    return {"history": history, "documents": docs}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    _validate_session(session_id)
    db_dir, docs_dir = resolve_dirs()
    for path in [os.path.join(db_dir, session_id), os.path.join(docs_dir, session_id)]:
        if os.path.exists(path):
            shutil.rmtree(path)
    return {"status": "success"}


@app.get("/api/sessions/{session_id}/documents/{filename}")
def get_document(session_id: str, filename: str):
    _validate_session(session_id)
    _, docs_dir = resolve_dirs()
    session_dir = safe_join(docs_dir, session_id)
    file_path = safe_join(session_dir, os.path.basename(filename))
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.delete("/api/sessions/{session_id}/documents/{filename}")
async def delete_document(session_id: str, filename: str):
    _validate_session(session_id)
    db_dir, docs_dir = resolve_dirs()

    session_dir = safe_join(docs_dir, session_id)
    safe_filename = os.path.basename(filename)
    file_path = safe_join(session_dir, safe_filename)

    if os.path.exists(file_path):
        os.remove(file_path)
        print(f"[DOC] Removed '{safe_filename}' from session '{session_id}'")

    db_path = safe_join(db_dir, session_id, "chromadb")
    remaining = []

    async with _session_locks[session_id]:
        _delete_vectors_for_file(db_path, session_id, safe_filename)

        remaining = [
            f for f in (os.listdir(session_dir) if os.path.exists(session_dir) else [])
            if os.path.isfile(os.path.join(session_dir, f))
        ]

        if not remaining and os.path.exists(db_path):
            shutil.rmtree(db_path)
            print(f"[RAG] Wiped ChromaDB for session '{session_id}' (no documents left)")

    return {"status": "success", "remaining_documents": remaining}


# ── UI ────────────────────────────────────────────────────────────────────────

@app.get("/")
def get_ui():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found alongside backend.py</h1>")


if __name__ == "__main__":
    import uvicorn
    print("Starting protoRAG+...")
    print("Open http://localhost:8000 in your browser.")
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
