"""Per-session chat history persistence as JSON files on disk."""

import json
import os

from ..config import MAX_HISTORY_ENTRIES


def load_history(session_id: str, db_dir: str) -> list:
    path = os.path.join(db_dir, session_id, "history.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_history(session_id: str, history: list, db_dir: str):
    path = os.path.join(db_dir, session_id, "history.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(history[-MAX_HISTORY_ENTRIES:], f)
