"""Constants and Pydantic models shared across the backend."""

import os
import re
from typing import Optional

from pydantic import BaseModel


DATA_DIR = os.environ.get("DEFAULT_DATA_DIR", "./data")
MAX_HISTORY_ENTRIES = 200
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

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
