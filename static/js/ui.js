// Sidebar toggles and textarea auto-resize — pure DOM helpers, no state.

export function openMobileSidebar() {
    document.getElementById('sidebar').classList.add('mobile-open');
}

export function closeMobileSidebar() {
    document.getElementById('sidebar').classList.remove('mobile-open');
}

export function toggleSidebar() {
    const s = document.getElementById('sidebar');
    if (window.innerWidth < 768) {
        s.classList.toggle('mobile-open');
    } else {
        s.classList.toggle('sidebar-expanded');
        s.classList.toggle('sidebar-collapsed');
    }
}

export function autoResizeTextArea(el) {
    el.style.height = '48px';
    el.style.height = el.scrollHeight + 'px';
}
