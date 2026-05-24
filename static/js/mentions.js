// @-mention autocomplete popup over the chat textarea.

import { escapeHtml } from './config.js';
import { autoResizeTextArea } from './ui.js';

let sessionDocs = [];
let atMentionActive = false;
let atMentionStart = -1;
let atSelectedIdx = 0;

export function setSessionDocs(docs) {
    sessionDocs = docs || [];
}

export function handleAtMention(textarea) {
    const val = textarea.value;
    const pos = textarea.selectionStart;

    // Walk left from the cursor to find the most recent unescaped '@'.
    let searchFrom = pos - 1;
    let atPos = -1;
    while (searchFrom >= 0) {
        if (val[searchFrom] === '@') { atPos = searchFrom; break; }
        if (val[searchFrom] === ' ' || val[searchFrom] === '\n') break;
        searchFrom--;
    }

    if (atPos === -1) { hideAtPopup(); return; }

    const typed = val.slice(atPos + 1, pos).toLowerCase();
    const matches = sessionDocs.filter(d => d.toLowerCase().includes(typed));

    if (matches.length === 0) { hideAtPopup(); return; }

    atMentionActive = true;
    atMentionStart  = atPos;
    atSelectedIdx   = 0;
    renderAtPopup(matches);
}

function renderAtPopup(matches) {
    const popup = document.getElementById('at-mention-popup');
    popup.innerHTML = matches.map((d, i) => {
        const ext = d.split('.').pop().toUpperCase();
        const extColors = { PDF: 'text-red-500', DOCX: 'text-blue-500', TXT: 'text-slate-500', CSV: 'text-emerald-600' };
        const col = extColors[ext] || 'text-indian-red';
        const esc = escapeHtml(d);
        return `<div class="at-mention-item ${i === 0 ? 'selected' : ''}" data-idx="${i}" data-filename="${esc}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="${col} flex-shrink-0"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
            <span class="truncate flex-1">${esc}</span>
            <span class="at-badge">${escapeHtml(ext)}</span>
        </div>`;
    }).join('');
    popup.querySelectorAll('.at-mention-item').forEach(el => {
        el.addEventListener('mousedown', () => insertAtMention(el.dataset.filename));
    });
    popup.classList.remove('hidden');
}

export function hideAtPopup() {
    atMentionActive = false;
    document.getElementById('at-mention-popup').classList.add('hidden');
}

export function handleAtMentionKey(e) {
    if (!atMentionActive) return;
    const popup = document.getElementById('at-mention-popup');
    const items = popup.querySelectorAll('.at-mention-item');
    if (items.length === 0) return;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        atSelectedIdx = Math.min(atSelectedIdx + 1, items.length - 1);
        items.forEach((el, i) => el.classList.toggle('selected', i === atSelectedIdx));
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        atSelectedIdx = Math.max(atSelectedIdx - 1, 0);
        items.forEach((el, i) => el.classList.toggle('selected', i === atSelectedIdx));
    } else if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const sel = items[atSelectedIdx];
        if (sel) insertAtMention(sel.dataset.filename);
    } else if (e.key === 'Escape') {
        hideAtPopup();
    }
}

function insertAtMention(filename) {
    const textarea = document.getElementById('message-input');
    const val = textarea.value;
    const pos = textarea.selectionStart;
    const before = val.slice(0, atMentionStart);
    const after  = val.slice(pos);
    // Filenames with spaces must be quoted so the backend regex @"..." matches them.
    const tag = filename.includes(' ') ? `"${filename}"` : filename;
    textarea.value = before + '@' + tag + ' ' + after;
    const newPos = atMentionStart + tag.length + 2;
    textarea.setSelectionRange(newPos, newPos);
    textarea.focus();
    hideAtPopup();
    autoResizeTextArea(textarea);
}
