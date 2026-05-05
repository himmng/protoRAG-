import os
import json
import shutil
import traceback
from typing import List

from fastapi import FastAPI, UploadFile, File, Form, Request
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

# Strict session isolation paths
DATA_DIR = "./data"
DB_DIR = os.path.join(DATA_DIR, "db", "session")
DOCS_DIR = os.path.join(DATA_DIR, "documents", "session")

os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

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
    base_url = config.base_url.rstrip("/")
    if config.provider.lower() == "ollama" and not base_url.endswith("/v1"):
        base_url += "/v1"
        
    api_key = config.api_key if config.api_key else "dummy"
    
    return OpenAIEmbeddings(
        model=config.embedding_model,
        openai_api_base=base_url,
        openai_api_key=api_key,
        check_embedding_ctx_length=False
    )

def get_llm(config: ChatConfig):
    base_url = config.base_url.rstrip("/")
    if config.provider.lower() == "ollama" and not base_url.endswith("/v1"):
        base_url += "/v1"
        
    api_key = config.api_key if config.api_key else "dummy"
    
    return ChatOpenAI(
        model=config.model_name,
        openai_api_base=base_url,
        openai_api_key=api_key,
        streaming=True
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

def load_history(session_id: str):
    hist_path = os.path.join(DB_DIR, session_id, "history.json")
    if os.path.exists(hist_path):
        with open(hist_path, "r") as f:
            return json.load(f)
    return []

def save_history(session_id: str, history: list):
    hist_path = os.path.join(DB_DIR, session_id, "history.json")
    os.makedirs(os.path.dirname(hist_path), exist_ok=True)
    with open(hist_path, "w") as f:
        json.dump(history, f)


@app.post("/api/upload")
async def upload_document(
    session_id: str = Form(...),
    provider: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(...),
    model_name: str = Form(...),
    embedding_model: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        config = ChatConfig(
            provider=provider, base_url=base_url, api_key=api_key, 
            model_name=model_name, embedding_model=embedding_model
        )
        
        # 1. Save original document to isolated session directory
        session_doc_path = os.path.join(DOCS_DIR, session_id)
        os.makedirs(session_doc_path, exist_ok=True)
        file_path = os.path.join(session_doc_path, file.filename)
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
            
        # 2. Extract and Split
        docs = load_document(file_path, file.filename)
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)
        
        # 3. Create/Update isolated ChromaDB for this specific session
        db_path = os.path.join(DB_DIR, session_id, "chromadb")
        embeddings = get_embeddings(config)
        vectorstore = Chroma(
            persist_directory=db_path,
            embedding_function=embeddings,
            collection_name=f"col_{session_id}"
        )
        vectorstore.add_documents(splits)
        
        return {"status": "success", "message": f"Uploaded and indexed {file.filename}."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id
    query = request.message
    config = request.config
    
    # Check if a vector DB exists for this session to inject RAG context
    db_path = os.path.join(DB_DIR, session_id, "chromadb")
    context = ""
    if os.path.exists(db_path):
        try:
            embeddings = get_embeddings(config)
            vectorstore = Chroma(
                persist_directory=db_path,
                embedding_function=embeddings,
                collection_name=f"col_{session_id}"
            )
            retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
            docs = retriever.invoke(query)
            context = "\n\n".join([d.page_content for d in docs])
        except Exception as e:
            print(f"Retrieval Error: {e}")
            
    history = load_history(session_id)
    
    sys_prompt = "You are a helpful and intelligent AI assistant."
    if context:
        sys_prompt += (
            "\n\nContext information from the user's local documents is below.\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n"
            "Given the context information and no prior knowledge, answer the user's query."
        )
    
    messages = [SystemMessage(content=sys_prompt)]
    
    # Cap history to prevent context overflow (last 10 interactions)
    for msg in history[-10:]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
            
    messages.append(HumanMessage(content=query))
    llm = get_llm(config)
    
    async def generate():
        full_response = ""
        try:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_response += chunk.content
                    # SSE format
                    yield f"data: {json.dumps({'content': chunk.content})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'content': f'\\n\\n**Connection Error:** {str(e)}'})}\n\n"
        
        # Save updated history
        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": full_response})
        save_history(session_id, history)
        
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/sessions")
def list_sessions():
    sessions = []
    if os.path.exists(DB_DIR):
        for sid in os.listdir(DB_DIR):
            hist_path = os.path.join(DB_DIR, sid, "history.json")
            doc_path = os.path.join(DOCS_DIR, sid)
            
            # Logic: If directory has files, it's a RAG session
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
                            preview = hist[-2]["content"][:35] + "..." if len(hist)>1 else hist[0]["content"][:35] + "..."
                    timestamp = os.path.getmtime(hist_path)
                except:
                    pass
            sessions.append({
                "id": sid, 
                "preview": preview, 
                "timestamp": timestamp,
                "is_rag": has_docs
            })
    
    sessions.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    history = load_history(session_id)
    doc_path = os.path.join(DOCS_DIR, session_id)
    docs = []
    if os.path.exists(doc_path):
        docs = os.listdir(doc_path)
    return {"history": history, "documents": docs}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    db_path = os.path.join(DB_DIR, session_id)
    doc_path = os.path.join(DOCS_DIR, session_id)
    if os.path.exists(db_path): shutil.rmtree(db_path)
    if os.path.exists(doc_path): shutil.rmtree(doc_path)
    return {"status": "success"}

@app.get("/api/sessions/{session_id}/documents/{filename}")
def get_document(session_id: str, filename: str):
    file_path = os.path.join(DOCS_DIR, session_id, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"status": "error", "message": "File not found"}

@app.post("/api/sessions/{session_id}/documents/{filename}/delete")
async def delete_document(session_id: str, filename: str, config: ChatConfig):
    # 1. Delete the specific document
    file_path = os.path.join(DOCS_DIR, session_id, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        
    # 2. Wipe the existing vector store for this session
    db_path = os.path.join(DB_DIR, session_id, "chromadb")
    if os.path.exists(db_path):
        shutil.rmtree(db_path)
        
    # 3. Rebuild the vector store with any remaining documents
    doc_path = os.path.join(DOCS_DIR, session_id)
    if os.path.exists(doc_path):
        remaining_files = os.listdir(doc_path)
        if remaining_files:
            embeddings = get_embeddings(config)
            vectorstore = Chroma(
                persist_directory=db_path,
                embedding_function=embeddings,
                collection_name=f"col_{session_id}"
            )
            for f in remaining_files:
                fp = os.path.join(doc_path, f)
                docs = load_document(fp, f)
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
                splits = text_splitter.split_documents(docs)
                vectorstore.add_documents(splits)
                
    return {"status": "success"}

# Mount Frontend UI directly on the root
@app.get("/")
def get_ui():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found alongside backend.py</h1>")


if __name__ == "__main__":
    import uvicorn
    # Automatically run on standard port 8000 when executed as a script
    print("Starting Local RAG Application...")
    print("Open http://localhost:8000 in your browser.")
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)