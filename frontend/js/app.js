import { fetchLimits } from './api.js';
import { STATE, HEALTH_CONFIG } from './state.js';
import { buildCard } from './components.js';

function renderGrid() {
    const grid = document.getElementById('grid');
    let html = '';
    let count = 0;
    
    STATE.data.forEach(item => {
        try {
            html += buildCard(item);
            count++;
        } catch (e) {
            console.error("Failed to render card for:", item, e);
        }
    });
    
    grid.innerHTML = html;
    document.getElementById('footer-count').textContent = count;
}

window.toggleConfig = function(key) {
    STATE[key] = !STATE[key];
    const btn = document.getElementById(`toggle-${key}`);
    if (btn) btn.classList.toggle('active', STATE[key]);
    if (key === 'compact') {
        document.body.classList.toggle('compact-mode', STATE[key]);
    }
    renderGrid();
}

async function loadData() {
    const grid = document.getElementById('grid');
    const loading = document.getElementById('loading');
    const errorBanner = document.getElementById('error-banner');
    const refreshBtn = document.getElementById('refresh-btn');
    const refreshIcon = document.getElementById('refresh-icon');
    const lastUpdated = document.getElementById('last-updated');

    grid.innerHTML = '';
    grid.classList.add('hidden');
    loading.classList.remove('hidden');
    errorBanner.classList.add('hidden');
    refreshBtn.disabled = true;
    refreshIcon.style.animation = 'spin 1s linear infinite';
    refreshIcon.style.transformOrigin = 'center';

    try {
        const json = await fetchLimits();
        STATE.data = json.limits;
        renderGrid();

        const now = new Date();
        lastUpdated.textContent = `Updated ${now.toLocaleTimeString()}`;
        lastUpdated.classList.remove('hidden');

    } catch (err) {
        errorBanner.classList.remove('hidden');
    } finally {
        loading.classList.add('hidden');
        grid.classList.remove('hidden');
        refreshBtn.disabled = false;
        refreshIcon.style.animation = 'none';
    }
}

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('refresh-btn').addEventListener('click', loadData);
    loadData();
});
