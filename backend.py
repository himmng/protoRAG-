import asyncio
import os
import json
import re
import shutil
import traceback
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

app = FastAPI(title="Local Isolated RAG Chat API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.environ.get("DEFAULT_DATA_DIR", "./data")
MAX_HISTORY_ENTRIES = 200
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".json", ".yaml", ".yml"}
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class _DummyEmbeddings(Embeddings):
    """No-op embeddings for opening existing Chroma DBs without querying."""
    def embed_documents(self, texts): return [[0.0] for _ in texts]
    def embed_query(self, text): return [0.0]


def _validate_session(session_id: str):
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")


def normalise_base_url(provider: str, base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url
    if provider.lower() in ("ollama", "lmstudio"):
        return url + "/v1"
    return url


def resolve_dirs():
    db_dir = os.path.join(DATA_DIR, "db", "session")
    docs_dir = os.path.join(DATA_DIR, "documents", "session")
    os.makedirs(db_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)
    return db_dir, docs_dir


def safe_join(base: str, *paths: str) -> str:
    base_real = os.path.realpath(base)
    candidate = os.path.realpath(os.path.join(base, *paths))
    if not candidate.startswith(base_real + os.sep) and candidate != base_real:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


def get_text_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)


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


def get_embeddings(config: ChatConfig):
    base_url = normalise_base_url(config.provider, config.base_url)
    api_key = config.api_key if config.api_key and config.api_key.strip() not in ("", "none", "None") else "dummy"
    return OpenAIEmbeddings(
        model=config.embedding_model,
        openai_api_base=base_url,
        openai_api_key=api_key,
        check_embedding_ctx_length=False,
    )


def get_llm(config: ChatConfig):
    base_url = normalise_base_url(config.provider, config.base_url)
    api_key = config.api_key if config.api_key and config.api_key.strip() not in ("", "none", "None") else "dummy"
    return ChatOpenAI(
        model=config.model_name,
        openai_api_base=base_url,
        openai_api_key=api_key,
        streaming=True,
    )


def load_document(file_path: str, filename: str):
    if filename.lower().endswith(".pdf"):
        try:
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(file_path)
            return loader.load()
        except ImportError:
            raise Exception("pypdf is required for PDF support. Run: pip install pypdf")
    else:
        from langchain_community.document_loaders import TextLoader
        loader = TextLoader(file_path, autodetect_encoding=True)
        return loader.load()


def load_history(session_id: str, db_dir: str):
    hist_path = os.path.join(db_dir, session_id, "history.json")
    if os.path.exists(hist_path):
        with open(hist_path, "r") as f:
            return json.load(f)
    return []


def save_history(session_id: str, history: list, db_dir: str):
    trimmed = history[-MAX_HISTORY_ENTRIES:]
    hist_path = os.path.join(db_dir, session_id, "history.json")
    os.makedirs(os.path.dirname(hist_path), exist_ok=True)
    with open(hist_path, "w") as f:
        json.dump(trimmed, f)


def get_vectorstore(db_path: str, embeddings, session_id: str) -> Chroma:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path) and not os.access(db_path, os.W_OK):
        fixed_path = os.path.join(os.path.dirname(db_path), "chromadb_rw")
        try:
            if not os.path.exists(fixed_path):
                shutil.copytree(db_path, fixed_path)
                print(f"[RAG] Cloned read-only ChromaDB from '{db_path}' to '{fixed_path}'")
            db_path = fixed_path
        except Exception as e:
            print(f"[RAG] Warning: failed to clone read-only DB '{db_path}': {e}")
    return Chroma(
        persist_directory=db_path,
        embedding_function=embeddings,
        collection_name=f"col_{session_id}",
    )


def delete_vectors_for_file(vectorstore: Chroma, filename: str):
    try:
        result = vectorstore.get(where={"doc_filename": filename})
        ids_to_delete = result.get("ids", [])
        if ids_to_delete:
            vectorstore.delete(ids=ids_to_delete)
            print(f"[RAG] Deleted {len(ids_to_delete)} vectors for file '{filename}'")
        else:
            print(f"[RAG] No vectors found for file '{filename}'")
    except Exception as e:
        print(f"[RAG] Warning: could not delete vectors for '{filename}': {e}")
        traceback.print_exc()


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
            return {"status": "error", "message": f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)"}

        config = ChatConfig(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            embedding_model=embedding_model,
        )

        db_dir, docs_dir = resolve_dirs()
        session_doc_path = safe_join(docs_dir, session_id)
        os.makedirs(session_doc_path, exist_ok=True)

        filename = os.path.basename(file.filename)
        file_path = safe_join(session_doc_path, filename)

        with open(file_path, "wb") as f:
            f.write(content)

        docs = load_document(file_path, filename)
        text_splitter = get_text_splitter()
        splits = text_splitter.split_documents(docs)

        for chunk in splits:
            chunk.metadata["doc_filename"] = filename

        db_path = safe_join(db_dir, session_id, "chromadb")
        embeddings = get_embeddings(config)
        vectorstore = get_vectorstore(db_path, embeddings, session_id)

        delete_vectors_for_file(vectorstore, filename)
        vectorstore.add_documents(splits)
        print(f"[RAG] Indexed {len(splits)} chunks for '{filename}' in session '{session_id}'")

        meta_path = os.path.join(db_dir, session_id, "embed_meta.json")
        with open(meta_path, "w") as f:
            json.dump({"embedding_model": config.embedding_model}, f)

        return {"status": "success", "message": f"Uploaded and indexed {filename}."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


def parse_at_mentions(message: str) -> tuple[list[str], str]:
    pattern = r'@"([^"]+)"|@(\S+)'
    mentions = []
    for m in re.finditer(pattern, message):
        fname = m.group(1) or m.group(2)
        mentions.append(fname.strip())
    cleaned = re.sub(pattern, "", message).strip()
    return mentions, cleaned


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
                        f"Re-upload your documents to fix this."
                    )
                    raise ValueError("embedding model mismatch")

            embeddings = get_embeddings(config)
            vectorstore = get_vectorstore(db_path, embeddings, session_id)

            collection_count = vectorstore._collection.count()
            if collection_count == 0:
                print(f"[RAG] Collection empty for session {session_id}, skipping retrieval")
            else:
                docs = []
                if mentioned_files:
                    session_doc_path = os.path.join(docs_dir, session_id)
                    available = set(os.listdir(session_doc_path)) if os.path.exists(session_doc_path) else set()
                    valid_mentions = [f for f in mentioned_files if f in available]
                    not_found = [f for f in mentioned_files if f not in available]

                    if not_found:
                        retrieval_warning += (
                            f"\n\n> ⚠️ **Document(s) not found in this session**: "
                            + ", ".join(f"`{f}`" for f in not_found)
                        )

                    if valid_mentions:
                        where_filter = (
                            {"doc_filename": {"$eq": valid_mentions[0]}}
                            if len(valid_mentions) == 1
                            else {"doc_filename": {"$in": valid_mentions}}
                        )
                        print(f"[RAG] @mention filter: {where_filter}")
                        retriever = vectorstore.as_retriever(
                            search_type="mmr",
                            search_kwargs={"k": 8, "fetch_k": 25, "filter": where_filter},
                        )
                        docs = retriever.invoke(query)
                        retrieved = list({d.metadata.get("doc_filename", "") for d in docs})
                        print(f"[RAG] filtered MMR → {len(docs)} chunks from {retrieved}")
                else:
                    docs = vectorstore.max_marginal_relevance_search(query, k=8, fetch_k=25)
                    retrieved = list({d.metadata.get("doc_filename", "") for d in docs})
                    print(f"[RAG] MMR retrieval → {len(docs)} chunks from {retrieved}")

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
            print(f"Retrieval Error: {e}")
            traceback.print_exc()
            if not retrieval_warning:
                retrieval_warning = f"\n\n> ⚠️ **RAG retrieval failed**: {str(e)}"

    history = load_history(session_id, db_dir)

    sys_prompt = (
        "You are a helpful and intelligent AI assistant. "
        "When answering from document context, always specify which document your answer comes from."
    )
    messages = [SystemMessage(content=sys_prompt)]
    for msg in history[-10:]:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg.get("content", "")))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg.get("content", "")))

    if context:
        source_note = f"(filtered to: {', '.join(mentioned_files)})" if mentioned_files else ""
        augmented_query = (
            f"Context information from the user's local documents {source_note} is below.\n"
            "Each section is labeled with its source document.\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n"
            "Given ONLY the context above (no prior knowledge), answer the user's query. "
            "Cite which document(s) your answer draws from.\n\n"
            f"User Query: {query}"
        )
        messages.append(HumanMessage(content=augmented_query))
    else:
        messages.append(HumanMessage(content=query))

    llm = get_llm(config)
    lock = _session_locks[session_id]

    async def generate():
        full_response = ""
        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_response += chunk.content
                    yield f"data: {json.dumps({'content': chunk.content})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'content': f'\\n\\n**Connection Error:** {str(e)}'})}\n\n"

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


@app.get("/api/sessions")
def list_sessions():
    db_dir, docs_dir = resolve_dirs()
    sessions = []
    if os.path.exists(db_dir):
        for sid in os.listdir(db_dir):
            if not os.path.isdir(os.path.join(db_dir, sid)):
                continue
            hist_path = os.path.join(db_dir, sid, "history.json")
            doc_path = os.path.join(docs_dir, sid)

            has_docs = os.path.exists(doc_path) and bool(os.listdir(doc_path))
            preview = "New Chat"
            timestamp = 0
            if os.path.exists(hist_path):
                try:
                    with open(hist_path, "r") as f:
                        hist = json.load(f)
                    if hist:
                        last_user = next(
                            (m for m in reversed(hist) if m.get("role") == "user"),
                            hist[-1],
                        )
                        content = last_user.get("content", "")
                        preview = (content[:35] + "...") if content else "New Chat"
                    timestamp = os.path.getmtime(hist_path)
                except Exception:
                    traceback.print_exc()
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
    docs = os.listdir(doc_path) if os.path.exists(doc_path) else []
    return {"history": history, "documents": docs}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    _validate_session(session_id)
    db_dir, docs_dir = resolve_dirs()
    db_path = os.path.join(db_dir, session_id)
    doc_path = os.path.join(docs_dir, session_id)
    if os.path.exists(db_path):
        shutil.rmtree(db_path)
    if os.path.exists(doc_path):
        shutil.rmtree(doc_path)
    return {"status": "success"}


@app.get("/api/sessions/{session_id}/documents/{filename}")
def get_document(session_id: str, filename: str):
    _validate_session(session_id)
    _, docs_dir = resolve_dirs()
    session_dir = safe_join(docs_dir, session_id)
    safe_filename = os.path.basename(filename)
    file_path = safe_join(session_dir, safe_filename)
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
        print(f"[DOC] Removed file '{safe_filename}' from session '{session_id}'")

    db_path = safe_join(db_dir, session_id, "chromadb")
    if os.path.exists(db_path):
        try:
            vectorstore = get_vectorstore(db_path, _DummyEmbeddings(), session_id)
            delete_vectors_for_file(vectorstore, safe_filename)
        except Exception as e:
            print(f"[RAG] Error removing vectors for '{safe_filename}': {e}")
            traceback.print_exc()

    remaining_files = []
    if os.path.exists(session_dir):
        remaining_files = [
            f for f in os.listdir(session_dir)
            if os.path.isfile(os.path.join(session_dir, f))
        ]

    if not remaining_files and os.path.exists(db_path):
        shutil.rmtree(db_path)
        print(f"[RAG] All documents removed — wiped ChromaDB for session '{session_id}'")

    return {"status": "success", "remaining_documents": remaining_files}


@app.get("/")
def get_ui():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found alongside backend.py</h1>")


if __name__ == "__main__":
    import uvicorn
    print("Starting Local RAG Application...")
    print("Open http://localhost:8000 in your browser.")
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
