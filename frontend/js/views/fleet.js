import { fetchFleet, patchSidecar, deleteSidecarAPI, triggerSidecarCollectAPI } from '../api.js';
import { buildFleetView } from '../components.js';

function escapeHTML(str) {
    if (!str) return '';
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return str.replace(/[&<>"']/g, m => map[m]);
}

export async function loadFleetView() {
    const container = document.getElementById('fleet-content');
    if (!container) return;
    container.innerHTML = '<p class="text-zinc-500 animate-pulse">Loading fleet...</p>';
    try {
        const data = await fetchFleet();
        container.innerHTML = buildFleetView(data.sidecars);
    } catch (err) {
        container.innerHTML = `<p class="text-red-400">Failed to load fleet: ${escapeHTML(err.message)}</p>`;
    }
}

export async function editSidecarName(sidecarId) {
    const newName = prompt('Enter a custom name for this sidecar:', '');
    if (newName === null) return;
    try {
        await patchSidecar(sidecarId, { custom_name: newName.trim() || null });
        await loadFleetView();
    } catch (err) {
        alert('Failed to rename: ' + err.message);
    }
}

export async function addSidecarTag(sidecarId) {
    const tag = prompt('Enter a tag for this sidecar:');
    if (!tag || !tag.trim()) return;
    try {
        const fleet = await fetchFleet();
        const sidecar = fleet.sidecars.find(s => s.sidecar_id === sidecarId);
        const tags = [...(sidecar?.tags || []), tag.trim()];
        await patchSidecar(sidecarId, { tags });
        await loadFleetView();
    } catch (err) {
        alert('Failed to add tag: ' + err.message);
    }
}

export async function deleteSidecar(sidecarId) {
    if (!confirm(`Remove sidecar "${sidecarId}" from the registry?`)) return;
    try {
        await deleteSidecarAPI(sidecarId);
        await loadFleetView();
    } catch (err) {
        alert('Failed to delete: ' + err.message);
    }
}

export async function triggerSidecarCollect(sidecarId) {
    const card = document.querySelector(`[data-sidecar="${CSS.escape(sidecarId)}"]`);
    const btn = card?.querySelector('button[title^="Run Now"]');

    const SVG_PLAY = btn?.innerHTML ?? '';
    const SVG_SPIN = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="animation:spin .7s linear infinite"><circle cx="12" cy="12" r="10" stroke-opacity=".25"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>';
    const SVG_CHECK = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    const SVG_ERR   = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    function setBtnState(svg, cls) {
        if (!btn) return;
        btn.innerHTML = svg;
        btn.className = btn.className.replace(/\btext-good-c\b|\btext-crit-c\b/g, '').trim();
        if (cls) btn.classList.add(cls);
        btn.disabled = cls === null; // null = loading
    }

    setBtnState(SVG_SPIN, null); // loading: spinner + disabled

    try {
        await triggerSidecarCollectAPI(sidecarId);
        setBtnState(SVG_CHECK, 'text-good-c');
        setTimeout(() => setBtnState(SVG_PLAY, ''), 1800);
    } catch (err) {
        setBtnState(SVG_ERR, 'text-crit-c');
        setTimeout(() => setBtnState(SVG_PLAY, ''), 2500);
    }
}

export function initFleetView() {
    // Fleet view uses inline onclick handlers in HTML
}