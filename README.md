# protoRAG+

protoRAG+ is a lightweight, local-first RAG (Retrieval-Augmented Generation) chat application.
It lets you upload documents, index them locally with Chroma, and chat with an LLM using those documents as context.
The UI is served from a static `index.html`, and the backend is a FastAPI app in the `backend/` package.

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
   python -m backend
   ```

3. Open the UI:

   - The backend serves `index.html` from the project root at `http://localhost:8000/`.
   - Ensure `index.html` is present alongside the `backend/` package.

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

## Secure LLM Inference over Tailscale

You can expose your LLM server (e.g. Ollama or an OpenAI-compatible proxy) only on your Tailscale tailnet and point protoRAG+ at that private address.

1. Install and log in to Tailscale on the machine running your LLM server.
2. Run your LLM API bound to the Tailscale interface or localhost, for example for Ollama:

   ```bash
   OLLAMA_HOST=127.0.0.1:11434 ollama serve
   ```

3. From a Tailscale-connected client machine, find the server’s Tailscale IP or MagicDNS name, e.g. `100.x.y.z` or `llm-server.tailnet-name.ts.net`.
4. In the protoRAG+ Settings modal on the client:

   - **Provider**: `ollama` (or matching your server)
   - **Base URL**: `http://llm-server.tailnet-name.ts.net:11434/v1` (or `http://100.x.y.z:11434/v1`)
   - **API Key**: leave blank or dummy for Ollama, or set as required by your proxy.

Only devices on your Tailscale tailnet will be able to reach the LLM endpoint, giving you a simple private network for secure inference.

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
- A small SQLite user store sits at `./data/users.db` (users + auth sessions).
- RAG data is per user:
  - `data/users/<user_id>/db/session/<session_id>/` – Chroma DB and `history.json`
  - `data/users/<user_id>/documents/session/<session_id>/` – uploaded documents
- First visit issues a `pr_guest` cookie (HttpOnly, 1y TTL) so anonymous use
  still works without sign-in. Each guest gets their own `<user_id>` folder.
- Pre-existing flat `data/db/session/...` directories from earlier versions
  are not auto-migrated. Re-upload to bring them into the new per-user layout.

---

## Authentication (optional)

Google sign-in is opt-in via an env var. With it set, the sidebar shows a
"Sign in with Google" button; users get their own isolated RAG storage. Their
existing guest sessions are merged into the Google account on first login.

```bash
export GOOGLE_CLIENT_ID="123…apps.googleusercontent.com"
python -m backend
```

Set up a Google Cloud OAuth 2.0 Client ID (Web application) and add the
backend's origin to the **Authorized JavaScript origins** list. Without
`GOOGLE_CLIENT_ID`, sign-in is hidden and all users stay anonymous.

Additional env vars:
- `PROTORAG_COOKIE_SECURE=1` — required when serving behind HTTPS (Render,
  Cloudflare, etc.). Disabled on plain `http://localhost` by default.
- `PROTORAG_CORS_ORIGINS=https://myfrontend.netlify.app,https://...` —
  comma-separated allowlist for cross-origin frontends. When set, the backend
  emits `Access-Control-Allow-Credentials: true` so auth cookies traverse the
  origin boundary. Required for Netlify-style deploys.

---

## Development

To run the FastAPI app via `uvicorn` directly:

```bash
uvicorn backend:app --host 0.0.0.0 --port 8000 --reload
```

Ensure `index.html` is present in the project root so the UI is served at `/`.

---

## Use the live Netlify demo with a fully local backend

If you don't want to expose your backend at all — keep it on `127.0.0.1` —
the live demo at <https://protorag.netlify.app> can talk straight to a
locally-running container. Only your **Ollama** model needs to be reachable
(it can also stay local, or be tunneled via tailscale / cloudflared if it
lives on a different machine).

```bash
docker compose -f docker-compose.local.yml up -d --build
```

That single command:

- Builds the image locally from the repo `Dockerfile` (tagged
  `protorag-local:latest`). The `+` in the repo name can't appear in a Docker
  image reference, so the image is built rather than pulled from GHCR.
- Binds port `8000` to `127.0.0.1` only — the backend is never on your LAN.
- Pre-sets `PROTORAG_CORS_ORIGINS=https://protorag.netlify.app` so cross-origin
  fetches from the deployed site succeed.
- Mounts `~/protorag_storage` into the container as `/data`; your vector DB,
  documents, and `users.db` live on your disk.

Then in your browser:

1. Open <https://protorag.netlify.app>.
2. Click **Continue as guest** (or sign in with Google if you have
   `GOOGLE_CLIENT_ID` set in the compose env).
3. Open **Settings** and set:
   - **Backend URL** → `http://localhost:8000`. Click **Test** — the dot
     should turn green.
   - **Base URL** → your Ollama endpoint, either `http://localhost:11434`
     for a same-machine Ollama, or a tailscale / cloudflared URL if Ollama
     runs elsewhere.
   - **Provider**, **LLM Model**, **Embedding Model** → as you'd configure
     them anywhere else.
4. Upload documents (or click the folder icon to ingest a whole directory)
   and chat.

### How auth crosses the origin boundary

In this layout, Netlify is HTTPS and your backend is plain
`http://localhost`. Browsers treat `SameSite=None` cookies on plain-http
inconsistently, so the backend now also issues a **bearer token** in the
JSON body of `/api/auth/guest` and `/api/auth/google`. The frontend stores
it in `localStorage` and sends it as `Authorization: Bearer …` on every
fetch — no cookie quirks. Same-origin deployments are unaffected: cookies
still work, the bearer header is just additive.

### How browsers permit HTTPS → http://localhost

Chrome's [Private Network Access](https://wicg.github.io/private-network-access/)
spec requires an explicit opt-in from the backend when an HTTPS page hits a
private IP. The backend's PNA middleware
([backend/app.py](backend/app.py)) handles this preflight automatically;
no browser flags needed.

---

## One-click "Connect with backend" (bundled default)

The auth gate at <https://protorag.netlify.app> shows a **Connect with backend**
button as step 1, above the Google / guest sign-in options. It points at a
backend baked into the frontend so users don't have to paste a URL. The default
is defined in [`static/js/config.js`](static/js/config.js) and can be overridden
at runtime with `window.PROTORAG_DEFAULT_BACKEND_URL`:

```js
export const DEFAULT_BACKEND_URL =
    (typeof window !== 'undefined' && window.PROTORAG_DEFAULT_BACKEND_URL) ||
    'https://my-ubuntu.tail8e3f2b.ts.net:8443';
```

Clicking the button applies the bundled defaults (provider `ollama`, LLM model
`gemma-4-e4b:latest`, embedding model `embeddinggemma:latest`), probes
`/api/health`, and shows a green/red result. The gate is shown on **every
visit** so the backend + identity are re-confirmed each time.

> The frontend talks to the **protoRAG FastAPI backend**, which in turn talks to
> Ollama server-side — the browser never hits Ollama directly. So the default
> URL must point at the FastAPI backend, not at Ollama's `:11434`.

### Why `:8443` and not `:443`

The Netlify page is HTTPS, so the backend must be HTTPS with a
**browser-trusted** cert — a plain `http://…` backend is blocked as mixed
content, and a self-signed cert is rejected. `tailscale serve` issues a real
cert automatically. Port `443` is often already in use on a host (e.g. by
Nextcloud), so this setup uses `8443`.

### Server-side setup (run on the backend host)

These steps run on the machine that hosts the backend (`my-ubuntu` in the
default). The frontend can't do them for you.

```bash
# 1. Build & start the backend (binds 127.0.0.1:8000; CORS already allows Netlify).
docker compose -f docker-compose.local.yml up -d --build

# 2. Expose it over Tailscale with a real HTTPS cert on :8443.
#    (443 is taken by Nextcloud on this host, so use 8443.)
tailscale serve --bg --https=8443 http://127.0.0.1:8000

# 3. Verify — this must return JSON like {"status":"ok",...}, not HTML.
tailscale serve status
curl -s https://my-ubuntu.tail8e3f2b.ts.net:8443/api/health
```

Once `curl` returns the health JSON, reload the Netlify site and **Connect with
backend** turns green.

### Backend → Ollama path (Docker only)

The bundled LLM **Base URL** default is `http://localhost:11434`. When the
backend runs **in Docker**, `localhost` is the *container*, not the host's
Ollama, so model calls fail even after Connect succeeds. Fix it one of these
ways:

- add `extra_hosts: ["host.docker.internal:host-gateway"]` to the compose
  service and set Base URL to `http://host.docker.internal:11434`, or
- run the backend container with `network_mode: host`, or
- run the backend **natively** on the host — then `http://localhost:11434`
  is already correct.

To change a different host/port, edit `DEFAULT_BACKEND_URL` in
[`static/js/config.js`](static/js/config.js) (and match the `tailscale serve`
port), or set `window.PROTORAG_DEFAULT_BACKEND_URL` before `main.js` loads.

---

## Deploying the frontend on Netlify (with local backend)

The frontend is a static SPA — Netlify just serves the files. All API calls
go to a backend URL the user configures in **Settings**. A typical layout:

```
┌─────────────────────────┐         ┌──────────────────────────┐
│ Browser                 │         │ Your machine             │
│ ─────────────────────── │         │ ──────────────────────── │
│ https://your.netlify.app│ ──API──►│ Cloudflare Tunnel (HTTPS)│
│ (static SPA, Google GIS)│         │     ↓                    │
│                         │         │ uvicorn backend.app:app  │
│                         │         │ Ollama on :11434         │
└─────────────────────────┘         └──────────────────────────┘
```

### 1. Backend env (`.env` next to `uvicorn`)

```bash
GOOGLE_CLIENT_ID=<your-oauth-client-id>
PROTORAG_CORS_ORIGINS=https://your-site.netlify.app
PROTORAG_COOKIE_SECURE=1
```

The backend loads `.env` automatically via `python-dotenv`. Real env vars
set by your shell or service manager still win — see
[backend/__init__.py](backend/__init__.py).

### 2. Google Cloud Console → OAuth Client → Authorized JavaScript origins

Add the **frontend** origins (Google checks the page that loads GIS, not
the API host). For most setups:

- `http://localhost:8000` — local dev
- `https://your-site.netlify.app` — prod

Do **not** add the Cloudflare/Tailscale tunnel hostname — the browser
never opens that URL directly, it just `fetch`es from it.

### 3. Expose the local backend over HTTPS

`SameSite=None` cookies require `Secure`, which requires HTTPS. Use a
**named Cloudflare Tunnel** so the hostname is stable (a quick tunnel
rotates every restart and breaks the CORS allowlist):

```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create protorag
# Edit ~/.cloudflared/config.yml:
#   tunnel: protorag
#   credentials-file: ~/.cloudflared/<UUID>.json
#   ingress:
#     - hostname: api.yourdomain.com
#       service: http://localhost:8000
#     - service: http_status:404
cloudflared tunnel route dns protorag api.yourdomain.com
cloudflared tunnel run protorag
```

Then start the backend bound to localhost:

```bash
python3.12 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

**Don't have a domain?** Use Tailscale Funnel instead:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale funnel 443 on
```

It gives you a stable `*.ts.net` hostname over HTTPS for free.

### 4. Wire the deployed frontend

Open `https://your-site.netlify.app` → **Settings** → set **Remote URL** to
your tunnel hostname (`https://api.yourdomain.com` or the `*.ts.net` URL)
→ Save. Stored in `localStorage`. Click **Test** to verify connectivity.

### Common gotchas

| Symptom | Likely cause |
|---|---|
| Google button doesn't render in the gate | Backend `.env` is missing `GOOGLE_CLIENT_ID`. |
| `origin_mismatch` from Google | Netlify URL not in **Authorized JavaScript origins**. |
| Sign-in "succeeds" but page acts logged out | `Set-Cookie` response missing `Secure; SameSite=None` — `PROTORAG_COOKIE_SECURE=1` not set. |
| `OPTIONS /api/...` returns CORS error | Netlify URL not in `PROTORAG_CORS_ORIGINS` (must match scheme + host exactly). |

---
