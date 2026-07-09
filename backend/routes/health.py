"""Health probe and root HTML serve."""

import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok", "service": "protoRAG+"}


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
