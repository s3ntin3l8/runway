Listed directory ai-usage-tracker
Viewed main.py:1-367
Browser task: "Researching cockpit-tools Auth Flow"
Read URL: https://github.com/jlcodes99/cockpit-tools
Viewed content.md:1-800
Searched web: "jlcodes99/cockpit-tools authentication oauth implementation details"

# AI Usage Tracker - Ideas & Improvements

## Medium Priority Issues

### 1. Frontend Error Messages Enhancement
**File**: `frontend/js/app.js:49-66`  
**Severity**: Medium  
**Effort**: 1-2 hours

**Current Issue**:
- Generic catch block doesn't log error details
- Error banner doesn't show error message to user
- No way to distinguish between network, server, or parsing errors

**Suggested Implementation**:
```javascript
} catch (err) {
    console.error('Failed to fetch limits:', err);
    const errorMsg = err.message || 'Unknown error';
    errorBanner.textContent = `> Error: ${errorMsg}`;
    errorBanner.classList.remove('hidden');
    
    // Log error type for debugging
    if (err instanceof TypeError) {
        console.debug('Network error detected');
    } else if (err instanceof SyntaxError) {
        console.debug('JSON parsing error detected');
    }
}
```

**Benefits**:
- Better user experience (see actual errors)
- Easier debugging for users reporting issues
- Can identify patterns in failures

---

### 2. Add Unit Tests & Integration Tests
**Directory**: `tests/`  
**Severity**: Medium  
**Effort**: 1-2 days

**Current Gap**: Zero test coverage

**Suggested Structure**:
```
tests/
├── unit/
│   ├── test_collectors.py          # Test each collector in isolation
│   ├── test_config.py              # Test configuration loading
│   ├── test_utils.py               # Test PaceCalculator, retry logic, etc.
│   └── test_schemas.py             # Test Pydantic models
├── integration/
│   ├── test_endpoints.py           # Test API endpoints
│   ├── test_collector_manager.py   # Test orchestration
│   └── conftest.py                 # Shared fixtures
└── fixtures/
    └── mock_responses.json         # Mock API responses
```

**Key Tests to Add**:
- Collector error scenarios (API down, invalid tokens, malformed data)
- Timeout handling (verify collectors fail gracefully)
- Rate limit retry logic (verify exponential backoff)
- External metrics ingestion
- Concurrent collector execution

**Testing Framework**: `pytest` + `pytest-asyncio` for async tests

---

### 3. Frontend Type Safety (JSDoc Annotations)
**Files**: `frontend/js/*.js`  
**Severity**: Medium  
**Effort**: 3-4 hours

**Current Issue**: Pure JavaScript with no type hints

**Suggested Implementation**:
```javascript
/**
 * Fetch all limits from backend
 * @returns {Promise<{limits: Array<LimitCard>}>}
 */
export async function fetchLimits() { ... }

/**
 * Render a single limit card
 * @param {LimitCard} card - The card data to render
 * @returns {HTMLElement} The rendered DOM element
 */
function renderCard(card) { ... }

/**
 * @typedef {Object} LimitCard
 * @property {string} service - Service name
 * @property {string} icon - Emoji icon
 * @property {string} remaining - Remaining capacity
 * @property {string} unit - Unit of measurement
 * @property {string} reset - Human-readable reset time
 * @property {string} health - "good" | "warning" | "critical"
 * @property {string} pace - Burn rate descriptor
 * @property {string} detail - Additional details
 */
```

**Benefits**:
- IDE autocompletion in VSCode
- Catches type errors early
- Better documentation for contributors
- No build step required (native JS)

---

### 4. Missing Docstrings in Collectors
**Files**: `app/services/collectors/*.py`  
**Severity**: Medium  
**Effort**: 2-3 hours

**Current Gap**: No docstrings explaining collection strategy

**Suggested Pattern**:
```python
class AnthropicCollector(BaseCollector):
    """
    Collects Claude Pro usage limits using a 3-tier strategy.
    
    Strategy:
    1. Try OAuth API if CLAUDE_CODE_OAUTH_TOKEN is available
       - Fetches real-time usage from Anthropic's OAuth endpoint
       - Returns multiple quotas (5h, 7d windows)
    2. Fallback to local log parsing (~/.claude/projects)
       - Scans .jsonl files from last 5 hours
       - Counts input/output tokens manually
    3. Return error card if both fail
    
    Caching:
    - OAuth results cached for 10 minutes to avoid rate limits
    - Local logs read fresh on every request
    
    Raises:
    - Returns error cards instead of raising exceptions
    """
    
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """
        Collect Claude usage limits.
        
        Args:
            client: AsyncHTTP client for making requests
        
        Returns:
            List of limit card dictionaries or error card
        """
```

**Benefits**:
- Onboarding new contributors becomes easier
- Helps future maintainers understand design decisions
- Can be extracted for API docs

---

## Low Priority Improvements

### 1. Response Caching Strategy
**File**: `app/services/collector_manager.py`  
**Severity**: Low  
**Effort**: 4-6 hours

**Current Issue**: All collectors run on every request to `/api/limits`

**Suggested Implementation**:
```python
class CollectorManager:
    def __init__(self):
        self.collectors = [...]
        self._cache = {}
        self._cache_times = {}
        self._cache_ttl = {
            'anthropic': 600,      # 10 min (OAuth rate limit safety)
            'gemini': 300,         # 5 min (frequent resets)
            'github': 900,         # 15 min (stable)
            'opencode': 1800,      # 30 min (rarely changes)
            # ...
        }
    
    async def collect_all(self) -> List[Dict[str, Any]]:
        """Collect with per-collector TTL caching."""
        results = {}
        now = time.time()
        
        for name, collector in zip(collector_names, self.collectors):
            if name in self._cache:
                age = now - self._cache_times[name]
                if age < self._cache_ttl.get(name, 300):
                    results[name] = self._cache[name]
                    continue
            
            # Collect fresh data
            data = await collector.collect(client)
            self._cache[name] = data
            self._cache_times[name] = now
            results[name] = data
```

**Benefits**:
- Reduced API calls during heavy dashboard usage
- Respects provider rate limits better
- Frontend can show "cached X seconds ago" badge
- Faster dashboard load times

---

### 2. Smart Differential Fetching
**File**: `app/services/collectors/*.py`  
**Severity**: Low  
**Effort**: 2-3 days

**Current Issue**: Collectors run every time, even if nothing changed

**Suggested Pattern**:
```python
class SmartCollector(BaseCollector):
    """Only fetch if last result is stale or errored."""
    
    def __init__(self):
        self.last_result = None
        self.last_error_count = 0
        self.error_threshold = 3  # Retry after 3 errors
    
    async def collect(self, client: httpx.AsyncClient):
        # If last collection was recent and successful, skip
        if self.should_use_cache():
            return self.last_result
        
        # Otherwise fetch fresh
        try:
            result = await self._fetch_fresh(client)
            self.last_error_count = 0
            self.last_result = result
            return result
        except Exception as e:
            self.last_error_count += 1
            # Return stale result if we have one, else error card
            return self.last_result or error_card(...)
```

**Benefits**:
- Fewer API calls overall
- Graceful degradation on failures
- Reduced latency for end users

---

### 3. Dashboard Auto-Refresh UI Toggle
**File**: `frontend/index.html` + `frontend/js/app.js`  
**Severity**: Low  
**Effort**: 2-3 hours

**Current Issue**: Dashboard doesn't auto-refresh, static view

**Suggested Implementation**:
```javascript
class DashboardManager {
    constructor() {
        this.refreshInterval = null;
        this.autoRefreshEnabled = localStorage.getItem('autoRefresh') === 'true';
        this.refreshRate = parseInt(localStorage.getItem('refreshRate')) || 60000; // 60s default
    }
    
    startAutoRefresh() {
        if (this.refreshInterval) return;
        
        this.refreshInterval = setInterval(() => {
            this.fetchAndRender();
        }, this.refreshRate);
    }
    
    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }
}
```

**HTML Changes**:
```html
<div class="controls">
    <label>
        <input type="checkbox" id="autoRefresh" /> 
        Auto-refresh
    </label>
    <select id="refreshRate">
        <option value="30000">30s</option>
        <option value="60000" selected>60s</option>
        <option value="300000">5m</option>
    </select>
</div>
```

**Benefits**:
- Real-time feel without constant fetching
- Configurable refresh rates
- Saves to localStorage for persistence
- Respects user preferences

---

### 4. Error Card Categorization
**File**: `app/core/utils.py`  
**Severity**: Low  
**Effort**: 2-3 hours

**Current Issue**: All errors look the same, hard to diagnose

**Suggested Implementation**:
```python
def error_card(service: str, icon: str, message: str, error_type: str = "unknown"):
    """
    Create an error card with categorized error types.
    
    error_type options:
    - "missing_config": Missing .env variable or credential file
    - "auth_failed": Invalid token or authentication issue
    - "rate_limited": API rate limit (429)
    - "timeout": Request timed out
    - "parse_error": Invalid response format
    - "api_error": Generic API error
    - "unknown": Unknown error
    """
    error_colors = {
        "missing_config": "🟡",  # Yellow
        "auth_failed": "🔴",      # Red
        "rate_limited": "🟠",     # Orange
        "timeout": "⏱️",          # Timeout symbol
        "parse_error": "⚠️",      # Warning
        "api_error": "❌",         # Error
        "unknown": "❓",          # Question mark
    }
    
    return {
        "service": service,
        "icon": error_colors.get(error_type, icon),
        "remaining": "ERR",
        "error_type": error_type,  # New field for frontend
        "detail": message,
        "health": "critical",
    }
```

**Benefits**:
- Frontend can style different error types differently
- Easier to spot patterns ("most failures are auth")
- Users can self-diagnose issues

---

### 5. Metrics Export Formats
**File**: `app/api/routes.py`  
**Severity**: Low  
**Effort**: 3-4 hours

**Current Issue**: API only returns JSON

**Suggested Enhancement**:
```python
@app.get("/api/limits")
async def get_limits(format: str = "json"):
    """
    Get all limits in requested format.
    
    Formats:
    - json (default)
    - csv (for Excel/spreadsheet import)
    - prometheus (for monitoring systems)
    - html (human-readable table)
    """
    limits = await manager.collect_all()
    
    if format == "csv":
        return StreamingResponse(export_csv(limits), 
                               media_type="text/csv")
    elif format == "prometheus":
        return Response(export_prometheus_metrics(limits),
                       media_type="text/plain")
    elif format == "html":
        return HTMLResponse(export_html_table(limits))
    else:
        return {"limits": limits}
```

**Benefits**:
- Integration with monitoring systems (Prometheus, Grafana)
- Can import into spreadsheets
- Opens up for analytics/BI tools

---

### 6. Webhook Notifications for Threshold Alerts
**File**: `app/services/` (new module)  
**Severity**: Low  
**Effort**: 4-6 hours

**Suggested Pattern**:
```python
class AlertManager:
    """Send alerts when quotas cross thresholds."""
    
    async def check_and_alert(self, limits: List[Dict]):
        """
        Check if any limits crossed configured thresholds.
        
        Thresholds (configurable):
        - Critical: >90% used
        - Warning: >70% used
        - Info: >50% used
        """
        webhooks = config.ALERT_WEBHOOKS  # Discord, Slack URLs
        
        for limit in limits:
            pct = parse_percent(limit['remaining'])
            
            if pct > 90:
                await self.notify("critical", limit, webhooks)
            elif pct > 70:
                await self.notify("warning", limit, webhooks)
```

**Webhook Payload**:
```json
{
  "service": "Claude Pro",
  "status": "critical",
  "remaining": "5%",
  "reset": "in 2h 30m",
  "timestamp": "2026-04-07T12:45:00Z"
}
```

**Benefits**:
- Get notified before running out of quota
- Integrates with Discord/Slack teams
- Prevents "out of quota" surprises

---

### 7. Historical Tracking & Burndown Charts
**File**: `app/services/` (new module)  
**Severity**: Low  
**Effort**: 1-2 days

**Suggested Data Model**:
```python
class HistoricalMetrics:
    """Track usage over time for trend analysis."""
    
    def __init__(self):
        self.db_path = "~/.usage-tracker/history.db"  # SQLite
        self.init_db()
    
    async def record(self, limits: List[Dict]):
        """Store snapshot of all limits."""
        snapshot = {
            "timestamp": datetime.now(),
            "limits": limits,
        }
        self.db.insert("snapshots", snapshot)
```

**Frontend Enhancements**:
- Line chart showing usage trend over last 7 days
- Estimated burndown rate
- ETA for quota exhaustion
- Comparison with last week

**Benefits**:
- Identify usage patterns
- Predict when quota will run out
- Track optimization improvements

---

## Architecture Improvements

### 1. Move Away from Hardcoded Limits
**Severity**: Low  
**Current State**: Claude limit hardcoded to 2,000,000 tokens

**Suggested Approach**:
- Query local IDE config files for plan information
- For Anthropic: check `~/.claude/.credentials.json` for subscription tier
- For Gemini: Use tier detection API endpoint
- Store limits in config, not in code

---

### 2. Implement Strategy Pattern for Collectors
**Severity**: Low  
**Effort**: 2-3 hours

All collectors inherit from `BaseCollector` but could benefit from consistent interface:

```python
class BaseCollector(ABC):
    """Base class with consistent strategy pattern."""
    
    @abstractmethod
    async def _primary_strategy(self) -> Optional[List[Dict]]:
        """Try primary data source (API)."""
        pass
    
    @abstractmethod
    async def _fallback_strategy(self) -> Optional[List[Dict]]:
        """Try fallback source (logs)."""
        pass
    
    @abstractmethod
    async def _error_handler(self, error: Exception) -> List[Dict]:
        """Return appropriate error card."""
        pass
```

---

## Documentation Gaps

### 1. Architecture Decision Records (ADRs)
**File**: `docs/adr/`  
**Severity**: Low

Document key decisions:
- Why we chose local-first over centralized API
- Why stateless (no database)
- Why specific collector fallback strategies
- Why environment-based credentials

---

### 2. Troubleshooting Guide
**File**: `docs/TROUBLESHOOTING.md`  
**Severity**: Low

Guide for common issues:
- "Why am I getting 'ERR' for Claude?"
- "How do I update expired tokens?"
- "Why aren't my logs being recognized?"
- "What does '[Cached]' mean?"

---

## Performance Optimizations

### 1. Lazy Load Collectors
**Severity**: Low

Currently all collectors instantiate on startup. Could lazy-load only requested ones.

### 2. Concurrent Collector Timeout Protection
**Severity**: Low

Add global timeout across all collectors (not just individual ones):

```python
async def collect_all_with_timeout(self, timeout: float = 30.0):
    """Collect with overall timeout."""
    try:
        return await asyncio.wait_for(
            asyncio.gather(...),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        # Return partial results + error cards for timed-out collectors
```

---

---

## The comparison between `ai-usage-tracker` and `jlcodes99/cockpit-tools` reveals that while your current project is an excellent **passive monitor**, `cockpit-tools` is an **active bridge** that manages the entire lifecycle of multiple accounts.

### 🔄 Comparison of Auth Flows

| Feature | Current `ai-usage-tracker` | `cockpit-tools` (The Alternative) |
| :--- | :--- | :--- |
| **Source of Truth** | `.env` variables or existing local files. | Its own managed database (`~/.antigravity_cockpit`). |
| **Token Acquisition** | Manual (User must copy-paste tokens). | **Active OAuth**: Handles the login flow in-app. |
| **Account Limit** | Usually 1 per provider (hardcoded in `.env`). | **Multi-Account**: List of many accounts per provider. |
| **Workflow** | Reads state and displays it. | **Credential Injection**: Writes selected tokens back to the IDE's local files to "switch" users. |
| **Token Longevity** | Expires when the manual token expires. | **Auto-Refresh**: Background tasks refresh OAuth tokens. |

---

### 💡 Smarter Ways to "Take Over"

If you want to evolve `ai-usage-tracker`, here are the "smarter" patterns from `cockpit-tools` that would be most valuable:

#### 1. Credential Injection (Active Switching)
Currently, you *read* from `~/.gemini` or `~/.codex`. A "Cockpit-style" improvement would be to allow the user to select an account in your dashboard and have `main.py` **write** that token back to those files. This turns your tracker into a "Switcher."

#### 2. Local OAuth Helper
Instead of asking users to find hidden tokens, you can implement a small OAuth callback listener in FastAPI.
> [!TIP]
> You could add a "Login" button that opens the browser to the provider's OAuth page, captures the redirect on a local port, and saves the token to your `.env` or a local JSON database automatically.

#### 2.1 GitHub Device Flow Integration
Inspired by `CodexBar`, we can implement the official GitHub Device Flow. This is particularly useful for headless or Docker environments where a browser redirect might be difficult.
- **Workflow**: The user clicks "Link GitHub", the dashboard displays a short code (e.g., `ABCD-1234`), and the user enters it at `github.com/login/device`.
- **Benefit**: No manual token generation/copy-pasting; works perfectly in containers; allows for automated token refresh.

#### 3. WebSocket Plugin Sync
`cockpit-tools` uses a local WebSocket (port `19528`) to talk to a browser extension. When a user logs into a web-based AI (like Claude or ChatGPT), the extension "sniffs" the token and pushes it to the local app. This is the "smartest" way to keep tokens fresh without manual work.

#### 4. Background Refresh Tasks
For providers like Google (Gemini CLI), tokens rotate frequently. You could implement a background `asyncio` task in `main.py` that checks for expiring tokens and uses the `refresh_token` to get a new one, keeping the dashboard (and the CLI) perpetually authenticated.

#### 5. Unified "Local Sync" Directory
Instead of scattering logic for `~/.claude`, `~/.gemini`, etc., you could adopt a pattern where you maintain a "Sync Folder" that maps your internal account database to the standard IDE locations.

### Recommendation
If you want to keep the tool lightweight, I suggest starting with **Multi-Account Support** (saving a list of tokens in a JSON file instead of just `.env`) and **Credential Injection** (the ability to write to the local files you currently only read).

Created ideas.md
Searched web: "jlcodes99/cockpit-tools source code structure quota fetching logic"

The specific way each tool gathers information differs fundamentally in its **source of truth** and **depth of integration**.

While `ai-usage-tracker` works like a "forensic tool" (looking at what's already on your disk), `cockpit-tools` works like a "remote agent" (talking directly to the provider's brain).

### 🛠 Comparison of Information Gathering

| Service | `ai-usage-tracker` (Scraping) | `cockpit-tools` (API-First) |
| :--- | :--- | :--- |
| **Claude** | **Local Logs**: Scans `~/.claude/projects` for `.jsonl` files and sums up tokens manually. Limits are hardcoded in `main.py`. | **Direct API**: Calls Anthropic's internal `/api/oauth/usage` endpoint. Gets dynamic limits and reset times directly from the server. |
| **Gemini** | **Local Sessions**: Reads `~/.gemini/tmp/sessions` to count prompt/completion tokens. | **Google API**: Uses OAuth credentials to query Google's management API for exact quota status. |
| **GitHub Copilot** | **API**: Uses `GITHUB_TOKEN` for `/rate_limit`. (Only core API, not copilot-specific). | **Copilot API**: Queries the specific Copilot billing/usage endpoints to distinguish between Inline and Chat suggestions. |
| **Codex** | **Local Cache**: Reads `~/.codex/sessions` for `used_percent`. | **Sync & Fetch**: Hydrates account metadata by calling Codex's `/account` and `/usage` APIs using the user's `auth.json`. |
| **OpenCode** | **SQLite**: Directly queries the `opencode.db` file for line changes. | **API**: Uses the OpenCode management endpoints for USD balance and hard limits. |
| **Windsurf / Trae** | **Not fully supported**. | **Local Injection**: Reads and *writes* to the platform's local storage (LevelDB or JSON) to sync account state. |

---

### 🧐 Why `cockpit-tools` is "Smarter"

1.  **Dynamic vs. Hardcoded**: Your current Claude collector assumes a `2,000,000` token limit. `cockpit-tools` fetches your "Plan" (Pro, Team, etc.) from the API and adjusts the limit automatically.
2.  **State Hydration**: When `cockpit-tools` imports a token, it immediately "hydrates" it—calling an official `/me` endpoint to get your username, avatar, and exact subscription tier.
3.  **The "Injection" Loophole**: Instead of just reading logs (which can be delayed), `cockpit-tools` manages the auth state. It can refresh a token *before* it expires, ensuring the gathering logic never fails due to an old session.
4.  **Strategy Pattern**: It uses a standardized code structure where each provider (Copilot, Cursor, etc.) implements a `getRemainingQuota()` method, making it trivial to add new ones.

### 💡 What we should adopt?

If you want to keep using your current "Scraping" approach (which is safer as it doesn't require as many permissions), you could still **adopt the API-first check** as a fallback.

> [!IMPORTANT]
> **The biggest win would be to move away from hardcoded limits.** Even if we continue reading local logs, we should try to find the "Plan" information in the local config files to set the usage progress bars accurately.