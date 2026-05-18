// Entry point: imports every module, exposes the handful of functions
// referenced by inline `onclick="..."` attributes in index.html, and wires
// up DOMContentLoaded init.

import * as ui from './ui.js';
import * as sessions from './sessions.js';
import * as upload from './upload.js';
import * as chat from './chat.js';
import * as preview from './preview.js';
import * as settings from './settings.js';
import * as mentions from './mentions.js';
import { initAuth } from './auth.js';
import { state } from './config.js';

// index.html uses inline `onclick="fnName()"` attributes for several controls.
// Module scope is not the global scope, so these names have to be re-exported
// on `window` for those handlers to resolve. Centralising the surface here
// keeps the HTML untouched and makes the global API explicit.
Object.assign(window, {
    openMobileSidebar:     ui.openMobileSidebar,
    closeMobileSidebar:    ui.closeMobileSidebar,
    toggleSidebar:         ui.toggleSidebar,
    autoResizeTextArea:    ui.autoResizeTextArea,
    createNewSession:      sessions.createNewSession,
    uploadFiles:           upload.uploadFiles,
    toggleSettingsModal:   settings.toggleSettingsModal,
    toggleDocsModal:       settings.toggleDocsModal,
    toggleDarkMode:        settings.toggleDarkMode,
    testBackendConnection: settings.testBackendConnection,
    onProviderChange:      settings.onProviderChange,
    saveSettings:          settings.saveSettings,
    closeDocModal:         preview.closeDocModal,
    handleAtMention:       mentions.handleAtMention,
    handleAtMentionKey:    mentions.handleAtMentionKey,
});

document.addEventListener('DOMContentLoaded', () => {
    sessions.loadSessions();
    sessions.loadSessionHistory(state.currentSessionId);
    settings.updateConfigUI();
    chat.updateSendStopBtn();
    chat.initChatForm();
    initAuth();

    const msgInput = document.getElementById('message-input');
    msgInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            document.getElementById('chat-form').requestSubmit();
        }
    });

    // Close mobile sidebar when a session row is tapped.
    document.getElementById('session-list').addEventListener('click', () => {
        if (window.innerWidth < 768) ui.closeMobileSidebar();
    });

    // Close the @-mention popup when clicking outside the chat form.
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#chat-form')) mentions.hideAtPopup();
    });
});
