// Multi-file upload: posts to /api/upload, then reloads the session.

import { config, state } from './config.js';
import { api, apiFetch } from './api.js';
import { appendMessage } from './chat.js';
import { loadSessionHistory } from './sessions.js';

// Mirrors backend.config.ALLOWED_EXTENSIONS — used to silently skip files
// inside a webkitdirectory upload that the backend would reject anyway
// (.DS_Store, .git/*, binary blobs, etc.).
const ALLOWED_EXTS = new Set([
    '.pdf',
    '.txt', '.md', '.rst', '.log',
    '.csv', '.tsv',
    '.json', '.jsonl',
    '.yaml', '.yml',
    '.xml', '.html', '.htm',
    '.docx', '.doc',
    '.pptx', '.ppt',
    '.xlsx', '.xls',
]);

function extOf(name) {
    const i = name.lastIndexOf('.');
    return i < 0 ? '' : name.slice(i).toLowerCase();
}

export async function uploadFiles(files) {
    const all = Array.from(files);
    // A folder pick can include hundreds of dotfiles and unsupported types;
    // filter to the supported set so we don't spam the chat with "Unsupported
    // file type" responses for every .DS_Store.
    const accepted = all.filter(f => {
        const rel = f.webkitRelativePath || f.name;
        if (rel.split('/').some(seg => seg.startsWith('.'))) return false;
        return ALLOWED_EXTS.has(extOf(f.name));
    });
    const skipped = all.length - accepted.length;
    if (accepted.length === 0) {
        appendMessage('assistant', `No supported documents in selection (got ${all.length} files).`);
        return;
    }
    if (skipped > 0) {
        appendMessage('assistant', `Skipping ${skipped} unsupported / hidden file${skipped === 1 ? '' : 's'} in selection.`);
    }
    for (const file of accepted) {
        await uploadFile(file);
    }
}

async function uploadFile(file) {
    if (!file) return;
    // Reset both file inputs so the same file/folder can be re-uploaded.
    const fi = document.getElementById('file-input');
    const di = document.getElementById('folder-input');
    if (fi) fi.value = '';
    if (di) di.value = '';

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
    // webkitdirectory uploads carry the folder-relative path so the UI can
    // still tell "foo/report.pdf" and "bar/report.pdf" apart.
    const relPath = file.webkitRelativePath || '';
    if (relPath) formData.append('relative_path', relPath);

    const label = relPath || file.name;
    appendMessage('assistant', `Indexing **${label}**…`);
    try {
        const res    = await apiFetch(api('/api/upload'), { method: 'POST', body: formData });
        const result = await res.json();
        appendMessage('assistant', result.message);
        await loadSessionHistory(state.currentSessionId);
    } catch (err) { appendMessage('assistant', `Upload failed: ${err.message}`); }
}
