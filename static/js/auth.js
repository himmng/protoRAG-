// Google sign-in + user-profile pill in the sidebar.
//
// Flow:
//   1. `/api/auth/me` returns {user, google_client_id}. `user.kind` is either
//      'anonymous' (a guest cookie was issued) or 'google'.
//   2. If user is 'google', render the profile pill.
//   3. If user is 'anonymous' AND google_client_id is non-null, lazy-load
//      Google Identity Services and render the sign-in button.
//   4. If anonymous and no GOOGLE_CLIENT_ID, render nothing (graceful degrade).

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
    const shortId = (user.user_id || '').slice(0, 8);
    const signInBlock = clientId
        ? `<div id="gis-button" class="flex justify-center pt-1"></div>
           <p class="text-[10px] text-gray-400 dark:text-slate-500 text-center mt-1 nav-text">Sign in to sync sessions across devices.</p>`
        : `<p class="text-[10px] text-gray-400 dark:text-slate-500 text-center nav-text leading-snug">
              Google sign-in not configured.
              <br>Set <code>GOOGLE_CLIENT_ID</code> in the backend env to enable.
           </p>`;

    slot.innerHTML = `
        <div class="pb-3">
            <div class="flex items-center gap-3 mb-2">
                <div class="w-8 h-8 rounded-full bg-gray-200 dark:bg-slate-800 text-gray-500 dark:text-slate-400 flex items-center justify-center text-xs font-bold flex-shrink-0">?</div>
                <div class="nav-text flex-1 min-w-0">
                    <div class="text-xs font-semibold text-gray-700 dark:text-slate-200">Guest</div>
                    <div class="text-[10px] text-gray-400 dark:text-slate-500 truncate" title="${escapeHtml(user.user_id || '')}">id: ${escapeHtml(shortId)}…</div>
                </div>
            </div>
            ${signInBlock}
        </div>`;

    if (!clientId) return;

    loadGIS().then(() => {
        google.accounts.id.initialize({
            client_id: clientId,
            callback: handleCredentialResponse,
            auto_select: false,
            ux_mode: 'popup',
        });
        google.accounts.id.renderButton(
            document.getElementById('gis-button'),
            { theme: 'outline', size: 'medium', shape: 'pill', text: 'signin_with' },
        );
    }).catch((err) => {
        const target = document.getElementById('gis-button');
        if (target) target.innerHTML = `<p class="text-[10px] text-red-500 nav-text">${escapeHtml(err.message)}</p>`;
    });
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
        // Refresh the UI now that the user is authenticated. Existing guest
        // sessions (if any) were merged on the server; re-fetch the list to
        // show them under the new identity.
        await refreshAuthUI();
        await loadSessions();
        if (state.currentSessionId) await loadSessionHistory(state.currentSessionId);
    } catch (err) {
        alert(`Sign-in failed: ${err.message}`);
    }
}

async function signOut() {
    try {
        await apiFetch(api('/api/auth/logout'), { method: 'POST' });
    } catch (_) { /* still clear local UI even if request failed */ }
    // After logout, /api/auth/me will mint a fresh guest user. Refresh
    // everything so the UI reflects the empty guest state.
    await refreshAuthUI();
    await loadSessions();
    document.getElementById('messages').innerHTML = '';
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
            // Always render a guest pill so the user can see auth state at a
            // glance. The sign-in button only appears if GOOGLE_CLIENT_ID is
            // configured on the backend — otherwise we surface a hint.
            renderGuestPill(slot, user, cid);
        }
    } catch (_) {
        slot.innerHTML = '';
    }
}

export function initAuth() {
    refreshAuthUI();
}
