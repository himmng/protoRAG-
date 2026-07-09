// Auth gate + sidebar profile pill.
//
// The gate is a pure *client-side* identity choice:
//   - "Continue as guest" → `localStorage.pr_mode = 'guest'`. Done.
//   - "Continue with Google" → GIS popup returns an ID token. We store the
//     token + decoded profile in localStorage and call it a day.
// Neither path requires the backend to be running. The backend session
// token is minted lazily by api.js#ensureBackendSession the first time a
// real API call is needed.
//
// On load, if any client-side identity is present, we skip the gate and
// render the sidebar pill from local state. Backend reachability is
// checked separately by main.js (which surfaces the "configure your
// backend" banner when needed).

import {
    api, apiFetch,
    clearAuth, ensureBackendSession,
    getGoogleProfile, getMode, getToken,
    setGoogleIdToken, setGoogleProfile, setMode, setToken,
} from './api.js';
import { config, DEFAULT_OLLAMA_BASE_URL, EFFECTIVE_DEFAULT_BACKEND_URL, escapeHtml, PUBLIC_GOOGLE_CLIENT_ID, setCurrentSessionId, state } from './config.js';
import { loadSessions, loadSessionHistory } from './sessions.js';

const GIS_SRC = 'https://accounts.google.com/gsi/client';
let gisLoadingPromise = null;

// Lucide-style monoline glyphs. The user_id maps to one deterministically,
// so a guest's avatar stays stable across reloads but differs guest-to-guest.
const GUEST_ICONS = [
    '<path d="M9 10h.01"/><path d="M15 10h.01"/><path d="M12 2a8 8 0 0 0-8 8v12l3-3 2.5 2.5L12 19l2.5 2.5L17 19l3 3V10a8 8 0 0 0-8-8z"/>',
    '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.287 1.288L3 12l5.8 1.9a2 2 0 0 1 1.288 1.287L12 21l1.9-5.8a2 2 0 0 1 1.287-1.288L21 12l-5.8-1.9a2 2 0 0 1-1.288-1.287Z"/>',
    '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
    '<path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z"/><line x1="16" y1="8" x2="2" y2="22"/><line x1="17.5" y1="15" x2="9" y2="15"/>',
    '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19.2 2.96c1.4 9.3-3.6 15.8-8.2 17.04Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6"/>',
    '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
    '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z"/>',
    '<line x1="12" y1="22" x2="12" y2="8"/><path d="M5 12H2a10 10 0 0 0 20 0h-3"/><circle cx="12" cy="5" r="3"/>',
    '<path d="M6 3h12l4 6-10 13L2 9Z"/>',
    '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09Z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>',
    '<path d="M12 2v20M2 12h20M5 5l14 14M19 5L5 19"/>',
    '<path d="M3 12a9 9 0 1 0 9-9 9.74 9.74 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
];

function guestIcon(seed) {
    let h = 0;
    for (let i = 0; i < seed.length; i++) h = ((h << 5) - h + seed.charCodeAt(i)) | 0;
    const idx = Math.abs(h) % GUEST_ICONS.length;
    return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${GUEST_ICONS[idx]}</svg>`;
}

function loadGIS() {
    if (window.google?.accounts?.id) return Promise.resolve();
    if (gisLoadingPromise) return gisLoadingPromise;
    gisLoadingPromise = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = GIS_SRC;
        s.async = true;
        s.defer = true;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error('Failed to load Google Identity Services'));
        document.head.appendChild(s);
    });
    return gisLoadingPromise;
}

const GOOGLE_G_SVG = `
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
`;

// JWT decoder for the Google ID token (header.payload.signature, base64url).
// We don't verify here — that's the backend's job. We just want the
// human-readable profile (name, email, picture) for the sidebar pill.
function decodeIdToken(idToken) {
    try {
        const payload = idToken.split('.')[1];
        const b64 = payload.replace(/-/g, '+').replace(/_/g, '/');
        const json = atob(b64.padEnd(b64.length + (4 - b64.length % 4) % 4, '='));
        return JSON.parse(decodeURIComponent(escape(json)));
    } catch { return null; }
}

// ── Sidebar pill ──────────────────────────────────────────────────────

function renderGuestPill(slot, clientId, seed) {
    const googleBtn = clientId ? `
        <button id="sidebar-google-btn" title="Sign in with Google" class="nav-text flex-shrink-0 w-8 h-8 rounded-full bg-white border border-gray-200 dark:bg-slate-800 dark:border-slate-700 hover:border-indian-red/50 dark:hover:border-indian-red/50 flex items-center justify-center transition-colors shadow-sm">
            ${GOOGLE_G_SVG}
        </button>` : '';

    slot.innerHTML = `
        <div class="pb-3 flex items-center gap-3">
            <div class="w-8 h-8 rounded-full bg-indian-red/10 dark:bg-indian-red/20 text-indian-red flex items-center justify-center flex-shrink-0">${guestIcon(seed)}</div>
            <div class="nav-text flex-1 min-w-0">
                <div class="text-xs font-semibold text-gray-700 dark:text-slate-200">Guest</div>
            </div>
            ${googleBtn}
            <button id="auth-signout-btn" title="Sign out" class="nav-text p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors flex-shrink-0">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
            </button>
        </div>`;
    document.getElementById('auth-signout-btn').addEventListener('click', signOut);

    if (!clientId) return;
    loadGIS().then(() => {
        google.accounts.id.initialize({
            client_id: clientId,
            callback: handleCredentialResponse,
            auto_select: false,
            ux_mode: 'popup',
        });
        document.getElementById('sidebar-google-btn')?.addEventListener('click', () => {
            google.accounts.id.prompt((notification) => {
                if (notification.isNotDisplayed?.() || notification.isSkippedMoment?.()) {
                    wireGateGoogle(clientId);
                    showGate();
                }
            });
        });
    }).catch(() => { /* button stays visible, just won't open prompt */ });
}

function renderProfilePill(slot, profile) {
    const initial = (profile.name || profile.email || '?').trim().charAt(0).toUpperCase();
    const avatar = profile.picture
        ? `<img src="${escapeHtml(profile.picture)}" referrerpolicy="no-referrer" class="w-8 h-8 rounded-full flex-shrink-0" alt="">`
        : `<div class="w-8 h-8 rounded-full bg-indian-red text-white flex items-center justify-center text-xs font-bold flex-shrink-0">${escapeHtml(initial)}</div>`;
    slot.innerHTML = `
        <div class="flex items-center gap-3 pb-3">
            ${avatar}
            <div class="nav-text flex-1 min-w-0">
                <div class="text-xs font-semibold text-gray-700 dark:text-slate-200 truncate">${escapeHtml(profile.name || profile.email)}</div>
                <div class="text-[10px] text-gray-400 dark:text-slate-500 truncate">${escapeHtml(profile.email || '')}</div>
            </div>
            <button id="auth-signout-btn" title="Sign out" class="nav-text p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors flex-shrink-0">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
            </button>
        </div>`;
    document.getElementById('auth-signout-btn').addEventListener('click', signOut);
}

/**
 * Render the sidebar pill from local state — no backend round-trip.
 * Called after the user picks on the gate AND on every page load when
 * an identity is already stored.
 */
export function refreshAuthUI() {
    const slot = document.getElementById('auth-slot');
    if (!slot) return;
    const mode = getMode();
    updateGuestBanner(mode);
    if (mode === 'google') {
        const profile = getGoogleProfile();
        if (profile) { renderProfilePill(slot, profile); return; }
    }
    if (mode === 'guest') {
        // Seed the icon from any stable per-browser value. Token if we have
        // one (post-backend-exchange), else a localStorage-persisted nonce
        // so the same guest sees the same icon across reloads.
        let seed = getToken();
        if (!seed) {
            seed = localStorage.getItem('pr_guest_seed') || '';
            if (!seed) { seed = crypto.randomUUID(); localStorage.setItem('pr_guest_seed', seed); }
        }
        renderGuestPill(slot, PUBLIC_GOOGLE_CLIENT_ID, seed);
        return;
    }
    slot.innerHTML = '';
}

// ── Gate handlers ─────────────────────────────────────────────────────

async function handleCredentialResponse(response) {
    const idToken = response?.credential;
    if (!idToken) {
        showGateError('Sign-in failed: no credential returned.');
        return;
    }
    const claims = decodeIdToken(idToken) || {};
    const profile = {
        sub: claims.sub || '',
        email: claims.email || '',
        name: claims.name || '',
        picture: claims.picture || '',
    };
    setMode('google');
    setGoogleIdToken(idToken);
    setGoogleProfile(profile);
    // Drop any bearer token left over from a prior guest session. Without this,
    // `_doExchange` short-circuits on `if (getToken()) return true` and NEVER
    // calls /api/auth/google — so we'd stay bound to the guest user_id and the
    // Google account's real conversation history would never load.
    setToken(null);
    hideGate();
    refreshAuthUI();
    // Try to mint the backend session immediately; if the backend isn't
    // up yet, main.js shows the "configure backend" banner instead.
    await ensureBackendSession();
    try {
        await loadSessions();
        if (state.currentSessionId) await loadSessionHistory(state.currentSessionId);
    } catch { /* no-backend state is surfaced by main.js */ }
}

// Step 1 of the gate: point the app at the default backend and confirm it's
// reachable. Applies the bundled provider/model defaults too, then probes
// /api/health so the user sees a green/red result before picking an identity.
async function connectDefaultBackend() {
    // This button is an explicit promise to use the bundled default backend,
    // so force it even if a custom URL was previously configured. A backend
    // change invalidates any token minted by the old one.
    const switching = config.backend_url !== EFFECTIVE_DEFAULT_BACKEND_URL;
    config.backend_url = EFFECTIVE_DEFAULT_BACKEND_URL;
    applyDefaultBackend();
    if (switching) setToken(null);

    const btn      = document.getElementById('auth-gate-connect');
    const statusEl = document.getElementById('auth-gate-connect-status');

    const setStatus = (text, cls) => {
        if (!statusEl) return;
        statusEl.textContent = text;
        statusEl.className = 'text-[10px] text-center leading-snug ' + cls;
        statusEl.classList.remove('hidden');
    };

    if (btn) btn.disabled = true;
    setStatus('Connecting to ' + EFFECTIVE_DEFAULT_BACKEND_URL + '…', 'text-gray-400 dark:text-slate-500');

    try {
        const ctrl  = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 6000);
        const res   = await fetch(EFFECTIVE_DEFAULT_BACKEND_URL.replace(/\/$/, '') + '/api/health', { signal: ctrl.signal });
        clearTimeout(timer);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json().catch(() => ({}));
        setStatus('Connected — ' + (data.service || 'backend reachable') + '. Now sign in below.',
                  'text-green-600 dark:text-green-400');
    } catch (err) {
        const msg = err.name === 'AbortError' ? 'timed out (6s) — is the backend up?'
                  : (err instanceof TypeError) ? 'blocked by the browser — backend down, or CORS/HTTPS not allowing this origin.'
                  : (err.message || 'unreachable');
        setStatus('Could not reach ' + EFFECTIVE_DEFAULT_BACKEND_URL + ' — ' + msg
                  + ' You can still continue and fix the URL in Settings.',
                  'text-red-600 dark:text-red-400');
    } finally {
        if (btn) btn.disabled = false;
    }
}

// Write the bundled backend + provider/model defaults into the live config and
// persist them. Only fills the backend URL when none is set, so a user who
// already configured a custom backend keeps it.
function applyDefaultBackend() {
    if (!config.backend_url) config.backend_url = EFFECTIVE_DEFAULT_BACKEND_URL;
    config.provider        = config.provider        || 'ollama';
    // The bundled backend runs in Docker and reaches the host's Ollama via the
    // host-gateway alias, not the container's own localhost. Replace the stock
    // localhost default, but leave any URL the user customised in Settings.
    if (!config.base_url || config.base_url === 'http://localhost:11434') {
        config.base_url = DEFAULT_OLLAMA_BASE_URL;
    }
    config.model_name      = config.model_name      || 'gemma-4-e4b:latest';
    config.embedding_model = config.embedding_model || 'embeddinggemma:latest';
    try { localStorage.setItem('app_config', JSON.stringify(config)); } catch { /* private mode */ }
}

async function continueAsGuest() {
    // Every explicit "Continue as guest" starts a brand-new, isolated guest
    // identity. We must drop any token/identity left in localStorage by a
    // PREVIOUS guest first — otherwise `ensureBackendSession` reuses that stale
    // bearer token (its `if (getToken()) return true` short-circuit) and two
    // different people on the same browser end up sharing one user_id, and thus
    // one conversation + history. Anonymous guests are intentionally ephemeral
    // (incognito-style); persistent cross-visit history is what signing in with
    // Google is for.
    clearAuth();
    localStorage.removeItem('pr_guest_seed');   // fresh avatar for the new guest
    localStorage.removeItem('last_session_id'); // don't inherit the old chat pointer
    setMode('guest');
    // Reset the in-memory pointer to a fresh chat so the UI starts clean while
    // the new backend session is being minted.
    setCurrentSessionId(crypto.randomUUID());
    document.getElementById('messages').innerHTML = '';
    hideGate();
    refreshAuthUI();
    // Forces a fresh POST /api/auth/guest now that no token is cached, minting a
    // new anonymous user_id with its own isolated storage.
    await ensureBackendSession();
    try {
        await loadSessions();
        if (state.currentSessionId) await loadSessionHistory(state.currentSessionId);
    } catch { /* no-backend state is surfaced by main.js */ }
}

async function signOut() {
    // Best-effort backend logout. Don't block local cleanup on it.
    try { await apiFetch(api('/api/auth/logout'), { method: 'POST' }); } catch {}
    clearAuth();
    document.getElementById('messages').innerHTML = '';
    document.getElementById('session-list').innerHTML = '';
    document.getElementById('auth-slot').innerHTML = '';
    await bootAuth();
    try { await loadSessions(); } catch {}
}

// ── Gate visibility ───────────────────────────────────────────────────

// Top flyer reminding guests their chats are ephemeral. Visible only while the
// active identity is an anonymous guest; hidden for Google users (whose history
// is persisted) and while the gate is up.
function updateGuestBanner(mode) {
    const el = document.getElementById('guest-mode-banner');
    if (el) el.classList.toggle('hidden', mode !== 'guest');
}

function showGate() {
    const gate = document.getElementById('auth-gate');
    if (gate) gate.classList.remove('hidden');
    // The gate covers the app — never leave the guest flyer showing behind it.
    updateGuestBanner(null);
}

function hideGate() {
    const gate = document.getElementById('auth-gate');
    if (gate) gate.classList.add('hidden');
}

function showGateError(msg) {
    const el = document.getElementById('auth-gate-error');
    if (!el) return;
    el.textContent = msg;
    el.classList.remove('hidden');
}

function wireGateGoogle(clientId) {
    const target = document.getElementById('auth-gate-google');
    if (!target) return;
    if (!clientId) {
        target.innerHTML = `<p class="text-[11px] text-gray-400 dark:text-slate-500 text-center leading-snug">
              Google sign-in not configured.
              <br>Set <code>PROTORAG_GOOGLE_CLIENT_ID</code> in the frontend or
              <code>GOOGLE_CLIENT_ID</code> in the backend.
           </p>`;
        return;
    }
    loadGIS().then(() => {
        google.accounts.id.initialize({
            client_id: clientId,
            callback: handleCredentialResponse,
            auto_select: false,
            ux_mode: 'popup',
        });
        google.accounts.id.renderButton(
            target,
            { theme: 'outline', size: 'large', shape: 'pill', text: 'continue_with', logo_alignment: 'center', width: 360 },
        );
    }).catch((err) => {
        target.innerHTML = `<p class="text-[11px] text-red-500 text-center">${escapeHtml(err.message)}</p>`;
    });
}

/**
 * Resolve the auth state on app load. The gate is shown only if no
 * client-side identity has been chosen yet. Backend reachability is
 * orthogonal — main.js surfaces that separately.
 */
export async function bootAuth() {
    // Make sure the default backend is in place so the gate's identity buttons
    // (and any direct Google boot below) work immediately.
    applyDefaultBackend();

    // Returning Google users skip the gate / backend-connect screen entirely
    // and boot straight into the app — their identity is already established and
    // their history is persisted server-side. The gate is only for picking an
    // identity, which a signed-in Google user has already done. Their backend
    // session is minted lazily by apiFetch when main.js loads the session list.
    if (getMode() === 'google' && getGoogleProfile()) {
        hideGate();
        refreshAuthUI();
        return { gated: false };
    }

    // No identity yet, or guest mode: show the gate. Guests re-confirm on every
    // visit so each one gets a fresh, isolated session (see continueAsGuest).
    document.getElementById('auth-gate-connect').addEventListener('click', connectDefaultBackend, { once: false });
    document.getElementById('auth-gate-guest').addEventListener('click', continueAsGuest, { once: false });
    wireGateGoogle(PUBLIC_GOOGLE_CLIENT_ID);
    showGate();
    return { gated: true };
}
