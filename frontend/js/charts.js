// frontend/js/charts.js
// Chart.js wrapper for the History tab usage panel.
// Depends on Chart.js being loaded globally (CDN in index.html).

let _chart = null;

const PROVIDER_COLORS = {
    anthropic: "#f59e0b",
    gemini: "#3b82f6",
    github: "#8b5cf6",
    chatgpt: "#10b981",
    opencode: "#06b6d4",
    openrouter: "#ec4899",
    minimax: "#14b8a6",
    ollama: "#94a3b8",
};

function colorFor(providerId) {
    return PROVIDER_COLORS[providerId] || "#64748b";
}

function extractLabelsAndProviders(snapshots) {
    const days = new Set();
    const providers = new Set();
    for (const s of snapshots) {
        days.add(s.timestamp.slice(0, 10));
        if (s.provider_id) providers.add(s.provider_id);
    }
    return { labels: Array.from(days).sort(), providers: Array.from(providers) };
}

function bucketByDay(snapshots) {
    // Returns { "YYYY-MM-DD": { provider_id: { sum, count } } }
    const buckets = {};
    for (const snap of snapshots) {
        if (snap.used_value == null) continue;
        const day = snap.timestamp.slice(0, 10);
        if (!buckets[day]) buckets[day] = {};
        const pid = snap.provider_id || "unknown";
        if (!buckets[day][pid]) buckets[day][pid] = { sum: 0, count: 0 };
        buckets[day][pid].sum += snap.used_value;
        buckets[day][pid].count += 1;
    }
    return buckets;
}

export function destroyCharts() {
    if (_chart) { _chart.destroy(); _chart = null; }
}

export function updateCharts(snapshots) {
    destroyCharts();

    const canvas = document.getElementById("chart-usage");
    const emptyEl = document.getElementById("chart-empty");
    if (!canvas) return;

    if (!snapshots || snapshots.length === 0) {
        emptyEl?.classList.remove("hidden");
        return;
    }
    emptyEl?.classList.add("hidden");

    const { labels, providers } = extractLabelsAndProviders(snapshots);
    const buckets = bucketByDay(snapshots);

    // Line chart (per provider)
    const datasets = providers.map(provider => {
        const color = colorFor(provider);
        return {
            label: provider.toUpperCase(),
            data: labels.map(day => {
                const b = buckets[day]?.[provider];
                // Average usage per day for this provider
                return b ? Math.round(b.sum / b.count) : null;
            }),
            borderColor: color,
            backgroundColor: color + "15",
            borderWidth: 2,
            tension: 0.3,
            spanGaps: true,
            pointRadius: 2,
            pointHoverRadius: 5,
            fill: true,
        };
    });

    const options = {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 500 },
        plugins: {
            legend: { 
                position: 'top',
                align: 'end',
                labels: { color: "#71717a", font: { size: 10, weight: 'bold' }, usePointStyle: true, boxWidth: 6 } 
            },
            tooltip: { 
                mode: "index", 
                intersect: false,
                backgroundColor: 'rgba(24, 24, 27, 0.95)',
                titleColor: '#f4f4f5',
                bodyColor: '#a1a1aa',
                borderColor: 'rgba(63, 63, 70, 0.5)',
                borderWidth: 1,
                padding: 10,
                bodyFont: { family: 'JetBrains Mono' }
            },
        },
        scales: {
            x: { 
                ticks: { color: "#52525b", font: { size: 9 }, maxTicksLimit: 7 }, 
                grid: { display: false } 
            },
            y: { 
                beginAtZero: true,
                ticks: { color: "#52525b", font: { size: 9 }, maxTicksLimit: 5 }, 
                grid: { color: "rgba(39, 39, 42, 0.5)" } 
            },
        },
    };

    _chart = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: { labels, datasets },
        options: options,
    });
}

export function setChartView(view) {
    // Legacy support for app.js calls
}
