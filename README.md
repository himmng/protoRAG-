# protoRAG+

protoRAG+ is a lightweight, local-first RAG (Retrieval-Augmented Generation) chat app. Upload documents, index them locally with Chroma, and chat with an LLM that answers using those documents as context. Nothing leaves your machine unless you choose a hosted LLM provider or a public tunnel.

The backend is a FastAPI app (`backend/`); the frontend is a static single-page app (`index.html` + `static/js/`, no build step). They run as **two independent processes** — the backend never bundles the UI unless explicitly told to (see [Running modes](#running-modes)).

---

## Features

- Local document storage and vector retrieval with Chroma, isolated per user/session
- Broad document support: PDF, Office (`.docx`/`.doc`, `.pptx`/`.ppt`, `.xlsx`/`.xls` via LibreOffice), Markdown, CSV/TSV, JSON/JSONL, YAML, XML/HTML, plain text
- In-browser document preview (Office files are converted to PDF on the fly)
- `@filename` mentions in chat to scope a question to specific uploaded documents
- Streaming chat responses (Server-Sent Events) with session-based history stored on disk
- Pluggable LLM/embedding provider: Ollama, LM Studio, OpenAI, LiteLLM, Anthropic (embeddings via an OpenAI-compatible endpoint), or any custom OpenAI-compatible API
- Optional Google sign-in; anonymous "guest" use works out of the box with isolated per-guest storage
- Bearer-token auth alongside cookies, so a cross-origin frontend (e.g. Netlify) can talk to a local/tunneled backend without cookie quirks
- Docker image with an optional bundled Cloudflare quick tunnel

---

## Project layout

```
backend/            FastAPI app — API only by default
  app.py            App assembly: CORS, PNA middleware, router mounts
  auth/              Guest + Google auth, cookie/bearer session handling
  rag/               Chroma vectorstore, loaders, embeddings, LLM calls, history
  routes/            /api/chat, /api/upload, /api/sessions, /api/documents, /api/health
frontend/            Static file server for the UI — `python3 -m frontend`
index.html           The SPA shell
static/js/           SPA modules (api, chat, upload, sessions, auth, config, ...)
Dockerfile           Bundles backend + frontend + cloudflared into one image
docker-compose.yml   One-command "Netlify frontend + local backend" launcher
entrypoint.sh        Container entrypoint (backend + optional tunnel)
```

---

## Requirements

- Python 3.10+ and pip
- An LLM endpoint compatible with the OpenAI API — e.g. [Ollama](https://ollama.com) (`/v1` endpoint), LM Studio, OpenAI, LiteLLM, or Anthropic
- For Office document previews: `soffice` (LibreOffice) on `PATH`. Docker installs everything needed; local runs need it installed separately if you want that feature.

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## Running modes

protoRAG+ can run three ways. Pick whichever fits:

| Mode | Command(s) | When to use |
|---|---|---|
| [All-in-one Docker](#1-all-in-one-docker-single-container) | `docker run` / `docker build` | Simplest self-contained setup — one container, UI + API on `:8000` |
| [Local backend + local frontend](#2-local-backend--local-frontend-no-docker) | `python -m backend` + `python3 -m frontend` | Development, or running fully outside Docker |
| [Netlify frontend + local backend](#3-netlify-frontend--local-backend) | `docker compose up -d --build` | Use the hosted UI at protorag.netlify.app against your own local models |

In every mode, all inference happens wherever your LLM endpoint runs (e.g. your own Ollama) — the FastAPI backend is the only thing that talks to it; the browser never does.

### 1. All-in-one Docker (single container)

One container serves both the API and the UI on port `8000`.

```bash
docker build -t protorag:latest .
docker run \
  --name protorag \
  -p 127.0.0.1:8000:8000 \
  -v /path/on/host:/app/data \
  protorag:latest
```

- Open `http://localhost:8000/` — the UI is served directly.
- All documents, Chroma DB files, and histories live under `/app/data` in the container (mapped to `/path/on/host`).
- Set `-e ENABLE_CLOUDFLARE_TUNNEL=true` to also start a Cloudflare quick tunnel exposing port `8000` publicly over HTTPS (URL printed to `docker logs`).
- In the UI Settings: **Storage Path (Local)** → `./data`; set your LLM endpoint fields as usual (can be remote).

The Dockerfile sets `SERVE_FRONTEND=true`, which is what makes the backend serve `index.html`/`static/` at all — see mode 2 for what changes when that's off.

### 2. Local backend (+ optional local frontend), no Docker

**One command** (recommended, single port): starts the backend with `SERVE_FRONTEND=true` so it serves both the API and the UI on the same port — matching Docker's all-in-one behavior, and matching whatever origin (`http://localhost:8000`) you've already registered in Google Cloud Console if you use Google sign-in. No second process, no extra origin to add anywhere.

```bash
python run.py
# custom port: python run.py --backend-port 8000
# skip auto-opening the browser: python run.py --no-browser
```

Open `http://localhost:8000/` — the gate's **Connect with backend** button goes green immediately (same-origin), and Google sign-in works with whatever origin you already trust for `:8000`.

**Two-port mode** (`--split`), if you specifically want the frontend served separately (e.g. static-hosting it, or iterating on `static/js/*.js` without backend `--reload` restarts):

```bash
python run.py --split
# or manually, two terminals:
#   python -m backend                    # API only, no UI at "/"
#   python3 -m frontend --port 4444      # static file server, auto-wires to :8000
```

This puts the frontend on its own origin (`http://localhost:4444` by default), which means:
- You must add that origin to Google Cloud Console's **Authorized JavaScript origins** separately if you use Google sign-in (see [Authentication](#authentication)) — it's a different origin than `:8000`, even on the same machine.
- Set `PROTORAG_CORS_ORIGINS=http://localhost:4444` on the backend so auth cookies/bearer tokens work — see [CORS & cross-origin auth](#cors--cross-origin-auth).

Either mode, in Settings you'll still want to fill in:

- **Storage Path (Local)**: `./data` (or another directory)
- **Provider**: `ollama` or the appropriate provider name
- **Base URL**: your LLM endpoint's base URL — for Ollama, typically `http://localhost:11434`
- **API Key**: as required by your provider (for local Ollama, any placeholder value works)
- **LLM Model** / **Embedding Model**: the model names to use

By default, data is stored under `./data` (configurable via `DEFAULT_DATA_DIR`).

### 3. Netlify frontend + local backend

Use the hosted UI at <https://protorag.netlify.app> against a backend that never leaves your machine — only your LLM endpoint needs to be reachable (it can also stay local).

```bash
docker compose up -d --build
```

That one command:

- Builds the image locally (tagged `protorag-local:latest` — the `+` in the repo name can't appear in a Docker image reference, so this builds instead of pulling from GHCR).
- Binds port `8000` to `127.0.0.1` only — never exposed to your LAN.
- Pre-sets `PROTORAG_CORS_ORIGINS=https://protorag.netlify.app` so cross-origin fetches from the deployed site succeed.
- Mounts `~/protorag_storage` into the container as `/data` — your vector DB, documents, and `users.db` live on your disk.

Then in the browser:

1. Open <https://protorag.netlify.app>.
2. Click **Continue as guest** (or sign in with Google if `GOOGLE_CLIENT_ID` is set).
3. In **Settings**, set **Backend URL** → `http://localhost:8000`, click **Test** (dot should turn green), and set your LLM provider/model fields.
4. Upload documents (or ingest a whole directory via the folder icon) and chat.

If the Netlify page needs to reach this backend from somewhere other than the same machine, set `ENABLE_CLOUDFLARE_TUNNEL=true` for a public HTTPS URL — see [Exposing the backend over HTTPS](#exposing-the-backend-over-https).

#### Reaching a local Ollama from the container

The dockerized backend reaches your host's Ollama via Docker's host-gateway alias (already wired in `docker-compose.yml` and the frontend defaults in `static/js/config.js`: `DEFAULT_OLLAMA_BASE_URL = http://host.docker.internal:11434`). Two host-side requirements:

1. **Ollama must listen on all interfaces** (the default `127.0.0.1` bind isn't reachable from inside Docker):

   ```bash
   OLLAMA_HOST=0.0.0.0 ollama serve
   ```

2. **The data directory must be writable by uid 1000** (the container user), or auth 500s with `unable to open database file`:

   ```bash
   mkdir -p ~/protorag_storage
   sudo chown -R 1000:1000 ~/protorag_storage
   ```

Recreate the container after editing `docker-compose.yml` so changes like `extra_hosts` take effect: `docker compose up -d --build`.

To point at a different backend/Ollama host by default, edit `DEFAULT_BACKEND_URL` / `DEFAULT_OLLAMA_BASE_URL` in `static/js/config.js`, or set `window.PROTORAG_DEFAULT_BACKEND_URL` / `window.PROTORAG_DEFAULT_OLLAMA_URL` before `main.js` loads.

---

## Configuration (environment variables)

Set these on the backend process (shell env, `.env` file next to `uvicorn`, or `docker-compose.yml` / `docker run -e`):

| Variable | Default | Purpose |
|---|---|---|
| `DEFAULT_DATA_DIR` | `./data` | Base directory for per-user document/vector storage and `users.db` |
| `SERVE_FRONTEND` | unset (off) | Serve `index.html` + `static/` from the backend at `/` and `/static/*`. Docker sets this to `true`; leave unset for API-only local runs |
| `GOOGLE_CLIENT_ID` | unset | Enables Google sign-in (see [Authentication](#authentication)) |
| `PROTORAG_CORS_ORIGINS` | unset (`*`, no credentials) | Comma-separated allowlist of frontend origins allowed to send credentials cross-origin. Required whenever the frontend and backend are on different origins (Netlify, `python3 -m frontend` on a different port, tunnels) |
| `PROTORAG_COOKIE_SECURE` | unset (off) | Marks auth cookies `Secure` + `SameSite=None`. Required when the backend is served over HTTPS (Cloudflare/Tailscale tunnel, Render, etc.) |
| `ENABLE_CLOUDFLARE_TUNNEL` | `false` | Docker only — starts a bundled `cloudflared` quick tunnel exposing `:8000` over HTTPS |

The backend loads a `.env` file automatically via `python-dotenv` (see `backend/__init__.py`); real env vars set by your shell/service manager always win over `.env` values.

---

## API overview

All routes are prefixed `/api` except the frontend-serving root, and all except `/api/health` require a resolved user (guest/bearer/cookie — see [Authentication](#authentication)):

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness probe |
| `GET /api/auth/status` | Check for an existing session without minting a new guest |
| `GET /api/auth/me` | Current user + whether Google sign-in is configured |
| `POST /api/auth/guest` | Mint an anonymous guest session (cookie + bearer token) |
| `POST /api/auth/google` | Exchange a Google ID token for a session; merges any prior guest storage |
| `POST /api/auth/logout` | Revoke the current session's token(s) |
| `POST /api/upload` | Upload a document into a session, chunk it, and index it into Chroma |
| `POST /api/chat` | Stream a chat response (SSE), retrieving context from the session's indexed documents |
| `GET /api/sessions` | List sessions (with preview + whether they have indexed docs) |
| `GET /api/sessions/{session_id}` | Get a session's chat history and document list |
| `DELETE /api/sessions/{session_id}` | Delete a session and its data |
| `GET /api/sessions/{session_id}/documents/{filename}` | Download a stored document |
| `GET /api/sessions/{session_id}/documents/{filename}/preview` | Preview a document (Office files are converted to PDF on the fly via LibreOffice) |
| `DELETE /api/sessions/{session_id}/documents/{filename}` | Delete a document and rebuild the session's index |
| `GET /` | JSON status by default; serves `index.html` instead when `SERVE_FRONTEND=true` |

---

## Data storage

- Default base directory: `./data` (override with `DEFAULT_DATA_DIR`).
- A small SQLite store at `<data_dir>/users.db` holds users + auth sessions.
- RAG data is isolated per user:
  - `<data_dir>/users/<user_id>/db/session/<session_id>/` — Chroma DB + `history.json`
  - `<data_dir>/users/<user_id>/documents/session/<session_id>/` — uploaded documents
- First visit issues a `pr_guest` cookie (HttpOnly, 1-year TTL) so anonymous use works without sign-in; each guest gets an isolated `<user_id>` folder.
- Pre-existing flat `data/db/session/...` layouts from older versions are not auto-migrated — re-upload to move into the per-user layout.

---

## Authentication

Auth is optional and layered:

1. **Guest (default)** — first request mints an anonymous user with a 1-year `pr_guest` cookie. No setup required.
2. **Google sign-in (opt-in)** — set `GOOGLE_CLIENT_ID` to show a "Sign in with Google" button in the sidebar. Any existing guest storage is merged into the Google account on first login.

```bash
export GOOGLE_CLIENT_ID="123…apps.googleusercontent.com"
python -m backend
```

Create a Google Cloud OAuth 2.0 Web Application client and add your **frontend's** origin(s) to **Authorized JavaScript origins** (Google checks the page that loads the sign-in widget, not the API host) — e.g. `http://localhost:4444` for local dev, `https://your-site.netlify.app` for prod. Without `GOOGLE_CLIENT_ID`, the button is hidden and everyone stays anonymous.

### CORS & cross-origin auth

Whenever the frontend and backend are on different origins (Netlify, a locally separate `python3 -m frontend`, or a tunnel), set:

- `PROTORAG_CORS_ORIGINS` — comma-separated allowlist of frontend origin(s), e.g. `http://localhost:4444` or `https://your-site.netlify.app`. Enables `Access-Control-Allow-Credentials`.
- `PROTORAG_COOKIE_SECURE=1` — only if the backend itself is served over HTTPS (a tunnel, Render, etc.); leave unset for plain `http://localhost`.

Browsers handle `SameSite=None` cookies on plain-HTTP `localhost` inconsistently, so `/api/auth/guest` and `/api/auth/google` also return a **bearer token** in the JSON body. The frontend stores it in `localStorage` and sends `Authorization: Bearer …` on every request — same-origin cookie auth still works unaffected, this is purely additive for the cross-origin case.

Chrome's [Private Network Access](https://wicg.github.io/private-network-access/) spec additionally requires an opt-in from the backend before an HTTPS page can call `http://localhost`/private IPs; this is handled automatically by middleware in `backend/app.py`.

---

## Exposing the backend over HTTPS

Needed for `SameSite=None` cookies (Google sign-in) when the frontend is on a different HTTPS origin, e.g. Netlify.

### Quick tunnel (bundled in the Docker image — easiest)

```bash
ENABLE_CLOUDFLARE_TUNNEL=true docker compose up -d --build
docker compose logs -f
# look for: https://random-words-1234.trycloudflare.com
```

Paste that URL into the frontend's Settings → Backend URL. It rotates on every restart — re-paste each time you `up`/restart. For a stable hostname, use one of the options below instead.

### Named Cloudflare Tunnel (stable hostname)

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

Then start the backend bound to localhost: `uvicorn backend:app --host 127.0.0.1 --port 8000`.

### Tailscale Funnel (no domain needed)

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale funnel 443 on
```

Gives a stable `*.ts.net` HTTPS hostname for free.

### Secure LLM inference over Tailscale

You can also keep your LLM endpoint itself private on a Tailscale tailnet instead of exposing it publicly:

1. Install and log in to Tailscale on the machine running your LLM server.
2. Bind it to Tailscale/localhost, e.g. for Ollama: `OLLAMA_HOST=127.0.0.1:11434 ollama serve`.
3. From a tailnet-connected client, find the server's Tailscale IP or MagicDNS name (e.g. `100.x.y.z` or `llm-server.tailnet-name.ts.net`).
4. In Settings, set **Base URL** to `http://llm-server.tailnet-name.ts.net:11434/v1` (or the IP form).

Only devices on your tailnet can reach the LLM endpoint.

---

## The "Connect with backend" gate

Every visit to the frontend shows a **Connect with backend** step before Google/guest sign-in, so the backend + identity are re-confirmed each time. `DEFAULT_BACKEND_URL` in `static/js/config.js` reads `window.PROTORAG_DEFAULT_BACKEND_URL`, falling back to same-origin (empty string) when unset — correct when the frontend is served by the same backend it talks to (Docker all-in-one). There's no portable default across *all* deployments, so:

- `python3 -m frontend` injects `window.PROTORAG_DEFAULT_BACKEND_URL` itself, pointed at `--backend` (default `http://localhost:8000`) — the common "backend + frontend, same machine, different ports" case just works.
- For anything else cross-origin (Netlify, a tunnel, a non-default port), set it explicitly via **Settings → Backend URL** (persisted to `localStorage`), or pass `--backend` / set `window.PROTORAG_DEFAULT_BACKEND_URL` before `main.js` loads.

Clicking the button applies the bundled provider defaults, probes `/api/health`, and shows a green/red result.

> The frontend only ever talks to the FastAPI backend; the backend talks to your LLM endpoint server-side. The URL you configure is always the backend's, never Ollama's `:11434` directly.

---

## Common gotchas

| Symptom | Likely cause |
|---|---|
| `http://localhost:8000/` returns JSON, not the UI | Expected outside Docker — the backend is API-only unless `SERVE_FRONTEND=true`. Run `python3 -m frontend` for the UI. |
| Google button doesn't render in the gate | `GOOGLE_CLIENT_ID` isn't set on the backend. |
| `origin_mismatch` from Google | Frontend's origin isn't in Google Cloud Console's **Authorized JavaScript origins**. |
| Sign-in "succeeds" but the page acts logged out | `Set-Cookie` is missing `Secure; SameSite=None` — set `PROTORAG_COOKIE_SECURE=1`. |
| `OPTIONS /api/...` returns a CORS error | Frontend origin isn't in `PROTORAG_CORS_ORIGINS` (must match scheme + host exactly, no trailing slash). |
| Docker container can't reach Ollama | Ollama bound to `127.0.0.1` instead of `0.0.0.0` — see [Reaching a local Ollama from the container](#reaching-a-local-ollama-from-the-container). |
| Auth 500s with "unable to open database file" (Docker) | Host data dir not writable by uid 1000 — `sudo chown -R 1000:1000 ~/protorag_storage`. |
