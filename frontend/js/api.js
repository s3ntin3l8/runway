export async function fetchLimits() {
    const resp = await fetch('/api/limits');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
}
