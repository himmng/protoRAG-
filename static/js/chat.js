// Streaming chat: form submit, SSE reader, send/stop button state, message rendering.

import { config, state, escapeHtml } from './config.js';
import { api, apiFetch } from './api.js';
import { loadSessions } from './sessions.js';

export const streamState = { isStreaming: false, abortController: null };

export function updateSendStopBtn() {
    const btn = document.getElementById('send-stop-btn');
    if (!btn) return;
    if (streamState.isStreaming) {
        btn.title = 'Stop response';
        btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="18" height="18" rx="2.5"/></svg>`;
        btn.onclick = (e) => { e.preventDefault(); if (streamState.abortController) streamState.abortController.abort(); };
    } else {
        btn.title = 'Send message';
        btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>`;
        btn.onclick = (e) => { e.preventDefault(); document.getElementById('chat-form').requestSubmit(); };
    }
}

export function appendMessage(role, content) {
    const container = document.getElementById('messages');
    const div   = document.createElement('div');

    if (role === 'system_notice') {
        // Centered red pill — visually distinct from chat bubbles. Marks
        // server-emitted chat ↔ RAG mode transitions; never markdown-parsed.
        div.className = 'flex justify-center animate-fade-in my-3';
        const inner = document.createElement('div');
        inner.className = 'px-4 py-2 rounded-full bg-indian-red/10 text-indian-red text-[12px] font-semibold tracking-wide border border-indian-red/20 select-none text-center max-w-[90%]';
        inner.textContent = content;
        div.appendChild(inner);
        container.appendChild(div);
        document.getElementById('chat-container').scrollTo({ top: 999999, behavior: 'smooth' });
        return inner;
    }

    div.className = `flex ${role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in`;
    const inner = document.createElement('div');
    inner.className = `max-w-[90%] md:max-w-[85%] p-4 rounded-2xl ${role === 'user' ? 'bg-indian-red text-white rounded-tr-none shadow-md' : 'glass-pill dark:text-slate-100 rounded-tl-none'} prose dark:prose-invert prose-sm`;
    inner.innerHTML = content.includes('animate-gear') ? content : DOMPurify.sanitize(marked.parse(content));
    div.appendChild(inner);
    container.appendChild(div);
    document.getElementById('chat-container').scrollTo({ top: 999999, behavior: 'smooth' });
    return inner;
}

export function renderSourcesFooter(parentInner, sources) {
    if (!sources || !sources.length) return;
    const foot = document.createElement('div');
    foot.className = 'mt-3 pt-2 border-t border-slate-200/60 dark:border-slate-700/60 text-[11px] text-slate-500 dark:text-slate-400 select-none not-prose';
    const chips = sources.map(s =>
        `<span class="inline-block px-2 py-0.5 mr-1 mb-1 rounded-md bg-slate-100 dark:bg-slate-800 font-mono">${escapeHtml(s)}</span>`
    ).join('');
    foot.innerHTML = `<span class="font-bold uppercase tracking-widest mr-2">Sources</span>${chips}`;
    parentInner.appendChild(foot);
}

export function initChatForm() {
    document.getElementById('chat-form').onsubmit = async (e) => {
        e.preventDefault();
        if (streamState.isStreaming) return;

        const input = document.getElementById('message-input');
        const msg   = input.value.trim();
        if (!msg) return;

        input.value = '';
        input.style.height = '48px';
        document.getElementById('welcome-msg')?.remove();
        appendMessage('user', msg);

        const assistantMsgDiv = appendMessage('assistant', `
            <div class="flex items-center gap-3">
                <svg width="24" height="24" viewBox="0 0 100 100" class="animate-gear flex-shrink-0">
                    <path d="M50 15C58 15 65 22 65 30C73 30 80 37 80 45C80 53 73 60 65 60C65 68 58 75 50 75C42 75 35 68 35 60C27 60 20 53 20 45C20 37 27 30 35 30C35 22 42 15 50 15Z" fill="#CD5C5C"/>
                    <circle cx="50" cy="45" r="8" fill="#CD5C5C" stroke="white" stroke-width="2"/>
                </svg>
                <span class="text-[11px] font-medium text-gray-400 dark:text-slate-500 uppercase tracking-widest loading-dots">Thinking</span>
            </div>
        `);

        streamState.isStreaming = true;
        streamState.abortController = new AbortController();
        updateSendStopBtn();

        let fullText = "";
        let pendingSources = null;
        try {
            const response = await apiFetch(api('/api/chat'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                signal: streamState.abortController.signal,
                body: JSON.stringify({
                    session_id: state.currentSessionId,
                    message: msg,
                    data_dir: config.data_dir || null,
                    config: {
                        provider:        config.provider,
                        base_url:        config.base_url,
                        api_key:         config.api_key,
                        model_name:      config.model_name,
                        embedding_model: config.embedding_model,
                    }
                })
            });

            const reader  = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                const lines = decoder.decode(value).split('\n');
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.slice(6);
                    if (dataStr === '[DONE]') break;
                    try {
                        const parsed = JSON.parse(dataStr);
                        if (parsed.type === 'sources') {
                            pendingSources = parsed.files || [];
                            continue;
                        }
                        // Guard: non-content events (e.g. future control messages)
                        // shouldn't corrupt the text buffer with `undefined`.
                        if (typeof parsed.content !== 'string') continue;
                        if (fullText === "") assistantMsgDiv.innerHTML = "";
                        fullText += parsed.content;
                        assistantMsgDiv.innerHTML = DOMPurify.sanitize(marked.parse(fullText));
                    } catch (_) {}
                }
            }
            if (pendingSources && pendingSources.length) {
                renderSourcesFooter(assistantMsgDiv, pendingSources);
            }
            loadSessions();
        } catch (err) {
            if (err.name === 'AbortError') {
                if (fullText) {
                    assistantMsgDiv.innerHTML = DOMPurify.sanitize(marked.parse(fullText))
                        + '<p class="text-[11px] text-gray-400 dark:text-slate-500 mt-2 select-none">■ stopped</p>';
                } else {
                    assistantMsgDiv.innerHTML = '<em class="text-gray-400 dark:text-slate-500">Response stopped.</em>';
                }
            } else {
                assistantMsgDiv.innerHTML = `<span class="text-red-500">Error: ${err.message}</span>`;
            }
        } finally {
            streamState.isStreaming = false;
            streamState.abortController = null;
            updateSendStopBtn();
        }
    };
}
