"""Constants and Pydantic models shared across the backend."""

import os
import re
from typing import Optional

from pydantic import BaseModel


DATA_DIR = os.environ.get("DEFAULT_DATA_DIR", "./data")
MAX_HISTORY_ENTRIES = 200
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Server-side provider defaults, reported to the frontend via
# /api/config/defaults once a backend connection is confirmed. Only the
# backend operator actually knows where its LLM/embedding provider lives
# (bare-metal host, Docker's host-gateway alias, a tailnet address, ...) —
# guessing it client-side (as the old hardcoded `host.docker.internal`
# default did) breaks for every deployment shape it didn't guess right.
# All unset by default so the frontend's own PROVIDER_DEFAULTS apply instead.
DEFAULT_PROVIDER_CONFIG = {
    "provider":        os.environ.get("PROTORAG_DEFAULT_PROVIDER", "").strip(),
    "base_url":        os.environ.get("PROTORAG_DEFAULT_BASE_URL", "").strip(),
    "api_key":         os.environ.get("PROTORAG_DEFAULT_API_KEY", "").strip(),
    "model_name":      os.environ.get("PROTORAG_DEFAULT_LLM_MODEL", "").strip(),
    "embedding_model": os.environ.get("PROTORAG_DEFAULT_EMBEDDING_MODEL", "").strip(),
}

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".txt", ".md", ".rst", ".log",
    ".csv", ".tsv",
    ".json", ".jsonl",
    ".yaml", ".yml",
    ".xml", ".html", ".htm",
    ".docx", ".doc",
    ".pptx", ".ppt",
    ".xlsx", ".xls",
}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_OFFICE_EXTS = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"}
_PREVIEW_DIRNAME = ".previews"


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
    data_dir: Optional[str] = None
