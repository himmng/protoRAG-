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

# App Initialization
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

# ---------------------------------------------------------------------------
# Provider URL normalisation & Standardisation
# ---------------------------------------------------------------------------
def normalise_base_url(provider: str, base_url: str) -> str:
    """
    Ensures URLs are compatible with standard OpenAI client expectations.
    Rules:
    1. Strip trailing slashes.
    2. If provider is Ollama/LMStudio and /v1 is missing, append it.
    3. If URL already has /v1, keep it (prevent double appending).
    """
    url = base_url.rstrip("/")
    if not url:
        return ""
    
    if url.endswith("/v1"):
        return url
        
    provider_lower = provider.lower()
    # Ollama and LM Studio expose OpenAI-compat endpoints at /v1
    if provider_lower in ("ollama", "lmstudio"):
        return f"{url}/v1"
        
    # For LiteLLM, OpenAI, or Custom, we use the URL exactly as provided
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

# ---------------------------------------------------------------------------
# Unified LangChain Tooling (OpenAI API Compatible)
# ---------------------------------------------------------------------------
def get_embeddings(config: ChatConfig):
    base_url = normalise_base_url(config.provider, config.base_url)
    # Use 'dummy' for local providers that don't check keys, or the user's key for OpenAI/LiteLLM
    api_key = config.api_key if config.api_key and config.api_key.strip() not in ("", "none", "None") else "ollama"

    return OpenAIEmbeddings(
        model=config.embedding_model,
        openai_api_base=base_url,
        openai_api_key=api_key,
        check_embedding_ctx_length=False, # Required for many local providers
    )

def get_llm(config: ChatConfig):
    base_url = normalise_base_url(config.provider, config.base_url)
    api_key = config.api_key if config.api_key and config.api_key.strip() not in ("", "none", "None") else "ollama"

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

# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
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
            provider=provider, base_url=base_url, api_key=api_key,
            model_name=model_name, embedding_model=embedding_model,
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
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)

        db_path = safe_join(db_dir, session_id, "chromadb")
        embeddings = get_embeddings(config)
        vectorstore = Chroma(
            persist_directory=db_path,
            embedding_function=embeddings,
            collection_name=f"col_{session_id}",
        )
        vectorstore.add_documents(splits)

        return {"status": "success", "message": f"Uploaded and indexed {filename}."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

@app.post("/api/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id
    query = request.message
    config = request.config

    _, db_dir, _ = resolve_dirs(config.data_dir)
    db_path = os.path.join(db_dir, session_id, "chromadb")
    context = ""
    
    if os.path.exists(db_path):
        try:
            embeddings = get_embeddings(config)
            vectorstore = Chroma(
                persist_directory=db_path,
                embedding_function=embeddings,
                collection_name=f"col_{session_id}",
            )
            retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
            docs = retriever.invoke(query)
            context = "\n\n".join([d.page_content for d in docs])
        except Exception as e:
            print(f"Retrieval Error: {e}")

    history = load_history(session_id, db_dir)
    sys_prompt = "You are a helpful and intelligent AI assistant."
    if context:
        sys_prompt += f"\n\nContext:\n{context}\n\nUse the context provided to answer the user query."

    messages = [SystemMessage(content=sys_prompt)]
    for msg in history[-10:]:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user": messages.append(HumanMessage(content=content))
        elif role == "assistant": messages.append(AIMessage(content=content))

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
            has_docs = os.path.exists(doc_path) and len(os.listdir(doc_path)) > 0
            
            preview, timestamp = "New Chat", 0
            if os.path.exists(hist_path):
                try:
                    with open(hist_path, "r") as f:
                        hist = json.load(f)
                        if hist:
                            preview = hist[-1]["content"][:40] + "..."
                    timestamp = os.path.getmtime(hist_path)
                except: pass
                
            sessions.append({"id": sid, "preview": preview, "timestamp": timestamp, "is_rag": has_docs})
    
    sessions.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"sessions": sessions}

@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, data_dir: Optional[str] = Query(default=None)):
    _, db_dir, docs_dir = resolve_dirs(data_dir)
    history = load_history(session_id, db_dir)
    doc_path = os.path.join(docs_dir, session_id)
    docs = os.listdir(doc_path) if os.path.exists(doc_path) else []
    return {"history": history, "documents": docs}

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, data_dir: Optional[str] = Query(default=None)):
    _, db_dir, docs_dir = resolve_dirs(data_dir)
    for p in [os.path.join(db_dir, session_id), os.path.join(docs_dir, session_id)]:
        if os.path.exists(p): shutil.rmtree(p)
    return {"status": "success"}

@app.get("/api/sessions/{session_id}/documents/{filename}")
def get_document(session_id: str, filename: str, data_dir: Optional[str] = Query(default=None)):
    _, _, docs_dir = resolve_dirs(data_dir)
    file_path = safe_join(docs_dir, session_id, filename)
    if os.path.exists(file_path): return FileResponse(file_path)
    raise HTTPException(status_code=404)

@app.get("/")
def get_ui():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found</h1>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)