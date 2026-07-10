"""Google ID-token verification.

We rely on `google-auth` to validate the JWT signature, issuer, audience,
expiry, and `email_verified` claim in one call. If the env var
`GOOGLE_CLIENT_ID` is unset, sign-in is disabled — `verify_id_token` raises
HTTPException(503) so callers don't accidentally accept unverifiable tokens.
"""

import os
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException

from ..logging_config import get_logger

log = get_logger("auth.google")


@dataclass
class GoogleProfile:
    sub: str
    email: str
    name: Optional[str]
    picture: Optional[str]


def google_client_id() -> Optional[str]:
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    return cid or None


def verify_id_token(id_token_str: str) -> GoogleProfile:
    cid = google_client_id()
    if not cid:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured on this server (GOOGLE_CLIENT_ID unset).",
        )
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="`google-auth` not installed on backend. Run: pip install google-auth",
        )

    try:
        payload = google_id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            cid,
        )
    except ValueError as e:
        # ValueError is the library's catch-all for bad signature, wrong audience,
        # expired token, etc. Surface as 401 so the frontend prompts re-signin.
        log.error("Google ID token verification failed: %s", e)
        raise HTTPException(status_code=401, detail=f"Invalid Google ID token: {e}")

    if not payload.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google account email is not verified.")

    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        raise HTTPException(status_code=401, detail="Google ID token missing required claims.")

    return GoogleProfile(
        sub=sub,
        email=email,
        name=payload.get("name"),
        picture=payload.get("picture"),
    )
