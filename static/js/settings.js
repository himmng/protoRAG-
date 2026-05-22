// Settings modal, provider-defaults toggling, backend health probe, dark mode.

import { config, PROVIDER_DEFAULTS, URL_HINTS, state } from './config.js';
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
        dot.className = 'inline-block w-2 h-2 rounded-full bg-green-500';
        status.textContent = 'Connected — ' + (data.service || 'backend reachable');
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
    document.getElementById('settings-modal').classList.toggle('hidden');
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

export function saveSettings() {
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
    // If the data dir changed, reload sessions from the new location.
    if (prevDataDir !== config.data_dir) {
        loadSessions();
        loadSessionHistory(state.currentSessionId);
    }
}

export function toggleDarkMode() {
    const isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
}
