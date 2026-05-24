// Google sign-in + user-profile pill in the sidebar.
//
// Flow:
//   1. `bootAuth()` calls `/api/auth/status` (non-minting). If no session,
//      show the gate overlay and resolve only after the user picks "Continue
//      as guest" or signs in with Google.
//   2. Once a session exists, render the sidebar pill via `refreshAuthUI()`.

import { api, apiFetch, setToken } from './api.js';
import { escapeHtml, state } from './config.js';
import { loadSessions, loadSessionHistory } from './sessions.js';

const GIS_SRC = 'https://accounts.google.com/gsi/client';
let gisLoadingPromise = null;

// Lucide-style monoline glyphs. The user_id maps to one deterministically,
// so a guest's avatar stays stable across reloads but differs guest-to-guest.
const GUEST_ICONS = [
    '<path d="M9 10h.01"/><path d="M15 10h.01"/><path d="M12 2a8 8 0 0 0-8 8v12l3-3 2.5 2.5L12 19l2.5 2.5L17 19l3 3V10a8 8 0 0 0-8-8z"/>',  // ghost
    '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.287 1.288L3 12l5.8 1.9a2 2 0 0 1 1.288 1.287L12 21l1.9-5.8a2 2 0 0 1 1.287-1.288L21 12l-5.8-1.9a2 2 0 0 1-1.288-1.287Z"/>',  // sparkles
    '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',  // star
    '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',  // moon
    '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',  // compass
    '<path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z"/><line x1="16" y1="8" x2="2" y2="22"/><line x1="17.5" y1="15" x2="9" y2="15"/>',  // feather
    '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19.2 2.96c1.4 9.3-3.6 15.8-8.2 17.04Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6"/>',  // leaf
    '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',  // flame
    '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',  // cloud
    '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',  // bolt
    '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z"/>',  // heart
    '<line x1="12" y1="22" x2="12" y2="8"/><path d="M5 12H2a10 10 0 0 0 20 0h-3"/><circle cx="12" cy="5" r="3"/>',  // anchor
    '<path d="M6 3h12l4 6-10 13L2 9Z"/>',  // diamond
    '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09Z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>',  // rocket
    '<path d="M12 2v20M2 12h20M5 5l14 14M19 5L5 19"/>',  // compass-star
    '<path d="M3 12a9 9 0 1 0 9-9 9.74 9.74 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',  // refresh
];

function guestIcon(userId) {
    // djb2-ish hash → stable per user_id.
    let h = 0;
    for (let i = 0; i < userId.length; i++) h = ((h << 5) - h + userId.charCodeAt(i)) | 0;
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

// Official Google G mark (multicolor). Inlined so the logo always shows
// even if GIS hasn't finished loading or its button rendering is suppressed.
const GOOGLE_G_SVG = `
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
`;

function renderGuestPill(slot, user, clientId) {
    const googleBtn = clientId ? `
        <button id="sidebar-google-btn" title="Sign in with Google" class="nav-text flex-shrink-0 w-8 h-8 rounded-full bg-white border border-gray-200 dark:bg-slate-800 dark:border-slate-700 hover:border-indian-red/50 dark:hover:border-indian-red/50 flex items-center justify-center transition-colors shadow-sm">
            ${GOOGLE_G_SVG}
        </button>` : '';

    slot.innerHTML = `
        <div class="pb-3 flex items-center gap-3">
            <div class="w-8 h-8 rounded-full bg-indian-red/10 dark:bg-indian-red/20 text-indian-red flex items-center justify-center flex-shrink-0">${guestIcon(user.user_id || '')}</div>
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
        // Click our custom button → trigger GIS One Tap. If suppressed (FedCM
        // cooldown, browser policy), fall back to opening the gate which has
        // the official, always-working GIS-rendered "Continue with Google".
        document.getElementById('sidebar-google-btn')?.addEventListener('click', () => {
            google.accounts.id.prompt((notification) => {
                if (notification.isNotDisplayed?.() || notification.isSkippedMoment?.()) {
                    wireGateGoogle(clientId);
                    showGate();
                }
            });
        });
    }).catch(() => { /* fall through: button still visible, just won't open prompt */ });
}

function renderProfilePill(slot, user) {
    const initial = (user.name || user.email || '?').trim().charAt(0).toUpperCase();
    const avatar = user.picture
        ? `<img src="${escapeHtml(user.picture)}" referrerpolicy="no-referrer" class="w-8 h-8 rounded-full flex-shrink-0" alt="">`
        : `<div class="w-8 h-8 rounded-full bg-indian-red text-white flex items-center justify-center text-xs font-bold flex-shrink-0">${escapeHtml(initial)}</div>`;
    slot.innerHTML = `
        <div class="flex items-center gap-3 pb-3">
            ${avatar}
            <div class="nav-text flex-1 min-w-0">
                <div class="text-xs font-semibold text-gray-700 dark:text-slate-200 truncate">${escapeHtml(user.name || user.email)}</div>
                <div class="text-[10px] text-gray-400 dark:text-slate-500 truncate">${escapeHtml(user.email || '')}</div>
            </div>
            <button id="auth-signout-btn" title="Sign out" class="nav-text p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors flex-shrink-0">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
            </button>
        </div>`;
    document.getElementById('auth-signout-btn').addEventListener('click', signOut);
}

async function handleCredentialResponse(response) {
    try {
        const res = await apiFetch(api('/api/auth/google'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id_token: response.credential }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json().catch(() => ({}));
        if (data.token) setToken(data.token);
        hideGate();
        await refreshAuthUI();
        await loadSessions();
        if (state.currentSessionId) await loadSessionHistory(state.currentSessionId);
    } catch (err) {
        showGateError(`Sign-in failed: ${err.message}`);
        alert(`Sign-in failed: ${err.message}`);
    }
}

async function signOut() {
    try {
        await apiFetch(api('/api/auth/logout'), { method: 'POST' });
    } catch (_) { /* still clear local UI even if request failed */ }
    setToken(null);
    document.getElementById('messages').innerHTML = '';
    document.getElementById('session-list').innerHTML = '';
    document.getElementById('auth-slot').innerHTML = '';
    // Drop the user back at the gate so they can pick again.
    await bootAuth();
    await loadSessions();
}

export async function refreshAuthUI() {
    const slot = document.getElementById('auth-slot');
    if (!slot) return;
    try {
        const res = await apiFetch(api('/api/auth/me'));
        if (!res.ok) { slot.innerHTML = ''; return; }
        const data = await res.json();
        const user = data.user || {};
        const cid = data.google_client_id;
        if (user.kind === 'google') {
            renderProfilePill(slot, user);
        } else {
            renderGuestPill(slot, user, cid);
        }
    } catch (_) {
        slot.innerHTML = '';
    }
}

// ── Gate ──────────────────────────────────────────────────────────────────

function showGate() {
    const gate = document.getElementById('auth-gate');
    if (gate) gate.classList.remove('hidden');
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
              <br>Set <code>GOOGLE_CLIENT_ID</code> in the backend env to enable.
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

async function continueAsGuest() {
    try {
        const res = await apiFetch(api('/api/auth/guest'), { method: 'POST' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json().catch(() => ({}));
        if (data.token) setToken(data.token);
        hideGate();
        await refreshAuthUI();
        await loadSessions();
    } catch (err) {
        showGateError(`Could not start guest session: ${err.message}`);
    }
}

/**
 * Resolve the auth state on app load. If the user already has a session,
 * render the sidebar pill. Otherwise show the gate and resolve when the user
 * picks an option (the picker handlers themselves continue the boot flow).
 */
export async function bootAuth() {
    let data;
    try {
        const res = await apiFetch(api('/api/auth/status'));
        data = res.ok ? await res.json() : { authenticated: false };
    } catch (_) {
        data = { authenticated: false };
    }

    if (data.authenticated) {
        await refreshAuthUI();
        return { gated: false };
    }

    // Wire the gate, show it, and let user actions drive the rest.
    document.getElementById('auth-gate-guest').addEventListener('click', continueAsGuest, { once: false });
    wireGateGoogle(data.google_client_id);
    showGate();
    return { gated: true };
}
