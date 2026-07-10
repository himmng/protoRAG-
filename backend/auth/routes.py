"""Auth endpoints: /me, /logout, /google (token exchange)."""

import os

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from ..config import DATA_DIR
from .db import (
    User,
    create_anonymous_user,
    create_auth_token,
    delete_user,
    find_user_by_token,
    merge_guest_storage,
    revoke_all_for_user,
    revoke_auth_token,
    upsert_google_user,
)
from .deps import (
    AUTH_COOKIE,
    AUTH_TTL_SECONDS,
    GUEST_COOKIE,
    GUEST_TTL_SECONDS,
    _bearer_token,
    clear_auth_cookie,
    clear_guest_cookie,
    current_user,
    set_auth_cookie,
    set_guest_cookie,
)
from .google import google_client_id, verify_id_token
from ..logging_config import get_logger


router = APIRouter()
log = get_logger("auth")


@router.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    # Surface GOOGLE_CLIENT_ID so the UI can show or hide the sign-in button.
    return {
        "user": user.to_public_dict(),
        "google_client_id": google_client_id(),
    }


@router.get("/api/auth/status")
def auth_status(request: Request):
    """Non-minting probe used by the frontend gate.

    Returns whether the caller already has a valid session WITHOUT setting any
    cookie. Lets the UI show a "continue as guest / sign in" landing screen
    on the very first visit instead of silently minting a guest behind the
    user's back.
    """
    candidates = []
    bearer = _bearer_token(request)
    if bearer:
        candidates.append(bearer)
    candidates.extend(t for t in (request.cookies.get(AUTH_COOKIE), request.cookies.get(GUEST_COOKIE)) if t)
    for token in candidates:
        u = find_user_by_token(token)
        if u:
            return {
                "authenticated": True,
                "user": u.to_public_dict(),
                "google_client_id": google_client_id(),
            }
    return {"authenticated": False, "google_client_id": google_client_id()}


@router.post("/api/auth/guest")
def continue_as_guest(response: Response):
    """Explicit guest minter — fires only when the user clicks 'Continue as guest'."""
    user = create_anonymous_user()
    token = create_auth_token(user.user_id, "guest", GUEST_TTL_SECONDS)
    set_guest_cookie(response, token)
    log.info("guest session minted: user=%s", user.user_id)
    # Token is also returned in the body so cross-origin clients (Netlify
    # frontend → localhost backend) can store it in localStorage and send it
    # as `Authorization: Bearer …` instead of relying on the cookie.
    return {
        "user": user.to_public_dict(),
        "token": token,
        "expires_in": GUEST_TTL_SECONDS,
    }


@router.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
):
    # Revoke whichever token this client actually presented, then clear both
    # cookies. The dep may have just minted a fresh guest if neither cookie
    # was valid — that's harmless; the cookies we clear below ensure the
    # client starts clean on the next request.
    bearer = _bearer_token(request)
    if bearer:
        revoke_auth_token(bearer)
    for cookie_name in (AUTH_COOKIE, GUEST_COOKIE):
        token = request.cookies.get(cookie_name)
        if token:
            revoke_auth_token(token)
    clear_auth_cookie(response)
    clear_guest_cookie(response)
    return {"status": "logged_out"}


@router.post("/api/auth/google")
def google_login(
    request: Request,
    response: Response,
    payload: dict = Body(...),
):
    """Exchange a Google ID token for a `pr_auth` cookie.

    If the caller has an existing guest cookie, their RAG storage is moved
    into the Google account on first login so they don't lose work.
    """
    id_token = (payload or {}).get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token in body")

    profile = verify_id_token(id_token)
    user = upsert_google_user(
        google_sub=profile.sub,
        email=profile.email,
        name=profile.name or "",
        picture=profile.picture or "",
    )
    log.info("google session minted: user=%s email=%s", user.user_id, profile.email)

    # Mint a fresh auth session and swap cookies.
    token = create_auth_token(user.user_id, "google", AUTH_TTL_SECONDS)
    set_auth_cookie(response, token)
    # Same token is echoed in the body for the bearer-auth path (see
    # /api/auth/guest above for the rationale).

    # Optional one-shot merge: if the requester arrived with a valid guest
    # cookie that points at a different (anonymous) user, fold that user's
    # storage into the Google account and revoke the guest.
    merged_sessions = 0
    guest_token = request.cookies.get(GUEST_COOKIE)
    if guest_token:
        guest_user = find_user_by_token(guest_token)
        if guest_user and guest_user.kind == "anonymous" and guest_user.user_id != user.user_id:
            merged_sessions = merge_guest_storage(
                DATA_DIR, guest_user.user_id, user.user_id
            )
            revoke_all_for_user(guest_user.user_id)
            delete_user(guest_user.user_id)
    clear_guest_cookie(response)

    return {
        "user": user.to_public_dict(),
        "token": token,
        "expires_in": AUTH_TTL_SECONDS,
        "merged_sessions": merged_sessions,
    }
