// URL builders + a thin fetch wrapper that always sends auth cookies.
//
// `credentials: 'include'` is mandatory for cross-origin Mode B deployments
// (Netlify static frontend → remote backend) so the `pr_guest` / `pr_auth`
// cookies actually traverse the origin boundary. Same-origin requests behave
// identically with this flag, so the default is safe everywhere.

import { config } from './config.js';

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
    return fetch(url, { credentials: 'include', ...options });
}
