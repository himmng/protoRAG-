"""FastAPI app assembly: middleware, router mounts, shutdown hook."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from .auth.routes import router as auth_router
from .rag.chroma import flush_all_vectorstores
from .routes.chat import router as chat_router
from .routes.documents import router as documents_router
from .routes.health import router as health_router
from .routes.sessions import router as sessions_router
from .routes.upload import router as upload_router


app = FastAPI(title="protoRAG+ API")

# CORS for cross-origin frontends (Netlify, etc.). When `PROTORAG_CORS_ORIGINS`
# is set, credentials (auth cookies) are allowed and origins are tightened to
# the allowlist — browsers reject `*` + credentials. Default to permissive
# same-origin behavior without credentials.
_cors_origins_env = os.environ.get("PROTORAG_CORS_ORIGINS", "").strip()
if _cors_origins_env:
    # Per the CORS spec, an Origin is scheme+host+port — NEVER a trailing
    # slash. Users routinely paste `https://site.netlify.app/` into .env
    # and then get silent rejection because string comparison fails.
    # Strip defensively here so the obvious mistake just works.
    _allow_origins = [
        o.strip().rstrip("/")
        for o in _cors_origins_env.split(",")
        if o.strip()
    ]
    _allow_credentials = True
else:
    _allow_origins = ["*"]
    _allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _private_network_access(request, call_next):
    # Chrome's Private Network Access blocks HTTPS pages from calling
    # http://localhost backends unless the preflight reply opts in. This
    # makes Mode B (Netlify frontend → local backend) work without flags.
    if request.method == "OPTIONS" and request.headers.get("access-control-request-private-network"):
        resp = Response(status_code=204)
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        resp.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
        resp.headers["Access-Control-Allow-Methods"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = request.headers.get("access-control-request-headers", "*")
        if _allow_credentials:
            resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    return await call_next(request)


app.include_router(auth_router)
app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(documents_router)
app.include_router(health_router)

# Frontend ES modules. Only mounted when SERVE_FRONTEND is enabled (Docker's
# bundled single-container mode) and the static/ dir exists, so a plain
# backend-only run (uvicorn / python -m backend) doesn't expose it.
_serve_frontend = os.environ.get("SERVE_FRONTEND", "false").strip().lower() in ("1", "true", "yes")
if _serve_frontend and os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("shutdown")
def _flush_session_vectorstores():
    flush_all_vectorstores()
