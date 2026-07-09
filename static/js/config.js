// Provider/UI defaults, the persisted config singleton, and currentSessionId.

// Google OAuth client ID is public — shipping it with the frontend is what
// lets the gate render the Google button BEFORE any backend is reachable.
// The matching secret is never used here (GIS is the client-side flow).
// Override per-deployment by setting `window.PROTORAG_GOOGLE_CLIENT_ID`
// before main.js loads, or leave blank to fall back to the value the
// backend reports via /api/auth/status once one is configured.
export const PUBLIC_GOOGLE_CLIENT_ID =
    (typeof window !== 'undefined' && window.PROTORAG_GOOGLE_CLIENT_ID) ||
    '970498019467-97pb8cvibpo6nocudk7jhu6nthfasi2r.apps.googleusercontent.com';

// Default backend the "Connect with backend" gate button points at. No
// portable default exists across deployments (every deployer's backend URL
// is different), so this intentionally defaults to same-origin (empty
// string) — correct for "open http://localhost:8000 directly" or "index.html
// served by the same backend it talks to". Netlify-hosted frontends talking
// to a separate/tunneled backend must set this explicitly, either via
// Settings → Backend URL (persisted in localStorage) or by setting
// `window.PROTORAG_DEFAULT_BACKEND_URL` before main.js loads.
export const DEFAULT_BACKEND_URL =
    (typeof window !== 'undefined' && window.PROTORAG_DEFAULT_BACKEND_URL) ||
    '';

// Local-dev convenience: `python3 -m frontend` serves the SPA on its own
// port (e.g. :4444), separate from `python -m backend` / uvicorn on :8000.
// Same-origin would then point at the frontend's own static server, which
// has no API — so when the page itself is on localhost/127.0.0.1 and NOT
// already on :8000 (that case is same-origin-correct, e.g. Docker's bundled
// UI), guess the backend lives on the same host at the default port 8000.
// Never applies off localhost (Netlify, etc.) — there's no such convention
// to guess there, and DEFAULT_BACKEND_URL above already covers explicit
// overrides for that case.
function _guessLocalBackendUrl() {
    if (typeof window === 'undefined' || !window.location) return '';
    const { hostname, port, protocol } = window.location;
    const isLocalHost = hostname === 'localhost' || hostname === '127.0.0.1';
    if (!isLocalHost || !port || port === '8000') return '';
    return `${protocol}//${hostname}:8000`;
}

// What the gate's "Connect with backend" button and the initial config
// singleton should actually use: an explicit override always wins, and
// local dev falls back to the same-host-port-8000 guess above. Exported
// separately from DEFAULT_BACKEND_URL so callers get the guess too instead
// of re-deriving (or forgetting) it themselves.
export const EFFECTIVE_DEFAULT_BACKEND_URL = DEFAULT_BACKEND_URL || _guessLocalBackendUrl();

// LLM/embedding provider URL the bundled backend uses to reach Ollama. The
// backend runs in Docker on the my-ubuntu host, and Ollama runs on that same
// host, so "localhost" inside the container is wrong — it must use the docker
// host-gateway alias (see `extra_hosts` in docker-compose.local.yml). This is
// resolved server-side by the backend, never by the browser.
// Override per-deployment with `window.PROTORAG_DEFAULT_OLLAMA_URL`.
export const DEFAULT_OLLAMA_BASE_URL =
    (typeof window !== 'undefined' && window.PROTORAG_DEFAULT_OLLAMA_URL) ||
    'http://host.docker.internal:11434';

export const PROVIDER_DEFAULTS = {
    ollama:    { base_url: DEFAULT_OLLAMA_BASE_URL,      api_key: 'none',      hint: 'Auto-appends /v1 · needs OLLAMA_ORIGINS set' },
    lmstudio:  { base_url: 'http://localhost:1234',      api_key: 'lm-studio', hint: 'Auto-appends /v1 · LM Studio server mode' },
    openai:    { base_url: 'https://api.openai.com/v1',  api_key: '',          hint: 'Include /v1 in URL · real API key required' },
    litellm:   { base_url: 'http://localhost:4000',      api_key: 'any',       hint: 'Proxy root · /v1 added by LiteLLM automatically' },
    anthropic: { base_url: 'http://localhost:11434/v1',  api_key: '',          hint: 'LLM → Anthropic API · Base URL = embedding service (e.g. Ollama /v1)' },
    custom:    { base_url: '',                            api_key: '',          hint: 'Use the exact endpoint your server expects' },
};

export const URL_HINTS = {
    ollama:    'e.g. http://localhost:11434 or your tailscale/cloudflared URL',
    lmstudio:  'e.g. http://localhost:1234',
    openai:    'e.g. https://api.openai.com/v1',
    litellm:   'e.g. http://localhost:4000',
    anthropic: 'Embedding service URL — e.g. http://localhost:11434/v1 (Ollama)',
    custom:    'Full base URL including path if needed',
};

// Mutable singleton — modules read/write fields on this object directly so
// updates propagate without any per-module wiring.
export const config = {
    backend_url:     EFFECTIVE_DEFAULT_BACKEND_URL,
    data_dir:        '',
    provider:        'ollama',
    base_url:        DEFAULT_OLLAMA_BASE_URL,
    api_key:         'none',
    model_name:      'gemma-4-e4b:latest',
    embedding_model: 'embeddinggemma:latest',
};

const savedConfig = localStorage.getItem('app_config');
if (savedConfig) {
    const parsed = JSON.parse(savedConfig);
    // A blank/missing saved backend_url (e.g. persisted by an older build
    // before the local-dev guess existed, or never set) shouldn't override
    // the freshly computed default above — only a real explicit value should.
    if (!parsed.backend_url) delete parsed.backend_url;
    Object.assign(config, parsed);
}

// Wrapped so `state.currentSessionId` always reflects the latest assignment.
// (Exporting a `let` binding works too, but the wrapper keeps every caller on
// the same path: read `state.currentSessionId`, write `setCurrentSessionId(...)`.)
export const state = {
    currentSessionId: localStorage.getItem('last_session_id') || crypto.randomUUID(),
    sessionDocs: [],
};

export function setCurrentSessionId(sid) {
    state.currentSessionId = sid;
    localStorage.setItem('last_session_id', sid);
}

export function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
