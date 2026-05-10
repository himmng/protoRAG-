# protoRAG+

A lightweight RAG chat app for your own documents and your own LLM. Three deployment shapes share the same UI:

| Mode | Where docs/embeddings live | Where the LLM call comes from | Best for |
|------|----------------------------|-------------------------------|----------|
| **B — Local-first** *(recommended)* | Your machine | Your local backend → your local Ollama | Private use; one user, full local control |
| **A — Cloud-shared** | Your hosted backend | Hosted backend → user's tunneled Ollama | Multiple users sharing one frontend |
| **C — Browser-only** | This browser (IndexedDB) | The browser itself → your local Ollama | Zero install on the server; static-host deploy |

The same FastAPI backend (`backend.py`) serves modes A and B. Mode C is a separate file (`index-static.html`) that runs entirely in the browser — no server.

---

## Mode B — Local-first (recommended)

Everything stays on your machine. The frontend can be opened from disk, served locally, or hosted somewhere static (e.g. Netlify) — it talks to a backend running on your localhost.

### With Docker

```bash
docker run -d --name protorag \
  -p 8000:8000 \
  -v ~/protorag-data:/app/data \
  ghcr.io/himmng/protorag-:latest
```

Then open `http://localhost:8000`. In **Settings**:

- **Remote URL** → leave blank (same origin) or `http://localhost:8000` if you opened the UI from a different host
- **LLM URL** → `http://localhost:11434` (Ollama)
- **Provider** → Ollama, fill in your model names

### Without Docker

```bash
pip install -r requirements.txt
python backend.py    # serves the UI at http://localhost:8000
```

The Ollama server must be running separately:

```bash
ollama pull gemma3
ollama serve
```

### Stop / wipe

```bash
docker stop protorag && docker rm protorag    # stop the container
rm -rf ~/protorag-data                        # wipe all sessions and embeddings
```

---

## Mode A — Cloud backend + tunneled Ollama

For a publicly hosted backend that several users share. **Documents and embeddings live on the cloud backend, not the user's machine** — pick this only if you're OK with that trade-off.

### 1. Deploy the backend

The repo includes [render.yaml](render.yaml) for a one-click Render deploy on the **free plan**:

1. Push the repo to GitHub.
2. On Render: **New → Blueprint** → select the repo. Render reads `render.yaml` and generates a `PROTORAG_API_TOKEN`.
3. Copy the generated token from the env-vars page. Without it the public backend is open to anyone.

**Free-tier caveats:** Render's free plan has **no persistent disk**, so `/app/data` (sessions, embeddings, uploads) is wiped on every restart/redeploy. The service also **spins down after ~15 min of inactivity** and cold-starts on the next request. Treat it as a demo deployment — for persistence, either upgrade to `plan: starter` and re-add the `disk:` block in [render.yaml](render.yaml) (5 GB at `/app/data`), or use **Mode B**.

The same Dockerfile works on Railway, Fly.io, etc. Just set `PROTORAG_API_TOKEN` to a long random string.

### 2. Tunnel each user's local Ollama

Each end-user picks one:

```bash
cloudflared tunnel --url http://localhost:11434     # → https://*.trycloudflare.com
tailscale serve 11434                               # → Tailscale magic-DNS URL
ngrok http 11434                                    # → https://*.ngrok.app
```

### 3. Configure the frontend

Open the deployed site (or any host running the same `index.html`) → **Settings**:

- **Remote URL** → your backend (e.g. `https://protorag.onrender.com`)
- **Backend Token** → the `PROTORAG_API_TOKEN` value from step 1
- **LLM URL** → the user's tunnel URL from step 2

Click **Test** next to Remote URL — green dot = backend reachable.

The token gates the backend; it does **not** gate the LLM tunnel. If you don't want strangers using your Ollama, also set `OLLAMA_HOST=127.0.0.1` and rely on the tunnel ACL.

---

## Mode C — Browser-only (no backend)

A pure static site. Embeddings, retrieval, and chat all run in the browser; the LLM call goes browser-direct to local Ollama.

### 1. Allow CORS on Ollama

The browser-direct call is cross-origin, so Ollama needs to opt in:

```bash
OLLAMA_ORIGINS='*' ollama serve
```

- macOS GUI install: `launchctl setenv OLLAMA_ORIGINS '*'`, then restart Ollama.
- Linux systemd user service: add `Environment="OLLAMA_ORIGINS=*"` to `~/.config/systemd/user/ollama.service` and reload.

### 2. Open the page

Either of:

```bash
python3 -m http.server 8080         # then open http://localhost:8080/index-static.html
```

Or drop `index-static.html` into Netlify drag-drop, GitHub Pages, or any static host.

### 3. Configure Settings

- **LLM URL** → `http://localhost:11434`
- **Provider** → Ollama
- **LLM Model** → e.g. `gemma3`
- The "Embedding Model" field is ignored — Mode C uses `Xenova/all-MiniLM-L6-v2` (~22 MB, downloaded once and cached).

### Limits

- Only Ollama / LM Studio / OpenAI-compatible servers reachable from the browser.
- File formats: text formats, PDF, DOCX. `.xlsx`/`.pptx`/`.doc` are not supported here — use Mode A or B for those.
- Storage is per-browser. Switching browsers, clearing site data, or using private mode wipes everything.

---

## Settings reference (the modal in the UI)

| Field | Modes A/B | Mode C |
|-------|-----------|--------|
| **Remote URL** | URL of the FastAPI backend, blank for same-origin | not shown |
| **Backend Token** | matches `PROTORAG_API_TOKEN` env var, if set | not shown |
| **Data Storage Path** | path on the backend host (default `./data`) | not shown |
| **LLM URL** | LLM endpoint reachable *from the backend* | LLM endpoint reachable *from this browser* |
| **Provider** | ollama / lmstudio / openai / litellm / anthropic / custom | ollama / lmstudio / custom |
| **API Key** | sent to the LLM provider | sent to the local LLM (don't paste real cloud keys here) |
| **LLM Model** | the chat model name | same |
| **Embedding Model** | the embedding model name | ignored — uses `Xenova/all-MiniLM-L6-v2` |

---

## API overview (Modes A and B)

| Method | Path | Purpose |
|--------|------|---------|
| `GET`    | `/api/health` | unauthed liveness probe used by the **Test** button |
| `POST`   | `/api/upload` | upload, chunk, embed, and index a document into a session |
| `POST`   | `/api/chat` | stream a chat response, with retrieval if the session has documents |
| `GET`    | `/api/sessions` | list sessions (preview + RAG flag) |
| `GET`    | `/api/sessions/{id}` | get chat history and document list for a session |
| `DELETE` | `/api/sessions/{id}` | delete a session and its data |
| `GET`    | `/api/sessions/{id}/documents/{filename}` | download a stored document |
| `GET`    | `/api/sessions/{id}/documents/{filename}/preview` | render office formats via LibreOffice |
| `DELETE` | `/api/sessions/{id}/documents/{filename}` | delete a document and prune its vectors |
| `GET`    | `/` | serve `index.html` |

When `PROTORAG_API_TOKEN` is set, every `/api/*` route except `/api/health` requires the `X-API-Token` header. For `<img>`/`<iframe>`/download-anchor URLs (which can't carry headers), the backend also accepts `?token=` on GETs. CORS preflights are always allowed; a Private-Network-Access middleware lets HTTPS pages call `http://localhost:8000` without browser flags.

---

## Data layout (Modes A and B)

Default base directory: `./data` (override with the `DEFAULT_DATA_DIR` env var, or per-request via the **Data Storage Path** field).

```
data/
├── db/session/<session_id>/
│   ├── chromadb/          # ChromaDB collection for this session
│   ├── embed_meta.json    # embedding-model name (mismatch detection)
│   └── history.json       # chat transcript
└── documents/session/<session_id>/
    └── <uploaded files>
```

In Mode C, the equivalent lives in IndexedDB (database `protorag`, stores `sessions` / `documents` / `chunks` / `messages`).

---

## Environment variables (server modes)

| Variable | Default | Effect |
|----------|---------|--------|
| `DEFAULT_DATA_DIR` | `./data` | Base directory for sessions, documents, vectors |
| `PROTORAG_API_TOKEN` | unset | If set, all `/api/*` routes (except `/api/health`) require `X-API-Token` |

---

## Development

```bash
# Auto-reload backend
uvicorn backend:app --host 0.0.0.0 --port 8000 --reload

# Smoke-test the static build
python3 -m http.server 8080
# → http://localhost:8080/index-static.html
```

The Docker image is published by [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml) on every push to `main` and on `v*` tags. Multi-arch (`linux/amd64` + `linux/arm64`) → `ghcr.io/himmng/protorag-:latest`.
