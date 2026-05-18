// Streaming chat: form submit, SSE reader, send/stop button state, message rendering.

import { config, state } from './config.js';
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
    div.className = `flex ${role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in`;
    const inner = document.createElement('div');
    inner.className = `max-w-[90%] md:max-w-[85%] p-4 rounded-2xl ${role === 'user' ? 'bg-indian-red text-white rounded-tr-none shadow-md' : 'bg-gray-100 dark:bg-slate-800 dark:text-slate-100 rounded-tl-none border border-gray-200 dark:border-slate-700 shadow-sm'} prose dark:prose-invert prose-sm`;
    inner.innerHTML = content.includes('animate-gear') ? content : DOMPurify.sanitize(marked.parse(content));
    div.appendChild(inner);
    container.appendChild(div);
    document.getElementById('chat-container').scrollTo({ top: 999999, behavior: 'smooth' });
    return inner;
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
                        if (fullText === "") assistantMsgDiv.innerHTML = "";
                        fullText += parsed.content;
                        assistantMsgDiv.innerHTML = DOMPurify.sanitize(marked.parse(fullText));
                    } catch (_) {}
                }
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
