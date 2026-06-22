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

// Default backend the "Connect with backend" gate button points at. This is
// the host that runs the protoRAG FastAPI server (which in turn talks to the
// Ollama provider configured below). Exposed over HTTPS on :8443 via
// `tailscale serve` (port 443 on this host is taken by Nextcloud), which
// gives a browser-trusted cert so the HTTPS Netlify page can reach it without
// a mixed-content or cert error. The matching server-side command is:
//   tailscale serve --bg --https=8443 http://127.0.0.1:8000
// Override per-deployment with `window.PROTORAG_DEFAULT_BACKEND_URL`.
export const DEFAULT_BACKEND_URL =
    (typeof window !== 'undefined' && window.PROTORAG_DEFAULT_BACKEND_URL) ||
    'https://my-ubuntu.tail8e3f2b.ts.net:8443';

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
    ollama:    { base_url: 'http://localhost:11434',     api_key: 'none',      hint: 'Auto-appends /v1 · needs OLLAMA_ORIGINS set' },
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
    backend_url:     '',
    data_dir:        '',
    provider:        'ollama',
    base_url:        'http://localhost:11434',
    api_key:         'none',
    model_name:      'gemma-4-e4b:latest',
    embedding_model: 'embeddinggemma:latest',
};

const savedConfig = localStorage.getItem('app_config');
if (savedConfig) Object.assign(config, JSON.parse(savedConfig));

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
