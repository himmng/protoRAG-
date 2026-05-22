// Google sign-in + user-profile pill in the sidebar.
//
// Flow:
//   1. `bootAuth()` calls `/api/auth/status` (non-minting). If no session,
//      show the gate overlay and resolve only after the user picks "Continue
//      as guest" or signs in with Google.
//   2. Once a session exists, render the sidebar pill via `refreshAuthUI()`.

import { api, apiFetch } from './api.js';
import { escapeHtml, state } from './config.js';
import { loadSessions, loadSessionHistory } from './sessions.js';

const GIS_SRC = 'https://accounts.google.com/gsi/client';
let gisLoadingPromise = null;

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

function renderGuestPill(slot, user, clientId) {
    slot.innerHTML = `
        <div class="pb-3 flex items-center gap-3">
            <div class="w-8 h-8 rounded-full bg-gray-200 dark:bg-slate-800 text-gray-500 dark:text-slate-400 flex items-center justify-center text-xs font-bold flex-shrink-0">?</div>
            <div class="nav-text flex-1 min-w-0">
                <div class="text-xs font-semibold text-gray-700 dark:text-slate-200">Guest</div>
            </div>
            ${clientId ? `<div id="gis-button-pill" class="nav-text flex-shrink-0"></div>` : ''}
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
        google.accounts.id.renderButton(
            document.getElementById('gis-button-pill'),
            { theme: 'outline', size: 'small', shape: 'pill', type: 'icon' },
        );
    }).catch(() => { /* fall through: button just won't appear */ });
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
