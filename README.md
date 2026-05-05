Here is a simple, self-contained `README.md` you can use for this codebase:

```markdown
# protoRAG+

protoRAG+ is a lightweight, local-first RAG (Retrieval-Augmented Generation) chat application.  
It lets you upload documents, index them locally with Chroma, and chat with an LLM using those documents as context.  
The UI is served from a static `index.html`, and the backend is a FastAPI app in `backend.py`.

---

## Features

- Local document storage and retrieval using Chroma
- PDF and text document support
- Session-based chat history stored on disk
- Simple FastAPI backend with streaming responses
- Pluggable LLM provider (e.g. Ollama-compatible / OpenAI-compatible APIs)
- Docker image for easy deployment

---

## Requirements (non-Docker)

- Python 3.10+
- pip
- An LLM endpoint compatible with the OpenAI API (e.g. Ollama with its `/v1` endpoint, OpenAI, or similar)

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Running Locally (without Docker)

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Start the backend:

   ```bash
   python backend.py
   ```

3. Open the UI:

   - The backend serves `index.html` from the project root at `http://localhost:8000/`.
   - Ensure `index.html` is present alongside `backend.py`.

4. Configure the UI (in the Settings modal):

   - **Storage Path (Local)**: `./data` (or another directory)
   - **Provider**: `ollama` or the appropriate provider name
   - **Base URL**: the base URL of your LLM endpoint  
     - For Ollama, typically: `http://localhost:11434/v1`
   - **API Key**: as required by your provider (for local Ollama, usually a dummy value is fine)
   - **LLM Model**: name of the chat model (e.g. `llama3`, `gpt-4o`, etc.)
   - **Embedding Model**: name of the embedding model

By default, data is stored under `./data` (configurable via `DEFAULT_DATA_DIR` env var).

---

## Running with Docker

A separate README (`README-docker.md`) contains details. The basic flow:

1. Build the image:

   ```bash
   docker build -t protorag:latest .
   ```

2. Run the container with a local data volume:

   ```bash
   docker run \
     --name protorag \
     -p 127.0.0.1:8000:8000 \
     -v /path/on/host:/app/data \
     protorag:latest
   ```

   - Inside the container, the app listens on `http://0.0.0.0:8000`.
   - All documents, Chroma DB files, and histories live under `/app/data` in the container (mapped to `/path/on/host`).

3. Inside the UI Settings (when running in Docker):

   - **Storage Path (Local)**: `./data`
   - Other fields as described in the local section, using your LLM endpoint (can be remote).

---

## API Overview

The FastAPI backend exposes a few main endpoints:

- `POST /api/upload`  
  Upload and index a document for a given session.

- `POST /api/chat`  
  Stream chat responses for a session, optionally using retrieved document context.

- `GET /api/sessions`  
  List existing sessions (with preview and whether they have RAG docs).

- `GET /api/sessions/{session_id}`  
  Get chat history and document list for a session.

- `DELETE /api/sessions/{session_id}`  
  Delete a session and its data.

- `GET /api/sessions/{session_id}/documents/{filename}`  
  Download a stored document.

- `POST /api/sessions/{session_id}/documents/{filename}/delete`  
  Delete a document and rebuild the RAG index for remaining docs.

- `GET /`  
  Serve the `index.html` UI from the project root.

---

## Data Storage

- Default base directory: `./data` (override with `DEFAULT_DATA_DIR` environment variable).
- Layout (per session):
  - `data/db/session/<session_id>/` – Chroma DB and `history.json`
  - `data/documents/session/<session_id>/` – uploaded documents

---

## Development

To run the FastAPI app via `uvicorn` directly:

```bash
uvicorn backend:app --host 0.0.0.0 --port 8000 --reload
```

Ensure `index.html` is present in the project root so the UI is served at `/`.

---
