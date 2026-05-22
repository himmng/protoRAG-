// Session list rendering, switching, deletion, and the sidebar doc-pill bar.

import { state, setCurrentSessionId, escapeHtml } from './config.js';
import { apiWithDataDir, apiFetch } from './api.js';
import { setSessionDocs } from './mentions.js';
import { appendMessage } from './chat.js';
import { openDocModal, deleteDocument } from './preview.js';

export async function loadSessions() {
    try {
        const res  = await apiFetch(apiWithDataDir('/api/sessions'));
        const data = await res.json();
        const list = document.getElementById('session-list');

        const ragIcon  = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline><circle cx="10" cy="13" r="2"></circle><line x1="12" y1="15" x2="14" y2="17"></line></svg>`;
        const chatIcon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;

        list.innerHTML = (data.sessions || []).map(s => `
            <div class="group relative flex items-center p-2.5 rounded-xl text-gray-600 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-800 cursor-pointer ${s.id === state.currentSessionId ? 'bg-gray-200/50 dark:bg-slate-800/50' : ''}" data-sid="${escapeHtml(s.id)}">
                <div class="flex-shrink-0 ${s.id === state.currentSessionId ? 'text-indian-red' : ''}">
                    ${s.is_rag ? ragIcon : chatIcon}
                </div>
                <span class="nav-text ml-4 text-sm truncate flex-1 pr-6">${escapeHtml(s.preview || 'Untitled Chat')}</span>
                <button data-del="${escapeHtml(s.id)}" class="absolute right-2 opacity-0 group-hover:opacity-100 p-1.5 hover:text-red-500 transition-all rounded-lg hover:bg-white dark:hover:bg-slate-700">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
            </div>
        `).join('');
        list.querySelectorAll('[data-sid]').forEach(el => {
            el.addEventListener('click', () => switchSession(el.dataset.sid));
        });
        list.querySelectorAll('[data-del]').forEach(el => {
            el.addEventListener('click', (e) => { e.stopPropagation(); deleteSession(el.dataset.del); });
        });
    } catch (e) { console.error(e); }
}

export function updateDocBar(docs) {
    setSessionDocs(docs);   // keep @mention autocomplete in sync
    const section = document.getElementById('sidebar-docs');
    const pills   = document.getElementById('doc-pills');
    if (!docs || docs.length === 0) { section.classList.add('hidden'); return; }
    section.classList.remove('hidden');

    const getFileIcon = (filename) => {
        const ext = (filename.split('.').pop() || '').toLowerCase();
        const colors = { pdf: 'text-red-500', xlsx: 'text-emerald-600', csv: 'text-emerald-600', xls: 'text-emerald-600', doc: 'text-blue-600', docx: 'text-blue-600', txt: 'text-slate-500' };
        return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="${colors[ext] || 'text-indian-red'} flex-shrink-0"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`;
    };

    pills.innerHTML = docs.map(d => {
        const esc = escapeHtml(d);
        return `<div class="doc-pill glass-pill flex items-center justify-between gap-2 px-2.5 py-2 rounded-xl text-[11px] font-semibold text-slate-600 dark:text-slate-300 group hover:border-indian-red/30 transition-colors animate-fade-in w-full box-border">
            <div class="flex items-center gap-2 overflow-hidden flex-1 cursor-pointer doc-open" data-filename="${esc}" title="${esc}">
                ${getFileIcon(d)}
                <span class="doc-filename truncate hover:text-indian-red transition-colors">${esc}</span>
            </div>
            <button class="doc-del flex-shrink-0 p-1 rounded-md text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-all flex items-center justify-center" data-filename="${esc}" title="Remove ${esc}">
                <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg>
            </button>
        </div>`;
    }).join('');
    pills.querySelectorAll('.doc-open').forEach(el => {
        el.addEventListener('click', () => openDocModal(el.dataset.filename));
    });
    pills.querySelectorAll('.doc-del').forEach(el => {
        el.addEventListener('click', (e) => deleteDocument(el.dataset.filename, e));
    });
}

export async function deleteSession(sid) {
    if (!confirm('Delete this session and all its documents?')) return;
    try {
        await apiFetch(apiWithDataDir(`/api/sessions/${sid}`), { method: 'DELETE' });
        if (sid === state.currentSessionId) createNewSession();
        else loadSessions();
    } catch (e) { console.error(e); }
}

export async function loadSessionHistory(sid) {
    setCurrentSessionId(sid);
    try {
        const res  = await apiFetch(apiWithDataDir(`/api/sessions/${sid}`));
        const data = await res.json();
        const container = document.getElementById('messages');
        container.innerHTML = '';
        if (!data.history || data.history.length === 0) renderWelcome();
        else data.history.forEach(msg => appendMessage(msg.role, msg.content));
        updateDocBar(data.documents || []);
        loadSessions();
    } catch (e) { console.error(e); }
}

export function createNewSession() {
    setCurrentSessionId(crypto.randomUUID());
    document.getElementById('messages').innerHTML = '';
    renderWelcome();
    updateDocBar([]);
    loadSessions();
}

export async function switchSession(sid) { await loadSessionHistory(sid); }

export function renderWelcome() {
    document.getElementById('messages').innerHTML = `
        <div id="welcome-msg" class="flex flex-col items-center justify-center min-h-[65vh] text-center animate-fade-in select-none">
            <div class="inline-flex items-center justify-center w-20 h-20 md:w-24 md:h-24 bg-indian-red/10 rounded-[2.5rem] mb-6 shadow-sm">
                <svg width="50" height="50" viewBox="0 0 100 100"><path d="M50 15C58 15 65 22 65 30C73 30 80 37 80 45C80 53 73 60 65 60C65 68 58 75 50 75C42 75 35 68 35 60C27 60 20 53 20 45C20 37 27 30 35 30C35 22 42 15 50 15Z" fill="#CD5C5C"/><circle cx="50" cy="45" r="8" fill="#CD5C5C" stroke="white" stroke-width="2"/></svg>
            </div>
            <h1 class="text-3xl md:text-4xl font-black text-gray-800 dark:text-white mb-2 tracking-tight">protoRAG⁺</h1>
            <p class="text-gray-500 dark:text-slate-400 text-base md:text-lg">Intelligent RAG with local isolation.</p>
        </div>`;
}
