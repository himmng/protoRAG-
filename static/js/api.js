// URL builders + a fetch wrapper that handles cross-origin auth.
//
// The auth model has two layers:
//   1. **Client-side identity choice** (mode='guest' or 'google'). Stored in
//      localStorage the moment the user clicks a gate button. This step
//      requires NO backend — it just records the user's preference.
//   2. **Backend session token** (`pr_token`). Minted by /api/auth/guest or
//      /api/auth/google the first time we need to call a real API. Stored
//      in localStorage, sent as `Authorization: Bearer …`.
//
// The split means a user can sign in (or pick guest) on Netlify, leave,
// start their local backend, come back, and have their auth choice still
// in place — apiFetch will lazily mint the backend session on demand.

import { config } from './config.js';

const TOKEN_KEY          = 'pr_token';
const MODE_KEY           = 'pr_mode';            // 'guest' | 'google'
const GOOGLE_TOKEN_KEY   = 'pr_google_id_token'; // raw Google ID token
const GOOGLE_PROFILE_KEY = 'pr_google_profile';  // {sub, email, name, picture}

// ── Storage helpers ─────────────────────────────────────────────────────

function lsGet(key) { try { return localStorage.getItem(key) || ''; } catch { return ''; } }
function lsSet(key, value) {
    try {
        if (value === null || value === undefined || value === '') localStorage.removeItem(key);
        else localStorage.setItem(key, value);
    } catch { /* private mode / quota */ }
}

export function getToken()           { return lsGet(TOKEN_KEY); }
export function setToken(t)          { lsSet(TOKEN_KEY, t); }
export function getMode()            { return lsGet(MODE_KEY); }
export function setMode(m)           { lsSet(MODE_KEY, m); }
export function getGoogleIdToken()   { return lsGet(GOOGLE_TOKEN_KEY); }
export function setGoogleIdToken(t)  { lsSet(GOOGLE_TOKEN_KEY, t); }
export function getGoogleProfile() {
    try { return JSON.parse(lsGet(GOOGLE_PROFILE_KEY) || 'null'); }
    catch { return null; }
}
export function setGoogleProfile(p) {
    lsSet(GOOGLE_PROFILE_KEY, p ? JSON.stringify(p) : '');
}

export function clearAuth() {
    setToken(null);
    setMode(null);
    setGoogleIdToken(null);
    setGoogleProfile(null);
}

// ── URL builders ────────────────────────────────────────────────────────

export function api(path) {
    return (config.backend_url || '').replace(/\/$/, '') + path;
}

export function apiWithDataDir(path) {
    const url = api(path);
    if (!config.data_dir) return url;
    const sep = url.includes('?') ? '&' : '?';
    return url + sep + 'data_dir=' + encodeURIComponent(config.data_dir);
}

// ── Lazy backend session exchange ───────────────────────────────────────
//
// Posts the user's client-side identity choice to the backend to mint a
// bearer token. Idempotent: returns true immediately if a token already
// exists. Returns false if the user hasn't picked a mode, or if the
// backend is unreachable — callers decide how to surface that (usually
// a "configure / start your backend" banner).

// ── No-backend banner control ───────────────────────────────────────────

function setNoBackendBanner(visible, message) {
    const el = document.getElementById('no-backend-banner');
    if (!el) return;
    if (visible) {
        if (message) {
            const msgEl = document.getElementById('no-backend-banner-msg');
            if (msgEl) msgEl.textContent = message;
        }
        el.classList.remove('hidden');
    } else {
        el.classList.add('hidden');
    }
}

let _exchangeInflight = null;

async function _doExchange() {
    if (getToken()) return true;
    const mode = getMode();
    if (!mode) return false;
    try {
        let res;
        if (mode === 'google') {
            const idToken = getGoogleIdToken();
            if (!idToken) return false;
            res = await fetch(api('/api/auth/google'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ id_token: idToken }),
            });
        } else {
            res = await fetch(api('/api/auth/guest'), {
                method: 'POST',
                credentials: 'include',
            });
        }
        if (!res.ok) return false;
        const data = await res.json().catch(() => ({}));
        if (data.token) { setToken(data.token); return true; }
        return false;
    } catch {
        // Network-level failure (backend down, CORS, mixed content, …).
        return false;
    }
}

export function ensureBackendSession() {
    // De-dupe concurrent first-call exchanges (a fresh page tends to fire
    // /sessions and /auth/me roughly simultaneously).
    if (_exchangeInflight) return _exchangeInflight;
    _exchangeInflight = _doExchange()
        .then((ok) => {
            // Banner is meaningful only after the user has picked an identity.
            // Before that the gate is up and covers everything.
            if (getMode()) setNoBackendBanner(!ok);
            return ok;
        })
        .finally(() => { _exchangeInflight = null; });
    return _exchangeInflight;
}

// ── Fetch wrapper ───────────────────────────────────────────────────────

export async function apiFetch(url, options = {}) {
    // Mint a backend session lazily if we have a client-side identity but
    // no backend token yet. Skip auth endpoints themselves to avoid
    // recursion.
    const isAuthEndpoint = /\/api\/auth\/(guest|google|status|me|logout)\b/.test(url);
    if (!isAuthEndpoint && !getToken() && getMode()) {
        const ok = await ensureBackendSession();
        if (!ok) {
            // Backend is unreachable — fail fast with a message that tells
            // the user what to do, instead of letting the network request
            // proceed and surface a generic "Failed to fetch".
            throw new Error('Backend not connected. Set the Backend URL in Settings.');
        }
    }
    const token = getToken();
    const headers = new Headers(options.headers || {});
    if (token && !headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${token}`);
    }
    return fetch(url, { credentials: 'include', ...options, headers });
}
