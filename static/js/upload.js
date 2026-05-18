// Multi-file upload: posts to /api/upload, then reloads the session.

import { config, state } from './config.js';
import { api, apiFetch } from './api.js';
import { appendMessage } from './chat.js';
import { loadSessionHistory } from './sessions.js';

export async function uploadFiles(files) {
    for (const file of Array.from(files)) {
        await uploadFile(file);
    }
}

async function uploadFile(file) {
    if (!file) return;
    // Reset file input so the same file can be re-uploaded.
    document.getElementById('file-input').value = '';

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', state.currentSessionId);
    // Explicitly append each config field (not the backend_url).
    formData.append('provider',        config.provider);
    formData.append('base_url',        config.base_url);
    formData.append('api_key',         config.api_key);
    formData.append('model_name',      config.model_name);
    formData.append('embedding_model', config.embedding_model);
    if (config.data_dir) formData.append('data_dir', config.data_dir);

    appendMessage('assistant', `Indexing **${file.name}**…`);
    try {
        const res    = await apiFetch(api('/api/upload'), { method: 'POST', body: formData });
        const result = await res.json();
        appendMessage('assistant', result.message);
        await loadSessionHistory(state.currentSessionId);
    } catch (err) { appendMessage('assistant', `Upload failed: ${err.message}`); }
}
