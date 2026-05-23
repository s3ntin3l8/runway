/**
 * Custom modal dialogs — drop-in replacements for window.alert / confirm / prompt.
 *
 * Reuses the .modal-bg / .modal HUD CSS already in input.css. Each call appends
 * a fresh instance to <body> and removes it on resolve, so stacked dialogs
 * (e.g. confirm → action fails → alert) work without any global state.
 *
 *   await showAlert(title, message)           → Promise<void>
 *   await showConfirm(title, message, opts?)  → Promise<boolean>
 *   await showPrompt(title, label, default?)  → Promise<string|null>
 */

import { escapeHTML } from './html.js';

let _zIndexCounter = 0;

function _build({ title, body, buttons, role }) {
    const wrap = document.createElement('div');
    wrap.className = 'modal-bg open';
    wrap.setAttribute('role', role || 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.style.zIndex = String(1000 + ++_zIndexCounter);

    wrap.innerHTML = `
        <div class="modal glass raised md-dialog">
            <div class="hd">
                <div></div>
                <div>
                    <div class="title">${escapeHTML(title)}</div>
                </div>
                <span class="x" data-md-cancel aria-label="Close">×</span>
            </div>
            <div class="body md-dialog-body">
                ${body}
                <div class="md-dialog-actions">${buttons}</div>
            </div>
        </div>`;
    return wrap;
}

function _attach(node, onResolve) {
    const previouslyFocused = document.activeElement;
    document.body.appendChild(node);

    const close = (result) => {
        node.removeEventListener('keydown', onKey, true);
        node.remove();
        _zIndexCounter = Math.max(0, _zIndexCounter - 1);
        if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
            previouslyFocused.focus();
        }
        onResolve(result);
    };

    const focusables = () => Array.from(node.querySelectorAll(
        'button, [href], input, [tabindex]:not([tabindex="-1"])'
    )).filter(el => !el.hasAttribute('disabled'));

    function onKey(e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            close({ cancelled: true });
        } else if (e.key === 'Tab') {
            const list = focusables();
            if (list.length === 0) return;
            const first = list[0];
            const last = list[list.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    }
    node.addEventListener('keydown', onKey, true);

    // Backdrop click cancels
    node.addEventListener('click', (e) => {
        if (e.target === node) close({ cancelled: true });
    });

    // Wire any element flagged with data-md-cancel as a cancel
    node.querySelectorAll('[data-md-cancel]').forEach(el => {
        el.addEventListener('click', () => close({ cancelled: true }));
    });

    return { node, close, focusables };
}

export function showAlert(title, message) {
    return new Promise((resolve) => {
        const node = _build({
            title,
            body: `<p class="md-dialog-msg">${escapeHTML(message ?? '')}</p>`,
            buttons: `<button class="btn-primary" data-md-ok>OK</button>`,
            role: 'alertdialog',
        });
        const { close } = _attach(node, () => resolve());
        node.querySelector('[data-md-ok]').addEventListener('click', () => close());
        requestAnimationFrame(() => node.querySelector('[data-md-ok]')?.focus());
    });
}

export function showConfirm(title, message, opts = {}) {
    const { okLabel = 'OK', cancelLabel = 'Cancel', danger = false } = opts;
    return new Promise((resolve) => {
        const okClass = danger ? 'btn-danger' : 'btn-primary';
        const node = _build({
            title,
            body: `<p class="md-dialog-msg">${escapeHTML(message ?? '')}</p>`,
            buttons: `
                <button class="btn-ghost" data-md-cancel-btn>${escapeHTML(cancelLabel)}</button>
                <button class="${okClass}" data-md-ok>${escapeHTML(okLabel)}</button>
            `,
            role: 'alertdialog',
        });
        const { close } = _attach(node, (r) => resolve(!r?.cancelled && r?.ok === true));
        node.querySelector('[data-md-ok]').addEventListener('click', () => close({ ok: true }));
        node.querySelector('[data-md-cancel-btn]').addEventListener('click', () => close({ cancelled: true }));
        requestAnimationFrame(() => node.querySelector('[data-md-ok]')?.focus());
    });
}

export function showPrompt(title, label, defaultValue = '') {
    return new Promise((resolve) => {
        const inputId = `md-prompt-input-${Math.random().toString(36).slice(2, 8)}`;
        const node = _build({
            title,
            body: `
                <label class="md-dialog-label" for="${inputId}">${escapeHTML(label ?? '')}</label>
                <input id="${inputId}" class="md-dialog-input" type="text" value="${escapeHTML(defaultValue)}" autocomplete="off">
            `,
            buttons: `
                <button class="btn-ghost" data-md-cancel-btn>Cancel</button>
                <button class="btn-primary" data-md-ok>OK</button>
            `,
        });
        const { close } = _attach(node, (r) => {
            if (r?.cancelled) return resolve(null);
            resolve(r?.value ?? null);
        });
        const input = node.querySelector('input');
        const submit = () => close({ value: input.value.trim() });
        node.querySelector('[data-md-ok]').addEventListener('click', submit);
        node.querySelector('[data-md-cancel-btn]').addEventListener('click', () => close({ cancelled: true }));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); submit(); }
        });
        requestAnimationFrame(() => {
            input.focus();
            input.select();
        });
    });
}
