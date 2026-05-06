import os
import json
import shutil
import traceback
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
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

DEFAULT_DATA_DIR = os.environ.get("DEFAULT_DATA_DIR", "./data")
MAX_HISTORY_ENTRIES = 200


def normalise_base_url(provider: str, base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url
    provider_lower = provider.lower()
    if provider_lower in ("ollama", "lmstudio"):
        return url + "/v1"
    return url


def resolve_dirs(data_dir: Optional[str]):
    base = data_dir or DEFAULT_DATA_DIR
    db_dir = os.path.join(base, "db", "session")
    docs_dir = os.path.join(base, "documents", "session")
    os.makedirs(db_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)
    return base, db_dir, docs_dir


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
    data_dir: Optional[str] = None


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
    trimmed_history = history[-MAX_HISTORY_ENTRIES:]
    hist_path = os.path.join(db_dir, session_id, "history.json")
    os.makedirs(os.path.dirname(hist_path), exist_ok=True)
    with open(hist_path, "w") as f:
        json.dump(trimmed_history, f)


@app.post("/api/upload")
async def upload_document(
    session_id: str = Form(...),
    provider: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(...),
    model_name: str = Form(...),
    embedding_model: str = Form(...),
    data_dir: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
):
    try:
        config = ChatConfig(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            embedding_model=embedding_model,
            data_dir=data_dir,
        )

        _, db_dir, docs_dir = resolve_dirs(config.data_dir)

        session_doc_path = safe_join(docs_dir, session_id)
        os.makedirs(session_doc_path, exist_ok=True)

        filename = os.path.basename(file.filename)
        file_path = safe_join(session_doc_path, filename)

        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        docs = load_document(file_path, filename)
        text_splitter = get_text_splitter()
        splits = text_splitter.split_documents(docs)

        db_path = safe_join(db_dir, session_id, "chromadb")
        embeddings = get_embeddings(config)
        vectorstore = Chroma(
            persist_directory=db_path,
            embedding_function=embeddings,
            collection_name=f"col_{session_id}",
        )
        vectorstore.add_documents(splits)

        # ── Save embedding model metadata so retrieval can detect mismatches ──
        meta_path = os.path.join(db_dir, session_id, "embed_meta.json")
        with open(meta_path, "w") as f:
            json.dump({"embedding_model": config.embedding_model}, f)

        return {"status": "success", "message": f"Uploaded and indexed {filename}."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id
    query = request.message
    config = request.config

    _, db_dir, docs_dir = resolve_dirs(config.data_dir)

    db_path = os.path.join(db_dir, session_id, "chromadb")
    context = ""
    retrieval_warning = ""

    if os.path.exists(db_path):
        try:
            # ── Detect embedding model mismatch before querying Chroma ──
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
            vectorstore = Chroma(
                persist_directory=db_path,
                embedding_function=embeddings,
                collection_name=f"col_{session_id}",
            )
            retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
            docs = retriever.invoke(query)
            context = "\n\n".join([d.page_content for d in docs])
            print(f"[RAG] Retrieved {len(docs)} chunks for session {session_id}")
        except Exception as e:
            print(f"Retrieval Error: {e}")
            traceback.print_exc()
            if not retrieval_warning:
                retrieval_warning = f"\n\n> ⚠️ **RAG retrieval failed**: {str(e)}"

    history = load_history(session_id, db_dir)

    sys_prompt = "You are a helpful and intelligent AI assistant."
    messages = [SystemMessage(content=sys_prompt)]

    # Load history
    for msg in history[-10:]:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg.get("content", "")))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg.get("content", "")))

    # ── FIX: Inject context directly into the final HumanMessage instead of SystemMessage ──
    # This prevents the LLM from ignoring the context due to recency bias or lack of System prompt support.
    if context:
        augmented_query = (
            "Context information from the user's local documents is below.\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n"
            "Given the context information and no prior knowledge, answer the user's query.\n\n"
            f"User Query: {query}"
        )
        messages.append(HumanMessage(content=augmented_query))
    else:
        messages.append(HumanMessage(content=query))
        
    llm = get_llm(config)

    async def generate():
        full_response = ""
        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_response += chunk.content
                    yield f"data: {json.dumps({'content': chunk.content})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'content': f'\\n\\n**Connection Error:** {str(e)}'})}\n\n"

        # ── Append retrieval warning to response so user sees it in chat ──
        if retrieval_warning:
            full_response += retrieval_warning
            yield f"data: {json.dumps({'content': retrieval_warning})}\n\n"

        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": full_response})
        save_history(session_id, history, db_dir)

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/sessions")
def list_sessions(data_dir: Optional[str] = Query(default=None)):
    _, db_dir, docs_dir = resolve_dirs(data_dir)
    sessions = []
    if os.path.exists(db_dir):
        for sid in os.listdir(db_dir):
            hist_path = os.path.join(db_dir, sid, "history.json")
            doc_path = os.path.join(docs_dir, sid)

            has_docs = False
            if os.path.exists(doc_path):
                files = os.listdir(doc_path)
                has_docs = len(files) > 0

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
            sessions.append(
                {
                    "id": sid,
                    "preview": preview,
                    "timestamp": timestamp,
                    "is_rag": has_docs,
                }
            )

    sessions.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, data_dir: Optional[str] = Query(default=None)):
    _, db_dir, docs_dir = resolve_dirs(data_dir)
    history = load_history(session_id, db_dir)

    doc_path = os.path.join(docs_dir, session_id)
    docs = []
    if os.path.exists(doc_path):
        docs = os.listdir(doc_path)
    return {"history": history, "documents": docs}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, data_dir: Optional[str] = Query(default=None)):
    _, db_dir, docs_dir = resolve_dirs(data_dir)
    db_path = os.path.join(db_dir, session_id)
    doc_path = os.path.join(docs_dir, session_id)
    if os.path.exists(db_path):
        shutil.rmtree(db_path)
    if os.path.exists(doc_path):
        shutil.rmtree(doc_path)
    return {"status": "success"}


@app.get("/api/sessions/{session_id}/documents/{filename}")
def get_document(
    session_id: str,
    filename: str,
    data_dir: Optional[str] = Query(default=None),
):
    _, _, docs_dir = resolve_dirs(data_dir)
    session_dir = safe_join(docs_dir, session_id)
    safe_filename = os.path.basename(filename)
    file_path = safe_join(session_dir, safe_filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)


@app.post("/api/sessions/{session_id}/documents/{filename}/delete")
async def delete_document(session_id: str, filename: str, config: ChatConfig):
    _, db_dir, docs_dir = resolve_dirs(config.data_dir)

    session_dir = safe_join(docs_dir, session_id)
    safe_filename = os.path.basename(filename)
    file_path = safe_join(session_dir, safe_filename)

    if os.path.exists(file_path):
        os.remove(file_path)

    db_path = safe_join(db_dir, session_id, "chromadb")
    if os.path.exists(db_path):
        shutil.rmtree(db_path)

    if os.path.exists(session_dir):
        remaining_files = os.listdir(session_dir)
        if remaining_files:
            embeddings = get_embeddings(config)
            vectorstore = Chroma(
                persist_directory=db_path,
                embedding_function=embeddings,
                collection_name=f"col_{session_id}",
            )
            for f in remaining_files:
                fp = safe_join(session_dir, f)
                docs = load_document(fp, f)
                text_splitter = get_text_splitter()
                splits = text_splitter.split_documents(docs)
                vectorstore.add_documents(splits)

    return {"status": "success"}


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