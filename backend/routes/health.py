"""Health probe and root HTML serve."""

import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok", "service": "protoRAG+"}


@router.get("/")
def get_ui():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found alongside backend.py</h1>")
