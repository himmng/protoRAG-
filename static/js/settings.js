// Settings modal, provider-defaults toggling, backend health probe, dark mode.

import { ensureBackendSession, getMode, setToken } from './api.js';
import { config, fetchBackendProviderDefaults, PROVIDER_DEFAULTS, URL_HINTS, state } from './config.js';
import { loadSessions, loadSessionHistory } from './sessions.js';

export function onProviderChange(provider) {
    const defaults = PROVIDER_DEFAULTS[provider] || PROVIDER_DEFAULTS.custom;
    const urlInput  = document.getElementById('config-url');
    const keyInput  = document.getElementById('config-key');
    const hintEl    = document.getElementById('provider-hint');
    const urlHintEl = document.getElementById('url-hint');
    urlInput.value        = defaults.base_url;
    keyInput.value        = defaults.api_key;
    urlInput.placeholder  = URL_HINTS[provider] || '';
    hintEl.textContent    = defaults.hint;
    urlHintEl.textContent = URL_HINTS[provider] || '';
}

export async function testBackendConnection() {
    const dot    = document.getElementById('config-backend-dot');
    const status = document.getElementById('config-backend-status');
    const raw    = document.getElementById('config-backend').value.trim().replace(/\/$/, '');
    const target = (raw || window.location.origin) + '/api/health';

    dot.className = 'inline-block w-2 h-2 rounded-full bg-yellow-400 animate-pulse';
    status.textContent = 'Checking ' + target + '…';
    status.className = 'text-[10px] text-gray-400 mt-1';

    try {
        const ctrl  = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 5000);
        const res   = await fetch(target, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json().catch(() => ({}));
        const gotDefaults = await fetchBackendProviderDefaults(raw || window.location.origin);
        if (gotDefaults) updateConfigUI();
        dot.className = 'inline-block w-2 h-2 rounded-full bg-green-500';
        status.textContent = 'Connected — ' + (data.service || 'backend reachable')
            + (gotDefaults ? ' (provider settings loaded from backend)' : '');
        status.className = 'text-[10px] text-green-600 dark:text-green-400 mt-1';
    } catch (err) {
        dot.className = 'inline-block w-2 h-2 rounded-full bg-red-500';
        let msg;
        if (err.name === 'AbortError') {
            msg = 'timeout (5s) — backend not running?';
        } else if (err instanceof TypeError) {
            // Browser refused the request before it ever left. Most common
            // causes when target is http://localhost from an HTTPS page:
            //   • backend not running on that port
            //   • CORS preflight rejected (PROTORAG_CORS_ORIGINS missing the
            //     Netlify origin)
            //   • Private Network Access preflight not approved
            // The native error string is identical in all three, so we list
            // the checks rather than guess.
            const isLocal = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(raw);
            msg = 'blocked by browser. Check: backend is running, '
                + (isLocal ? 'and ' : 'CORS allows this origin, and ')
                + 'open the README "Local backend" section for the docker compose command.';
        } else {
            msg = err.message || 'unreachable';
        }
        status.textContent = 'Cannot reach ' + target + ' — ' + msg;
        status.className = 'text-[10px] text-red-600 dark:text-red-400 mt-1';
    }
}

export function toggleSettingsModal() {
    const modal = document.getElementById('settings-modal');
    const opening = modal.classList.contains('hidden');
    // Re-sync the form from the live config each time the modal opens so it
    // reflects defaults applied after page load (e.g. the gate's "Connect
    // with backend" step). Otherwise Save would write back stale field values.
    if (opening) updateConfigUI();
    modal.classList.toggle('hidden');
}

export function toggleDocsModal() {
    document.getElementById('docs-modal').classList.toggle('hidden');
}

export function updateConfigUI() {
    document.getElementById('config-backend').value  = config.backend_url || '';
    document.getElementById('config-data-dir').value = config.data_dir || '';
    document.getElementById('config-provider').value = config.provider;
    document.getElementById('config-url').value      = config.base_url;
    document.getElementById('config-key').value      = config.api_key;
    document.getElementById('config-model').value    = config.model_name;
    document.getElementById('config-embed').value    = config.embedding_model;
    onProviderChange(config.provider);
    // Re-set after onProviderChange resets them to defaults.
    document.getElementById('config-url').value = config.base_url;
    document.getElementById('config-key').value = config.api_key;
}

export async function saveSettings() {
    const prevBackendUrl = config.backend_url;
    const prevDataDir = config.data_dir;
    config.backend_url     = document.getElementById('config-backend').value.trim();
    config.data_dir        = document.getElementById('config-data-dir').value.trim();
    config.provider        = document.getElementById('config-provider').value;
    config.base_url        = document.getElementById('config-url').value.trim();
    config.api_key         = document.getElementById('config-key').value.trim();
    config.model_name      = document.getElementById('config-model').value.trim();
    config.embedding_model = document.getElementById('config-embed').value.trim();
    localStorage.setItem('app_config', JSON.stringify(config));
    toggleSettingsModal();

    // If the backend URL just changed, the old token (if any) was minted by
    // a different backend and can't be reused. Drop it so the next API
    // call mints a fresh session against the new backend.
    if (prevBackendUrl !== config.backend_url) setToken(null);

    // Re-attempt the backend session against (possibly new) URL. Updates
    // the no-backend banner as a side-effect. Only meaningful once the
    // user has picked an identity at the gate.
    if (getMode()) await ensureBackendSession();

    if (prevBackendUrl !== config.backend_url || prevDataDir !== config.data_dir) {
        try {
            await loadSessions();
            await loadSessionHistory(state.currentSessionId);
        } catch { /* banner already surfaces the unreachable case */ }
    }
}

export function toggleDarkMode() {
    const isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
}
