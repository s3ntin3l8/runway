# Phase 4 — Platform Evolution

## Context

Phases 0–3 established schema, stateful core, hardening, quick wins, and architecture health. Phase 4 builds the full Runway experience on top of that foundation:

- **4C** makes `/api/limits` non-blocking (instant response from in-memory registry)
- **4B** adds persistent sidecar fleet tracking with a registry UI
- **4A** organizes the dashboard into provider sections with context filter pills
- **4D** adds token health visibility and proactive OAuth renewal to Settings

**Implementation order: 4C → 4B → 4A → 4D**
4C eliminates blocking from every subsequent feature. 4B creates the sidecar registry that 4A's filter pills consume. 4D is self-contained and benefits from a stable registry.

**Pre-1.0 policy:** No migration scaffolding needed — create tables, rename, and change freely.

---

## Current State (post-Phase 3)

- Routes: `/api/v1/usage/*`, `/api/v1/fleet/*`, `/api/v1/system/*`, `/api/v1/auth/*`
- `app/api/endpoints/usage.py` — `/limits`, `/history`, `/reset/{provider}`
- `app/api/endpoints/fleet.py` — `/ingest` (HMAC-signed)
- `app/api/endpoints/system.py` — `/health`, `/settings`, `/status`
- `app/services/poller.py` — `BackgroundPoller` writes `UsageSnapshot` rows every 15min
- `app/services/collector_manager.py` — `collect_all()` with single-flight, `_sync_collectors()` throttled 60s
- `app/services/token_cache.py` — in-memory 30min TTL; `get_all_stats()` and `get_all_active_accounts()` exist
- `app/models/db.py` — `UsageSnapshot` table (indexed on `provider_id`, `account_id`, `sidecar_id`, `timestamp`)
- `app/core/db.py` — `init_db()` calls `SQLModel.metadata.create_all(engine)` (new models auto-created if imported here)

---

## Phase 4C — Background Refresh & Instant-Cache Serving

### Goal

`/api/v1/usage/limits` returns instantly from an in-memory registry. A background task drives freshness; SmartCollector TTL caching already handles per-provider staleness.

### Design

Add a flat `_registry: List[Dict]` to `CollectorManager`. The poller populates it after every collection. The `/limits` endpoint reads from it without calling `collect_all()`. On startup, do one eager collect to pre-populate before accepting traffic.

This avoids introducing a new `BackgroundRefresher` class — the existing `BackgroundPoller` already does everything needed, just not storing the result anywhere accessible.

### Step 1 — Extend `CollectorManager` (`app/services/collector_manager.py`)

Add to `__init__`:
```python
self._registry: List[Dict[str, Any]] = []   # In-memory card store
```

Add method:
```python
def get_registry_snapshot(self) -> List[Dict[str, Any]]:
    """Return current registry. Thread-safe under asyncio cooperative scheduling."""
    return list(self._registry)  # shallow copy to prevent caller mutation
```

### Step 2 — Update `BackgroundPoller` (`app/services/poller.py`)

At the end of `poll_now()`, after building the card list but before DB writes, store to registry:
```python
# Update in-memory registry with latest results
manager._registry = cards   # atomic assignment, safe under asyncio
```

Keep all existing DB snapshot logic unchanged.

### Step 3 — Pre-populate Registry on Startup (`app/main.py`)

In the lifespan context, before `yield`, do an initial collect:
```python
# Pre-populate registry so first request is instant
try:
    initial_cards = await manager.collect_all()
    manager._registry = initial_cards
except Exception as e:
    logger.warning(f"Initial collection failed: {e}")
poller.start()
```

This means `_warmup_keychain()` is called as part of `collect_all()` and doesn't need a separate task.

### Step 4 — Update `/limits` Endpoint (`app/api/endpoints/usage.py`)

```python
@router.get("/limits")
@limiter.limit("10/minute")
async def fetch_all_limits(request: Request) -> Dict[str, Any]:
    results = manager.get_registry_snapshot()
    if not results:
        # Bootstrap fallback: registry not yet populated (should rarely happen)
        results = await manager.collect_all()
    limit_cards = [LimitCard(**item) for item in results]
    response = LimitsResponse(limits=limit_cards)
    return response.model_dump(exclude_none=False)
```

### Files Modified
- `app/services/collector_manager.py` — add `_registry`, `get_registry_snapshot()`
- `app/services/poller.py` — store result to `manager._registry` in `poll_now()`
- `app/main.py` — eager initial collect in lifespan startup
- `app/api/endpoints/usage.py` — read from registry, fallback to `collect_all()`

### Tests
- `tests/unit/test_collector_manager.py` — assert `get_registry_snapshot()` returns copy of `_registry`
- `tests/integration/test_usage_api.py` (new) — monkeypatch `manager._registry` with fixture, assert `/limits` returns it without calling `collect_all()`; assert empty registry triggers fallback

---

## Phase 4B — Sidecar Fleet Management

### Goal

Persistent sidecar registry in SQLite. New Fleet tab shows all known sidecars: last_seen, tags, custom name. Ingest auto-registers. No config push (Option A — config stays local to sidecar).

### Step 1 — New DB Model (`app/models/db.py`)

```python
import json as _json

class SidecarRegistry(SQLModel, table=True):
    __tablename__ = "sidecar_registry"

    sidecar_id: str = Field(primary_key=True)
    hostname: Optional[str] = None          # socket.gethostname() from sidecar
    custom_name: Optional[str] = None       # User-assigned display name
    _tags: Optional[str] = Field(default=None, alias="tags")  # JSON list stored as str
    last_seen: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )
    first_seen: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_ip: Optional[str] = None
    error_count: int = Field(default=0)
    ingest_count: int = Field(default=0)

    @property
    def tags(self) -> List[str]:
        return _json.loads(self._tags) if self._tags else []

    @tags.setter
    def tags(self, value: List[str]):
        self._tags = _json.dumps(value)
```

Add `from app.models.db import SidecarRegistry` to `app/core/db.py`'s `init_db()` so the table is created by `create_all`.

### Step 2 — Fleet Registry Service (`app/services/fleet_registry.py`) — New File

```python
from sqlmodel import Session, select
from app.models.db import SidecarRegistry
from datetime import datetime, timezone
from typing import Optional, List

class FleetRegistryService:
    def upsert_sidecar(
        self, sidecar_id: str, source_ip: str, session: Session
    ) -> SidecarRegistry:
        """Insert on first sight, update last_seen + ingest_count on repeat."""
        row = session.get(SidecarRegistry, sidecar_id)
        if row:
            row.last_seen = datetime.now(timezone.utc)
            row.ingest_count += 1
            row.last_ip = source_ip
        else:
            row = SidecarRegistry(
                sidecar_id=sidecar_id,
                hostname=sidecar_id,
                last_ip=source_ip,
            )
            session.add(row)
        session.commit()
        session.refresh(row)
        return row

    def update_sidecar(
        self, sidecar_id: str, custom_name: Optional[str],
        tags: Optional[List[str]], session: Session
    ) -> Optional[SidecarRegistry]:
        row = session.get(SidecarRegistry, sidecar_id)
        if not row:
            return None
        if custom_name is not None:
            row.custom_name = custom_name
        if tags is not None:
            row.tags = tags
        session.commit()
        session.refresh(row)
        return row

fleet_registry = FleetRegistryService()
```

### Step 3 — Expand Fleet Endpoint (`app/api/endpoints/fleet.py`)

Hook into ingest (add `Session` dependency and call `fleet_registry.upsert_sidecar()` when `sidecar_id` is present):
```python
from app.core.db import get_session
from app.services.fleet_registry import fleet_registry
from sqlmodel import Session

@router.post("/ingest")
async def ingest_metrics(
    raw_request: Request,
    session: Session = Depends(get_session),
    ...
):
    ...
    if request.sidecar_id:
        source_ip = raw_request.client.host if raw_request.client else "unknown"
        fleet_registry.upsert_sidecar(request.sidecar_id, source_ip, session)
    ...
```

Add new routes to the same `fleet.py` router:

```
GET  /api/v1/fleet/sidecars                → list all SidecarRegistry rows
GET  /api/v1/fleet/sidecars/{sidecar_id}   → get one sidecar
PATCH /api/v1/fleet/sidecars/{sidecar_id}  → update custom_name, tags
DELETE /api/v1/fleet/sidecars/{sidecar_id} → remove from registry
```

Response shape for list item:
```json
{
  "sidecar_id": "alice-macbook-pro",
  "custom_name": "Alice Work Laptop",
  "tags": ["Work", "Primary"],
  "last_seen": "2026-04-13T10:30:00Z",
  "first_seen": "2026-03-01T08:00:00Z",
  "last_ip": "192.168.1.42",
  "error_count": 0,
  "ingest_count": 147
}
```

PATCH body: `{"custom_name": "...", "tags": ["Work", "Primary"]}`

All new endpoints get `@limiter.limit("30/minute")`.

### Step 4 — Fleet Frontend

**`frontend/index.html`** — Add fourth nav link and view section:
```html
<button onclick="switchView('fleet')" class="nav-link" id="nav-fleet">Fleet</button>
...
<section id="view-fleet" class="view hidden">
  <div id="fleet-content"></div>
</section>
```

**`frontend/js/api.js`** — Add:
```javascript
export async function fetchFleet() { ... GET /api/v1/fleet/sidecars ... }
export async function patchSidecar(id, body) { ... PATCH ... }
export async function deleteSidecar(id) { ... DELETE ... }
```

**`frontend/js/app.js`** — Add `loadFleet()` called from `switchView('fleet')`:
- Fetches fleet data, calls `buildFleetView(data.sidecars)` 
- `window.editSidecarName(id)` — inline edit on name click → PATCH → re-render
- `window.deleteSidecar(id)` — confirm dialog → DELETE → re-render

**`frontend/js/components.js`** — Add `buildFleetView(sidecars)`:
- Cards or table rows per sidecar
- Status dot: 🟢 `last_seen < 30m`, 🟡 `< 2h`, ⚫ otherwise
- Tag pills with `+` button for inline tag management
- Inline name edit (click to edit, blur to save)
- `ingest_count` and `last_ip` in detail row

### Files Modified/Created
- `app/models/db.py` — add `SidecarRegistry` model
- `app/core/db.py` — import `SidecarRegistry` in `init_db()`
- `app/services/fleet_registry.py` — **new file**
- `app/api/endpoints/fleet.py` — ingest hook + 4 new routes
- `frontend/index.html` — Fleet nav + view section
- `frontend/js/api.js` — fleet fetch/patch/delete helpers
- `frontend/js/app.js` — `loadFleet()`, handlers
- `frontend/js/components.js` — `buildFleetView()`

### Tests
- `tests/unit/test_fleet_registry.py` (new) — `upsert_sidecar`: first call creates row, second increments `ingest_count` and updates `last_seen`; `update_sidecar`: sets custom_name and tags; unknown sidecar returns None
- `tests/integration/test_fleet_api.py` (new) — POST ingest with `sidecar_id` → GET `/fleet/sidecars` shows it → PATCH custom_name → DELETE → 404

---

## Phase 4A — Context-Aware Dashboard Reorganization

### Goal

Cards grouped by `provider_id` with a section header per provider. Context filter pills above the grid for sidecar/account/window filtering. Small source badge on cards showing sidecar initial. **Pure frontend — no backend changes.**

### Step 1 — Filter State (`frontend/js/state.js`)

Add to `STATE`:
```javascript
activeFilter: JSON.parse(localStorage.getItem('runway_active_filter') || 'null'),
// { dimension: 'sidecar_id'|'account_label'|'window_type', value: 'string' } | null
filterDimension: localStorage.getItem('runway_filter_dimension') || 'sidecar_id',
```

### Step 2 — Filter Pills UI (`frontend/index.html`)

Add above the grid inside `#view-dashboard`:
```html
<div id="filter-bar" class="mb-5 flex flex-col gap-2">
  <div class="flex gap-2 items-center">
    <span class="text-[10px] text-zinc-600 uppercase tracking-wide">Filter by</span>
    <button class="dim-btn" data-dim="sidecar_id" onclick="setFilterDimension('sidecar_id')">Source</button>
    <button class="dim-btn" data-dim="account_label" onclick="setFilterDimension('account_label')">Account</button>
    <button class="dim-btn" data-dim="window_type" onclick="setFilterDimension('window_type')">Window</button>
  </div>
  <div id="filter-pills" class="flex flex-wrap gap-1.5"></div>
</div>
```

### Step 3 — Filter Logic (`frontend/js/app.js`)

Add `applyFilters(data)`:
```javascript
function applyFilters(data) {
    const f = STATE.activeFilter;
    return data.filter(item => {
        if (f && item[f.dimension] !== f.value) return false;
        const disabled = STATE.disabledServices.includes(item.service_name);
        return !disabled || STATE.showHidden;
    });
}
```

Add `renderFilterPills()` — called from `loadData()` after `STATE.data` is set:
```javascript
function renderFilterPills() {
    const dim = STATE.filterDimension;
    const values = [...new Set(STATE.data.map(i => i[dim]).filter(Boolean))].sort();
    const active = STATE.activeFilter?.value;
    const pills = ['<button class="pill' + (!active ? ' pill-active' : '') + '" onclick="setFilter(null)">All</button>'];
    values.forEach(v => {
        pills.push(`<button class="pill${active === v ? ' pill-active' : ''}" onclick="setFilter('${escapeHTML(v)}')">${escapeHTML(v)}</button>`);
    });
    document.getElementById('filter-pills').innerHTML = pills.join('');
    // highlight active dim button
    document.querySelectorAll('.dim-btn').forEach(btn => {
        btn.classList.toggle('dim-btn-active', btn.dataset.dim === dim);
    });
}
window.setFilter = value => {
    STATE.activeFilter = value ? { dimension: STATE.filterDimension, value } : null;
    localStorage.setItem('runway_active_filter', JSON.stringify(STATE.activeFilter));
    renderFilterPills();
    renderGrid();
};
window.setFilterDimension = dim => {
    STATE.filterDimension = dim;
    STATE.activeFilter = null;
    localStorage.setItem('runway_filter_dimension', dim);
    localStorage.removeItem('runway_active_filter');
    renderFilterPills();
    renderGrid();
};
```

### Step 4 — Grouped Grid (`frontend/js/app.js`)

Replace flat `forEach` in `renderGrid()` with grouped sections:
```javascript
function renderGrid() {
    const visible = applyFilters(STATE.data);
    // Group by provider_id
    const groups = new Map();
    visible.forEach(item => {
        const key = item.provider_id || '__other__';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(item);
    });
    const sorted = [...groups.keys()].sort((a, b) =>
        a === '__other__' ? 1 : b === '__other__' ? -1 : a.localeCompare(b)
    );
    const html = sorted.map(key => buildProviderSection(key, groups.get(key))).join('');
    document.getElementById('grid').innerHTML = html || '<p class="empty-state">No cards match active filters.</p>';
}
```

### Step 5 — Provider Sections (`frontend/js/components.js`)

Add `buildProviderSection(providerId, items)`:
```javascript
const PROVIDER_ICONS = {
    anthropic: '🟠', gemini: '✨', github: '🐙', chatgpt: '🤖',
    openrouter: '🚀', opencode: '⚡', ollama: '🦙', minimax: '💎',
    kimi_api: '🌊', kimi_coding: '💻', zai_api: '🔮', zai_plan: '📋',
    antigravity: '🪐',
};
function buildProviderSection(providerId, items) {
    const title = providerId === '__other__' ? 'Other' : providerId;
    const icon = PROVIDER_ICONS[providerId] || '🔧';
    const cards = items.map(buildCard).filter(Boolean).join('');
    return `<div class="provider-section mb-8">
        <div class="flex items-center gap-2 mb-3 pb-2 border-b border-zinc-800/40">
            <span>${icon}</span>
            <h3 class="text-xs font-bold text-zinc-400 uppercase tracking-widest">${escapeHTML(title)}</h3>
            <span class="text-[10px] text-zinc-600 mono">${items.length}</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">${cards}</div>
    </div>`;
}
```

Add source badge inside `buildCard()` when `item.sidecar_id` is non-null:
```javascript
const sourceBadge = item.sidecar_id
    ? `<div class="source-badge" title="${escapeHTML(item.sidecar_id)}">${escapeHTML(item.sidecar_id[0].toUpperCase())}</div>`
    : '';
// Inject into card HTML at top-right of card container (absolute positioned)
```

### Step 6 — CSS Additions (`frontend/css/input.css`)

```css
.pill { @apply px-3 py-1 rounded-full text-[10px] font-semibold bg-zinc-800/60 border border-zinc-700/50 text-zinc-400 cursor-pointer transition-all; }
.pill:hover { @apply border-violet-500/50 text-violet-300; }
.pill-active { @apply bg-violet-500/15 border-violet-500/50 text-violet-300; }
.dim-btn { @apply px-2 py-0.5 rounded text-[10px] font-semibold text-zinc-500 hover:text-zinc-300 transition-colors; }
.dim-btn-active { @apply text-zinc-200; }
.source-badge { position: absolute; top: 6px; right: 6px; width: 16px; height: 16px; border-radius: 50%; background: rgba(139,92,246,0.2); border: 1px solid rgba(139,92,246,0.4); color: #a78bfa; font-size: 7px; font-weight: 800; display: flex; align-items: center; justify-content: center; }
```

### Files Modified
- `frontend/js/state.js` — add `activeFilter`, `filterDimension`
- `frontend/js/app.js` — `applyFilters()`, `renderFilterPills()`, `setFilter()`, `setFilterDimension()`, grouped `renderGrid()`
- `frontend/js/components.js` — `buildProviderSection()`, `PROVIDER_ICONS`, source badge in `buildCard()`
- `frontend/index.html` — filter bar HTML above grid
- `frontend/css/input.css` — pill / dim-btn / source-badge styles

### Tests
No new backend tests. Frontend logic can be tested manually: 
1. Confirm sections appear grouped by provider
2. Click a sidecar pill → only that sidecar's cards show
3. Filter pills repopulate correctly when dimension changes
4. Filters persist across page reload via localStorage

---

## Phase 4D — Token Health & Proactive Refresh

### Goal

Settings page shows a "Token Health" panel listing all known credentials with expiry status. Supports proactive OAuth token refresh for Anthropic and Gemini.

### Step 1 — Token Health Service (`app/services/token_health.py`) — New File

```python
import base64, json, time, logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.services.token_cache import token_cache

logger = logging.getLogger(__name__)
EXPIRY_WARNING_SECS = 86400  # 24h

def _parse_jwt_exp(token: str) -> Optional[float]:
    """Extract exp claim without signature verification."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return float(payload['exp']) if payload.get('exp') else None
    except Exception:
        return None

def _status(exp: Optional[float]) -> str:
    if exp is None: return 'unknown'
    now = time.time()
    if exp < now: return 'expired'
    if exp - now < EXPIRY_WARNING_SECS: return 'expiring'
    return 'valid'

class TokenHealthService:
    async def get_health(self) -> List[Dict[str, Any]]:
        stats = await token_cache.get_all_stats()   # already exists: provider→{account_id→{...}}
        result = []
        for provider, accounts in stats.items():
            for acc_id, info in accounts.items():
                tokens = await token_cache.get(provider, acc_id) or {}
                exp = None
                for key in ('oauth_token', 'access_token', 'id_token'):
                    if key in tokens:
                        exp = _parse_jwt_exp(tokens[key])
                        if exp:
                            break
                result.append({
                    'provider': provider,
                    'account_id': acc_id,
                    'account_label': info.get('account_label'),
                    'token_types': list(tokens.keys()),
                    'status': _status(exp),
                    'expires_at': datetime.fromtimestamp(exp, tz=timezone.utc).isoformat() if exp else None,
                    'ttl_remaining_seconds': info.get('ttl_remaining', 0),
                    'can_refresh': 'refresh_token' in tokens,
                })
        return result

token_health_service = TokenHealthService()
```

Verify `token_cache.get_all_stats()` returns `{provider: {account_id: {account_label, ttl_remaining, tokens: [...]}}}` shape. Adjust accessor if the real schema differs.

### Step 2 — New Endpoints in `app/api/endpoints/system.py`

```python
from app.services.token_health import token_health_service

@router.get("/token-health")
@limiter.limit("30/minute")
async def get_token_health(request: Request) -> Dict[str, Any]:
    tokens = await token_health_service.get_health()
    return {"tokens": tokens}

@router.post("/token-health/refresh/{provider}/{account_id}")
@limiter.limit("5/minute")
async def refresh_token(request: Request, provider: str, account_id: str) -> Dict[str, Any]:
    """Attempt proactive OAuth refresh for providers that support it."""
    tokens = await token_cache.get(provider, account_id) or {}
    refresh_token = tokens.get('refresh_token')
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token available")
    
    # Dispatch to provider-specific refresh logic
    # Only Anthropic and Gemini have known OAuth endpoints
    from app.services.token_refresher import refresh_oauth_token
    try:
        new_tokens = await refresh_oauth_token(provider, tokens)
        await token_cache.store(provider, new_tokens, account_id)
        return {"status": "refreshed"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Refresh failed: {str(e)[:100]}")
```

### Step 3 — Token Refresher (`app/services/token_refresher.py`) — New File

```python
import httpx
from typing import Dict

REFRESH_ENDPOINTS = {
    "anthropic": "https://claude.ai/api/auth/oauth/token",
    "gemini": "https://oauth2.googleapis.com/token",
}

async def refresh_oauth_token(provider: str, tokens: Dict[str, str]) -> Dict[str, str]:
    endpoint = REFRESH_ENDPOINTS.get(provider)
    if not endpoint:
        raise ValueError(f"No refresh endpoint known for provider: {provider}")
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(endpoint, data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            # Provider-specific: client_id for Gemini, etc.
            **_get_client_params(provider, tokens),
        }, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    
    updated = dict(tokens)
    updated["oauth_token"] = data.get("access_token", tokens["oauth_token"])
    if "refresh_token" in data:
        updated["refresh_token"] = data["refresh_token"]
    return updated

def _get_client_params(provider: str, tokens: Dict) -> Dict:
    if provider == "gemini":
        return {
            "client_id": tokens.get("client_id", ""),
            "client_secret": tokens.get("client_secret", ""),
        }
    return {}
```

Note: Exact OAuth endpoints and parameters for Anthropic must be confirmed against the collector's existing refresh code in `app/services/collectors/anthropic_oauth.py` before implementing — use those exact parameters.

### Step 4 — Frontend: Token Health Panel (`frontend/js/`)

**`api.js`** — add:
```javascript
export async function fetchTokenHealth() { ... GET /api/v1/system/token-health ... }
export async function postTokenRefresh(provider, accountId) { ... POST /api/v1/system/token-health/refresh/{provider}/{accountId} ... }
```

**`app.js`** — extend `loadSettings()` to append token health section after the existing settings content:
```javascript
async function loadSettings() {
    ... // existing
    const health = await fetchTokenHealth();
    document.getElementById('settings-extra').innerHTML = buildTokenHealthPanel(health.tokens);
}
window.refreshToken = async function(provider, accountId) {
    try {
        const d = await postTokenRefresh(provider, accountId);
        if (d.status === 'refreshed') loadSettings();
        else alert('Refresh failed: ' + (d.detail || 'unknown'));
    } catch(e) { alert('Error: ' + e.message); }
}
```

Add `<div id="settings-extra"></div>` to the settings view in `index.html`.

**`components.js`** — add `buildTokenHealthPanel(tokens)`:
- Section header "🔑 Token Health"
- Row per token: provider, account_label (if set), token types, status badge (color-coded), expiry relative time or cache TTL
- "REFRESH" button when `can_refresh && status !== 'valid'`

### Files Modified/Created
- `app/services/token_health.py` — **new file**
- `app/services/token_refresher.py` — **new file**
- `app/api/endpoints/system.py` — 2 new routes
- `frontend/js/api.js` — `fetchTokenHealth()`, `postTokenRefresh()`
- `frontend/js/app.js` — extend `loadSettings()`, `window.refreshToken`
- `frontend/js/components.js` — `buildTokenHealthPanel()`
- `frontend/index.html` — add `#settings-extra` div

### Tests
- `tests/unit/test_token_health.py` (new) — mock `token_cache.get_all_stats()` + `token_cache.get()` with fixture tokens (one valid JWT with `exp` in future, one expired); assert correct `status` values; test `_parse_jwt_exp()` with known JWT and malformed input

---

## Critical Files

| File | Change |
|------|--------|
| `app/services/collector_manager.py` | Add `_registry`, `get_registry_snapshot()` |
| `app/services/poller.py` | Store result to `manager._registry` in `poll_now()` |
| `app/main.py` | Eager initial collect in lifespan startup |
| `app/api/endpoints/usage.py` | Read from registry, fallback to `collect_all()` |
| `app/models/db.py` | Add `SidecarRegistry` model |
| `app/core/db.py` | Import `SidecarRegistry` in `init_db()` |
| `app/services/fleet_registry.py` | **New** — `FleetRegistryService` |
| `app/api/endpoints/fleet.py` | Ingest hook + 4 CRUD routes |
| `app/services/token_health.py` | **New** — `TokenHealthService` |
| `app/services/token_refresher.py` | **New** — `refresh_oauth_token()` |
| `app/api/endpoints/system.py` | 2 new token-health routes |
| `frontend/index.html` | Fleet nav link + view; filter bar; `#settings-extra` div |
| `frontend/js/state.js` | Add `activeFilter`, `filterDimension` |
| `frontend/js/app.js` | Grouped `renderGrid()`, filter functions, `loadFleet()`, `loadSettings()` extension |
| `frontend/js/components.js` | `buildProviderSection()`, `buildFleetView()`, `buildTokenHealthPanel()`, source badge |
| `frontend/js/api.js` | Fleet and token-health fetch helpers |
| `frontend/css/input.css` | Pill, dim-btn, source-badge styles |

---

## Verification

1. **4C**: `GET /api/v1/usage/limits` responds in <50ms on second request (first populates registry). Disable a collector's API → endpoint still returns immediately with stale data.
2. **4B**: Start sidecar pointing at local server → sidecar appears in Fleet tab. Edit name/tags → persists after page reload. DELETE sidecar → disappears from list.
3. **4A**: Cards grouped under provider headers. Click "Source" → pills show sidecar hostnames. Click a pill → only that sidecar's cards shown. Reload → filter state preserved.
4. **4D**: Settings → Token Health section shows active credentials. Status correctly shows valid/expiring/expired for mock tokens. REFRESH button triggers backend call and panel re-renders.
5. **Full suite**: `source .venv/bin/activate && pytest` — all tests pass except the 2 pre-existing macOS cookie tests on WSL2.
