// Document inspection modal: PDF / image / Office (LibreOffice → PDF) / text.

import { state, escapeHtml } from './config.js';
import { apiWithDataDir, apiFetch } from './api.js';
import { loadSessionHistory } from './sessions.js';
import { appendMessage } from './chat.js';

export function openDocModal(filename) {
    if (!state.currentSessionId) return;
    const existing = document.getElementById('doc-modal-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'doc-modal-overlay';
    overlay.className = 'fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-md flex items-center justify-center p-4 md:p-10 animate-fade-in';
    overlay.onclick = (e) => { if (e.target === overlay) closeDocModal(); };

    const fileUrl    = apiWithDataDir(`/api/sessions/${state.currentSessionId}/documents/${encodeURIComponent(filename)}`);
    const previewUrl = apiWithDataDir(`/api/sessions/${state.currentSessionId}/documents/${encodeURIComponent(filename)}/preview`);
    const ext = (filename.split('.').pop() || '').toLowerCase();
    const officeExts = ['docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls'];

    overlay.innerHTML = `
        <div class="glass-surface relative w-full max-w-5xl h-[85vh] rounded-3xl flex flex-col overflow-hidden animate-zoom-in">
            <div class="flex items-center justify-between p-4 border-b border-slate-100/60 dark:border-slate-800/60 sticky top-0 z-10">
                <div class="flex items-center gap-3">
                    <div class="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg text-indian-red">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                    </div>
                    <div>
                        <h3 class="text-sm font-bold text-slate-800 dark:text-slate-100 truncate max-w-[160px] md:max-w-md">${filename}</h3>
                        <p class="text-[10px] text-slate-400 uppercase tracking-widest font-bold">Document Inspection</p>
                    </div>
                </div>
                <button onclick="closeDocModal()" class="p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors">
                    <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 6L6 18M6 6l12 12"/></svg>
                </button>
            </div>
            <div id="doc-modal-content-area" class="flex-1 overflow-hidden">
                <div class="flex items-center justify-center h-full"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indian-red"></div></div>
            </div>
            <div class="p-3 border-t border-slate-100/60 dark:border-slate-800/60 flex justify-end gap-2">
                <a href="${fileUrl}" download="${filename}" class="flex items-center gap-2 px-4 py-2 bg-indian-red text-white text-xs font-bold rounded-xl hover:opacity-90 transition-opacity">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    Download
                </a>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    const area = document.getElementById('doc-modal-content-area');

    if (ext === 'pdf') {
        area.innerHTML = `<iframe src="${fileUrl}" class="w-full h-full rounded-lg border-none"></iframe>`;
    } else if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) {
        area.innerHTML = `<div class="flex items-center justify-center h-full p-4"><img src="${fileUrl}" class="max-w-full max-h-full object-contain shadow-2xl rounded-lg"/></div>`;
    } else if (officeExts.includes(ext)) {
        // Server converts via LibreOffice; fetch as blob so we can show
        // a helpful error if conversion fails (e.g. soffice not installed).
        area.innerHTML = `<div class="flex flex-col items-center justify-center h-full gap-3 text-slate-500 dark:text-slate-400">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indian-red"></div>
            <p class="text-xs uppercase tracking-widest font-bold">Rendering preview…</p>
        </div>`;
        apiFetch(previewUrl).then(async (r) => {
            if (!r.ok) {
                const err = await r.json().catch(() => ({ detail: r.statusText }));
                area.innerHTML = `<div class="flex flex-col items-center justify-center h-full p-6 text-center gap-3">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="text-slate-400"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    <p class="text-sm font-semibold text-slate-700 dark:text-slate-200">Preview unavailable</p>
                    <p class="text-xs font-mono text-slate-500 dark:text-slate-400 max-w-md">${escapeHtml(err.detail || 'Conversion failed')}</p>
                    <a href="${fileUrl}" download="${escapeHtml(filename)}" class="mt-2 px-4 py-2 bg-indian-red text-white text-xs font-bold rounded-xl hover:opacity-90">Download original</a>
                </div>`;
                return;
            }
            const blob = await r.blob();
            const blobUrl = URL.createObjectURL(blob);
            area.innerHTML = `<iframe src="${blobUrl}" class="w-full h-full rounded-lg border-none"></iframe>`;
        }).catch(err => {
            area.innerHTML = `<div class="text-red-500 p-6">Failed to load preview: ${escapeHtml(err.message)}</div>`;
        });
    } else {
        apiFetch(fileUrl).then(r => r.text()).then(text => {
            area.innerHTML = `<pre class="p-6 text-sm font-mono text-slate-700 dark:text-slate-300 whitespace-pre-wrap h-full overflow-auto w-full">${text.replace(/</g, '&lt;')}</pre>`;
        }).catch(() => {
            area.innerHTML = `<div class="text-red-500 p-6">Failed to load.</div>`;
        });
    }
}

export function closeDocModal() {
    const overlay = document.getElementById('doc-modal-overlay');
    if (overlay) { overlay.classList.add('animate-fade-out'); setTimeout(() => overlay.remove(), 200); }
}

export async function deleteDocument(filename, e) {
    if (e) e.stopPropagation();
    if (!confirm(`Remove "${filename}" from this session?\n\nIts vectors will be deleted from the RAG index immediately.`)) return;
    const wasRag = (state.sessionDocs?.length || 0) > 0;
    try {
        const res = await apiFetch(
            apiWithDataDir(`/api/sessions/${state.currentSessionId}/documents/${encodeURIComponent(filename)}`),
            { method: 'DELETE' }
        );
        if (res.ok) {
            await loadSessionHistory(state.currentSessionId);
            if (wasRag && (state.sessionDocs?.length || 0) === 0) {
                appendMessage('assistant', '**Chat session resumed.** All documents have been removed — replies will no longer be grounded in any documents.');
            }
        } else {
            const err = await res.json().catch(() => ({}));
            alert(`Delete failed: ${err.detail || res.statusText}`);
        }
    } catch (err) { alert(`Failed to delete: ${err.message}`); }
}
