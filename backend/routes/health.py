"""Health probe and root HTML serve."""

import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..config import DEFAULT_PROVIDER_CONFIG


router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok", "service": "protoRAG+"}


@router.get("/api/config/defaults")
def config_defaults():
    """Provider defaults this backend operator has configured (if any).

    Only fields actually set via env vars are included — the frontend fills
    these in once the backend connection succeeds, and leaves its own
    PROVIDER_DEFAULTS in place for anything the backend didn't specify.
    """
    return {k: v for k, v in DEFAULT_PROVIDER_CONFIG.items() if v}


# Bundled-UI serving is opt-in. Docker sets SERVE_FRONTEND=true so the single
# container works standalone; a plain `uvicorn backend:app` / `python -m
# backend` run stays backend-only (API + docs, no HTML at "/") so it can sit
# behind a separately-hosted frontend (Netlify, `python3 -m frontend`, ...).
_SERVE_FRONTEND = os.environ.get("SERVE_FRONTEND", "false").strip().lower() in ("1", "true", "yes")

if _SERVE_FRONTEND:

    @router.get("/")
    def get_ui():
        if os.path.exists("index.html"):
            with open("index.html", "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>index.html not found alongside backend.py</h1>")

else:

    @router.get("/")
    def get_ui():
        return {
            "status": "ok",
            "service": "protoRAG+ backend",
            "message": "This is the API only. Run the frontend separately "
            "(python3 -m frontend, or Netlify) and point it at this backend.",
        }
