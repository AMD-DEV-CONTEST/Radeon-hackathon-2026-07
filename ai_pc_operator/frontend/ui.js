// ui.js — Screen-AI UI helpers
// Toast notifications, modal dialogs, theme manager, animations.
// Replaces alert()/confirm()/prompt() with polished in-app UI.

'use strict';

(function (global) {
    // ─── Theme Manager ──────────────────────────────────────────────────────
    const THEME_KEY = 'screenai_theme_v1';
    const themes = ['dark', 'light', 'midnight'];

    function getTheme() {
        return localStorage.getItem(THEME_KEY) || 'dark';
    }

    function setTheme(theme) {
        if (!themes.includes(theme)) theme = 'dark';
        localStorage.setItem(THEME_KEY, theme);
        document.documentElement.dataset.theme = theme;
        emit('theme:changed', theme);
    }

    function cycleTheme() {
        const current = getTheme();
        const idx = themes.indexOf(current);
        const next = themes[(idx + 1) % themes.length];
        setTheme(next);
        return next;
    }

    // Initialize theme on load
    setTheme(getTheme());

    // ─── Event Bus ──────────────────────────────────────────────────────────
    const listeners = new Map();
    function on(event, handler) {
        if (!listeners.has(event)) listeners.set(event, new Set());
        listeners.get(event).add(handler);
        return () => listeners.get(event).delete(handler);
    }
    function emit(event, payload) {
        const set = listeners.get(event);
        if (!set) return;
        for (const handler of set) {
            try { handler(payload); } catch (e) { console.warn(`[ui] listener for ${event} threw:`, e); }
        }
    }

    // ─── Toast Notifications ────────────────────────────────────────────────
    let toastContainer = null;

    function ensureToastContainer() {
        if (toastContainer && document.body.contains(toastContainer)) return toastContainer;
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'toast-container';
        document.body.appendChild(toastContainer);
        return toastContainer;
    }

    function toast(message, type = 'info', durationMs = 3500) {
        const container = ensureToastContainer();
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        const icon = {
            success: '✓',
            error: '✕',
            warning: '!',
            info: 'i',
        }[type] || 'i';
        el.innerHTML = `
            <span class="toast-icon">${icon}</span>
            <span class="toast-message"></span>
        `;
        el.querySelector('.toast-message').textContent = message;
        container.appendChild(el);
        requestAnimationFrame(() => el.classList.add('toast-show'));
        setTimeout(() => {
            el.classList.remove('toast-show');
            el.classList.add('toast-hide');
            setTimeout(() => el.remove(), 300);
        }, durationMs);
        return el;
    }

    // ─── Modal Dialogs ──────────────────────────────────────────────────────
    let modalOverlay = null;

    function closeModal() {
        if (modalOverlay) {
            modalOverlay.classList.add('modal-hide');
            setTimeout(() => {
                if (modalOverlay && modalOverlay.parentNode) {
                    modalOverlay.parentNode.removeChild(modalOverlay);
                }
                modalOverlay = null;
            }, 200);
        }
    }

    function showModal({ title, body, actions = [], dismissible = true }) {
        closeModal();
        modalOverlay = document.createElement('div');
        modalOverlay.className = 'modal-overlay';

        const modal = document.createElement('div');
        modal.className = 'modal';

        if (title) {
            const header = document.createElement('div');
            header.className = 'modal-header';
            const h = document.createElement('h3');
            h.textContent = title;
            header.appendChild(h);
            if (dismissible) {
                const close = document.createElement('button');
                close.className = 'modal-close';
                close.setAttribute('aria-label', 'Close');
                close.textContent = '×';
                close.addEventListener('click', closeModal);
                header.appendChild(close);
            }
            modal.appendChild(header);
        }

        const content = document.createElement('div');
        content.className = 'modal-body';
        if (typeof body === 'string') {
            content.textContent = body;
        } else if (body instanceof Node) {
            content.appendChild(body);
        }
        modal.appendChild(content);

        if (actions.length > 0) {
            const footer = document.createElement('div');
            footer.className = 'modal-footer';
            actions.forEach(action => {
                const btn = document.createElement('button');
                btn.className = `modal-btn modal-btn-${action.variant || 'default'}`;
                btn.textContent = action.label;
                btn.addEventListener('click', async () => {
                    if (action.handler) {
                        const result = await action.handler();
                        if (result !== false) closeModal();
                    } else {
                        closeModal();
                    }
                });
                footer.appendChild(btn);
            });
            modal.appendChild(footer);
        }

        modalOverlay.appendChild(modal);
        if (dismissible) {
            modalOverlay.addEventListener('click', (e) => {
                if (e.target === modalOverlay) closeModal();
            });
        }
        document.body.appendChild(modalOverlay);
        requestAnimationFrame(() => modalOverlay.classList.add('modal-show'));
        return { close: closeModal };
    }

    // ─── Confirm Dialog (replaces window.confirm) ────────────────────────────
    function confirm(message, { title = 'Confirm', confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false } = {}) {
        return new Promise((resolve) => {
            showModal({
                title,
                body: message,
                actions: [
                    { label: cancelLabel, variant: 'default', handler: () => { resolve(false); } },
                    { label: confirmLabel, variant: danger ? 'danger' : 'primary', handler: () => { resolve(true); } },
                ],
            });
        });
    }

    // ─── Prompt Dialog (replaces window.prompt) ──────────────────────────────
    function prompt(message, { title = 'Input', placeholder = '', defaultValue = '', confirmLabel = 'OK', cancelLabel = 'Cancel', type = 'text', secure = false } = {}) {
        return new Promise((resolve) => {
            const body = document.createElement('div');
            const label = document.createElement('p');
            label.className = 'modal-prompt-label';
            label.textContent = message;
            body.appendChild(label);
            const input = document.createElement('input');
            input.type = secure ? 'password' : type;
            input.className = 'modal-prompt-input';
            input.placeholder = placeholder;
            input.value = defaultValue;
            body.appendChild(input);
            setTimeout(() => input.focus(), 50);

            showModal({
                title,
                body,
                actions: [
                    { label: cancelLabel, variant: 'default', handler: () => { resolve(null); } },
                    {
                        label: confirmLabel, variant: 'primary', handler: () => {
                            resolve(input.value);
                        }
                    },
                ],
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    resolve(input.value);
                    closeModal();
                }
            });
        });
    }

    // ─── Alert Dialog (replaces window.alert) ────────────────────────────────
    function alert(message, { title = 'Notice', type = 'info' } = {}) {
        return new Promise((resolve) => {
            showModal({
                title,
                body: message,
                actions: [{ label: 'OK', variant: 'primary', handler: () => { resolve(true); } }],
            });
        });
    }

    // ─── DOM Helpers ────────────────────────────────────────────────────────
    function $(selector, root = document) { return root.querySelector(selector); }
    function $$(selector, root = document) { return Array.from(root.querySelectorAll(selector)); }

    function clearNode(node) {
        while (node.firstChild) node.removeChild(node.firstChild);
    }

    function el(tag, attrs = {}, children = []) {
        const node = document.createElement(tag);
        for (const [key, value] of Object.entries(attrs)) {
            if (key === 'class') node.className = value;
            else if (key === 'text') node.textContent = value;
            else if (key.startsWith('on') && typeof value === 'function') {
                node.addEventListener(key.slice(2).toLowerCase(), value);
            } else if (value !== null && value !== undefined) {
                node.setAttribute(key, value);
            }
        }
        for (const child of [].concat(children)) {
            if (child == null) continue;
            if (typeof child === 'string') node.appendChild(document.createTextNode(child));
            else node.appendChild(child);
        }
        return node;
    }

    function appendText(parent, tag, text, className = '') {
        const node = document.createElement(tag);
        if (className) node.className = className;
        node.textContent = text ?? '';
        parent.appendChild(node);
        return node;
    }

    // ─── Public API ─────────────────────────────────────────────────────────
    global.ScreenAI.ui = {
        theme: { get: getTheme, set: setTheme, cycle: cycleTheme, themes },
        toast,
        modal: { show: showModal, close: closeModal },
        confirm,
        prompt,
        alert,
        dom: { $, $$, clearNode, el, appendText },
        events: { on, emit },
    };
})(window);
