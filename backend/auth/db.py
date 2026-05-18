"""SQLite user + auth-session store (stdlib only).

Schema lives at `{DEFAULT_DATA_DIR}/users.db`. One pool per backend deployment,
independent of any per-request `data_dir` override — that override only
controls where on disk a user's RAG data lives, not their identity.
"""

import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

from ..config import DATA_DIR


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id       TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,
  google_sub    TEXT UNIQUE,
  email         TEXT,
  name          TEXT,
  picture       TEXT,
  created_at    INTEGER NOT NULL,
  last_seen_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
  token        TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL,
  kind         TEXT NOT NULL,
  expires_at   INTEGER NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
"""


@dataclass
class User:
    user_id: str
    kind: str  # 'anonymous' | 'google'
    email: Optional[str] = None
    name: Optional[str] = None
    picture: Optional[str] = None
    google_sub: Optional[str] = None

    def to_public_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "kind": self.kind,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
        }


def _users_db_path() -> str:
    base = os.path.expanduser(DATA_DIR)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "users.db")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(_users_db_path())
    c.row_factory = sqlite3.Row
    try:
        c.executescript(_SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["user_id"],
        kind=row["kind"],
        email=row["email"],
        name=row["name"],
        picture=row["picture"],
        google_sub=row["google_sub"],
    )


def create_anonymous_user() -> User:
    user_id = str(uuid.uuid4())
    now = int(time.time())
    with _conn() as c:
        c.execute(
            "INSERT INTO users(user_id,kind,created_at,last_seen_at) VALUES(?,?,?,?)",
            (user_id, "anonymous", now, now),
        )
    return User(user_id=user_id, kind="anonymous")


def get_user(user_id: str) -> Optional[User]:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None


def touch_user(user_id: str) -> None:
    now = int(time.time())
    with _conn() as c:
        c.execute("UPDATE users SET last_seen_at=? WHERE user_id=?", (now, user_id))


def upsert_google_user(google_sub: str, email: str, name: str, picture: str) -> User:
    """Insert or update a Google-authenticated user keyed by google_sub."""
    now = int(time.time())
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE google_sub=?", (google_sub,)).fetchone()
        if row:
            c.execute(
                "UPDATE users SET email=?, name=?, picture=?, last_seen_at=? WHERE user_id=?",
                (email, name, picture, now, row["user_id"]),
            )
            return User(
                user_id=row["user_id"], kind="google",
                email=email, name=name, picture=picture, google_sub=google_sub,
            )
        user_id = str(uuid.uuid4())
        c.execute(
            "INSERT INTO users(user_id,kind,google_sub,email,name,picture,created_at,last_seen_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (user_id, "google", google_sub, email, name, picture, now, now),
        )
        return User(
            user_id=user_id, kind="google",
            email=email, name=name, picture=picture, google_sub=google_sub,
        )


def create_auth_token(user_id: str, kind: str, ttl_seconds: int) -> str:
    """Mint an opaque session token. Caller is responsible for setting the cookie."""
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_seconds
    with _conn() as c:
        c.execute(
            "INSERT INTO auth_sessions(token,user_id,kind,expires_at) VALUES(?,?,?,?)",
            (token, user_id, kind, expires_at),
        )
    return token


def find_user_by_token(token: str) -> Optional[User]:
    """Resolve a token to its user iff the token is unexpired."""
    now = int(time.time())
    with _conn() as c:
        row = c.execute(
            "SELECT u.* FROM auth_sessions s JOIN users u ON u.user_id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > ?",
            (token, now),
        ).fetchone()
        return _row_to_user(row) if row else None


def revoke_auth_token(token: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM auth_sessions WHERE token=?", (token,))


def revoke_all_for_user(user_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))


def delete_user(user_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id=?", (user_id,))


def merge_guest_storage(data_root: str, guest_id: str, target_id: str) -> int:
    """Move guest's RAG storage into the target user's tree.

    Returns the number of session subdirs moved. Uuid collisions on the same
    side (db/ and documents/) are skipped — keeping the existing target wins.

    Only operates on the default data dir; a guest who ever used a custom
    `data_dir` keeps that data orphaned at the old path. Documented as a known
    limitation.
    """
    import os
    import shutil

    src = os.path.join(data_root, "users", guest_id)
    dst = os.path.join(data_root, "users", target_id)
    if not os.path.isdir(src):
        return 0

    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)
        return 1

    moved = 0
    for top in ("db", "documents"):
        src_top = os.path.join(src, top, "session")
        dst_top = os.path.join(dst, top, "session")
        if not os.path.isdir(src_top):
            continue
        os.makedirs(dst_top, exist_ok=True)
        for sid in os.listdir(src_top):
            src_sid = os.path.join(src_top, sid)
            dst_sid = os.path.join(dst_top, sid)
            if os.path.exists(dst_sid):
                continue  # collision is vanishingly improbable for uuid4 ids
            os.rename(src_sid, dst_sid)
            moved += 1
    shutil.rmtree(src, ignore_errors=True)
    return moved
