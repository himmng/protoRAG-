"""FastAPI dependency that resolves the requester to a User.

Resolution order on every request:
  1. `Authorization: Bearer <token>` header → bearer auth (Netlify ↔ localhost).
  2. `pr_auth` cookie  → real signed-in user (Google in Phase D).
  3. `pr_guest` cookie → existing anonymous user.
  4. Mint a fresh anonymous user, drop a 1-year `pr_guest` cookie.

The bearer path exists because the Netlify-hosted frontend talking to a local
backend (https → http://localhost) hits browser-specific cookie quirks
(SameSite=None+Secure on plain-http localhost). Bearer tokens stored in
localStorage sidestep all of it. Same token table as cookies, no schema split.

The last path preserves the "open and use" UX: no sign-in required, but every
request is bound to a stable user_id so storage stays isolated.
"""

import os

from fastapi import Request, Response

from .db import (
    User,
    create_anonymous_user,
    create_auth_token,
    find_user_by_token,
    touch_user,
)


GUEST_COOKIE = "pr_guest"
AUTH_COOKIE = "pr_auth"
GUEST_TTL_SECONDS = 365 * 24 * 3600
AUTH_TTL_SECONDS = 30 * 24 * 3600

# Set when serving behind HTTPS (e.g. Cloudflare, Render). Browsers reject
# Secure cookies on plain http://localhost otherwise — keep off in dev.
COOKIE_SECURE = os.environ.get("PROTORAG_COOKIE_SECURE", "").lower() in ("1", "true", "yes")

# When the frontend is on a different origin than the backend (e.g. Netlify
# frontend → tunneled backend), the auth cookie must be SameSite=None so the
# browser sends it on cross-site fetches. Browsers REQUIRE Secure=true with
# SameSite=None — so we only flip this when COOKIE_SECURE is on.
COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"


def set_guest_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=GUEST_COOKIE,
        value=token,
        max_age=GUEST_TTL_SECONDS,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        path="/",
    )


def set_auth_cookie(response: Response, token: str) -> None:
    """Used by /api/auth/google to swap the guest cookie for a real session."""
    response.set_cookie(
        key=AUTH_COOKIE,
        value=token,
        max_age=AUTH_TTL_SECONDS,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE, path="/")


def clear_guest_cookie(response: Response) -> None:
    response.delete_cookie(GUEST_COOKIE, path="/")


def _bearer_token(request: Request) -> str | None:
    """Pull the bearer token out of Authorization, if present."""
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def current_user(request: Request, response: Response) -> User:
    bearer = _bearer_token(request)
    if bearer:
        user = find_user_by_token(bearer)
        if user is not None:
            touch_user(user.user_id)
            return user

    auth_token = request.cookies.get(AUTH_COOKIE)
    if auth_token:
        user = find_user_by_token(auth_token)
        if user is not None:
            touch_user(user.user_id)
            return user

    guest_token = request.cookies.get(GUEST_COOKIE)
    if guest_token:
        user = find_user_by_token(guest_token)
        if user is not None:
            touch_user(user.user_id)
            return user

    user = create_anonymous_user()
    token = create_auth_token(user.user_id, "guest", GUEST_TTL_SECONDS)
    set_guest_cookie(response, token)
    return user
