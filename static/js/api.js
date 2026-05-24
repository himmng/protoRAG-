// URL builders + a thin fetch wrapper that handles cross-origin auth.
//
// Two transports are supported in parallel:
//   1. Cookies (`credentials: 'include'`) — works when the frontend and
//      backend share an origin, or when the backend is reached over HTTPS
//      with `PROTORAG_COOKIE_SECURE=true`.
//   2. Bearer token in `Authorization: Bearer …` — required when the Netlify
//      static frontend points at a local backend on `http://localhost:8000`,
//      where SameSite=None+Secure cookies behave inconsistently across
//      browsers. The token is minted by /api/auth/guest or /api/auth/google
//      and persisted in localStorage by static/js/auth.js.

import { config } from './config.js';

const TOKEN_KEY = 'pr_token';

export function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ''; }
    catch (_) { return ''; }
}

export function setToken(token) {
    try {
        if (token) localStorage.setItem(TOKEN_KEY, token);
        else localStorage.removeItem(TOKEN_KEY);
    } catch (_) { /* private mode / quota — auth still degrades to cookie path */ }
}

export function api(path) {
    return (config.backend_url || '').replace(/\/$/, '') + path;
}

// Append data_dir as a query parameter to GET/DELETE URLs.
export function apiWithDataDir(path) {
    const url = api(path);
    if (!config.data_dir) return url;
    const sep = url.includes('?') ? '&' : '?';
    return url + sep + 'data_dir=' + encodeURIComponent(config.data_dir);
}

export function apiFetch(url, options = {}) {
    const token = getToken();
    const headers = new Headers(options.headers || {});
    if (token && !headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${token}`);
    }
    return fetch(url, { credentials: 'include', ...options, headers });
}
