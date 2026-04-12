# Codebase Audit — Runway (Pre-1.0)

Comprehensive review of the codebase with focus on security, stability, performance, and architecture. Findings are organized by severity.

---

## 🔴 Security

### S1. Global Exception Handler Leaks Internals

**File:** [main.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/main.py#L50-L57)

The global exception handler returns `str(exc)` to the client:

```python
return JSONResponse(
    status_code=500,
    content={"detail": "Internal Server Error", "message": str(exc)},
)
```

This can leak stack traces, file paths, database errors, or credential-related messages to any HTTP client. In production, the response should never include the raw exception message.

**Fix:** Remove `"message": str(exc)` from the response body. Keep the `logger.error()` with `exc_info=True` for server-side debugging.

---

### S2. No Rate Limiting on Public Endpoints

**Files:** [routes.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/api/routes.py), [health.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/api/endpoints/health.py)

`/api/limits`, `/api/health`, and the GitHub OAuth endpoints have no rate limiting. An attacker (or a misconfigured auto-refresh loop) can:
- Exhaust upstream API quotas by hammering `/api/limits` (each call triggers all collectors)
- DoS the server with rapid health check requests

**Fix:** Add a simple `slowapi` or middleware-based rate limiter. Suggested limits:
- `/api/limits`: 10 req/min per IP
- `/api/health`: 30 req/min per IP
- `/api/ingest`: 60 req/min per IP (already HMAC-protected, but still)
- GitHub OAuth: 5 req/min per IP

---

### S3. Health Endpoint Exposes Internal State

**File:** [health.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/api/endpoints/health.py#L18-L19)

```python
"token_cache": {
    "providers": await token_cache.get_all_stats(),
    "count": len(token_cache._cache),  # <-- private attribute
},
```

`get_all_stats()` returns token type names (e.g., `oauth_token`, `refresh_token`, `cookie_...`) and account IDs. While it doesn't return token *values*, the metadata is still sensitive — it reveals which providers are authenticated, which accounts are active, and TTL remaining on each credential.

**Fix:** Either restrict `/api/health` behind an API key/auth header, or strip it down to just `{"status": "healthy", "collectors_active": N, "external_providers": N}` for unauthenticated access.

---

### S4. GitHub Token Written Non-Atomically

**File:** [github_oauth.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/api/endpoints/github_oauth.py#L174-L176)

```python
with open(settings.GITHUB_OAUTH_PATH, "w") as f:
    json.dump(token_data, f, indent=2)
```

Uses raw `open()` instead of `safe_write_json()`. If the process is interrupted mid-write (e.g., `kill -9`, power loss), the token file will be truncated/corrupted, and GitHub auth will silently break until the user re-authenticates.

**Fix:** Replace with `safe_write_json(settings.GITHUB_OAUTH_PATH, token_data)`.

---

### S5. ChatGPT Token Persistence is Non-Atomic

**File:** [chatgpt.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/collectors/chatgpt.py#L149-L162)

Same issue as S4 — `_save_refreshed_oauth_token` uses raw `open()` for both read and write. Crash during write corrupts `auth.json`.

**Fix:** Use `safe_write_json()` for the write path.

---

### S6. CORS Origins Are Hardcoded

**File:** [config.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/core/config.py#L150)

```python
CORS_ORIGINS: list = ["http://localhost:8765", "http://127.0.0.1:8765"]
```

If `APP_HOST` or `APP_PORT` is changed (e.g., in Docker with `APP_HOST=0.0.0.0`), CORS will still only allow the hardcoded origins. Requests from the actual deployment URL will fail with CORS errors.

**Fix:** Derive CORS origins dynamically from `APP_HOST`/`APP_PORT`, or add a `CORS_ORIGINS` env var that overrides the hardcoded list.

---

## 🟡 Stability

### T1. Dual CollectorManager Instances

**Files:** [routes.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/api/routes.py#L12), [collector_manager.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/collector_manager.py#L189)

Two separate `CollectorManager` instances exist:
```python
# routes.py:
manager = CollectorManager()  # <-- used by /api/limits

# collector_manager.py:
collector_manager = CollectorManager()  # <-- exported global, unused?
```

The `routes.py` instance is the one actually serving `/api/limits`. The `collector_manager.py` global is never imported by route handlers. If someone imports `collector_manager` from the module thinking it's the active instance, they'll get a completely separate set of collectors with separate caches.

**Fix:** Delete the instantiation in `routes.py`. Import `collector_manager` from `collector_manager.py` and use it in the route handler. One instance, one source of truth.

---

### T2. Double-Caching in Collectors + SmartCollector

**Files:** [chatgpt.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/collectors/chatgpt.py#L29-L30), [gemini.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/collectors/gemini.py#L54-L56)

Both ChatGPT and Gemini collectors have their own internal caches (`_cached_api_results` / `_cache_ttl = 300`), while SmartCollector already wraps them with TTL-based caching. This means:
- SmartCollector manages cache freshness and returns cached data on TTL
- But the inner collector *also* returns stale cached data if called within its own TTL

SmartCollector thinks it's getting "fresh" data (no error), but the collector is actually serving from its own internal cache. The two TTL timers can drift, and error recovery becomes unpredictable.

**Fix:** Remove the internal caching from individual collectors. SmartCollector is the single caching layer — collectors should always attempt a fresh fetch when called.

---

### T3. No Lock on `_sync_collectors()`

**File:** [collector_manager.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/collector_manager.py#L103)

`_sync_collectors()` is called on every `collect_all()` invocation but has no lock. If two concurrent requests hit `/api/limits` simultaneously, both will race through `_sync_collectors()`, potentially spawning duplicate collectors for the same `provider:account` key. The `if key not in self.smart_collectors` check is not atomic.

**Fix:** Add an `asyncio.Lock` and acquire it at the top of `_sync_collectors()`.

---

### T4. `ExternalMetricService` Side Effect in Getter

**File:** [external_metrics.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/external_metrics.py#L233-L239)

`get_all_metrics()` — a read operation — deletes stale providers from `self.metrics` as a side effect. Worse, this deletion is never persisted to disk (no `_save_unlocked()` call after the deletion), so the stale entries will reappear after a restart.

**Fix:** Either (a) persist the eviction by calling `_save_unlocked()` after deleting stale entries, or (b) move eviction to a dedicated `_evict_stale()` method that runs periodically, not inside a getter.

---

### T5. `httpx.AsyncClient` Never Closed on Shutdown

**File:** [collector_manager.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/collector_manager.py#L132-L136)

The `_client` is lazily created but never closed in the FastAPI lifespan shutdown handler. On graceful shutdown, this leaves pending connections in the connection pool.

**Fix:** Add cleanup in the lifespan context manager:
```python
yield
# Shutdown
if manager._client and not manager._client.is_closed:
    await manager._client.aclose()
```

---

### T6. Shallow Copy Doesn't Protect Nested Dicts in Cache

**File:** [smart_collector.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/smart_collector.py#L262)

```python
card_copy = {**card}  # shallow copy sufficient for flat card dicts
```

The comment says "sufficient for flat card dicts" — but `LimitCard.metadata` is a `Dict[str, Any]`. If any downstream code mutates `metadata` on the returned card, it will corrupt the cached original. The `_mark_success` path uses `copy.deepcopy()` (line 211), but `_tag_as_cached` does not.

**Fix:** Use `copy.deepcopy()` consistently, or at minimum `card_copy["metadata"] = {**card.get("metadata", {})}`.

---

### T7. Dockerfile Healthcheck Triggers Full Collection

**File:** [Dockerfile](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/Dockerfile#L64-L65)

```dockerfile
HEALTHCHECK ... CMD curl -f http://localhost:8765/api/limits || exit 1
```

Every 30 seconds, the healthcheck calls `/api/limits`, which triggers a full `collect_all()` cycle across all providers. This wastes API quota, generates logs, and could cause the healthcheck to timeout (10s) if a provider is slow.

Meanwhile, `docker-compose.yml` correctly uses `/api/health` (line 55). The Dockerfile and docker-compose are inconsistent.

**Fix:** Change Dockerfile healthcheck to `curl -f http://localhost:8765/api/health`.

---

## 🟢 Performance

### P1. No Request Coalescing on `/api/limits`

**File:** [routes.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/api/routes.py#L15-L25)

Every request to `/api/limits` triggers a full `collect_all()`. If 3 browser tabs refresh simultaneously, 3 full collection cycles run in parallel, each hitting all upstream APIs. Combined with the SmartCollector cache, only the first request actually fetches — but the overhead of spawning tasks, acquiring locks, and checking caches for 13+ collectors still adds up.

**Fix:** Implement a single-flight pattern: if a collection is already in progress, subsequent requests await the same result instead of starting a new cycle. This is especially important before background polling (Phase 1C) lands.

---

### P2. Redundant Credential File Reads in GeminiCollector

**File:** [gemini.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/collectors/gemini.py#L322-L331)

Inside the `for bucket in buckets` loop, `_get_credentials()` is called for every bucket to extract the email from `id_token`. This reads the credentials JSON file from disk on each iteration (Gemini can return 3+ buckets).

**Fix:** Hoist the `creds = await self._get_credentials()` call and email extraction above the loop.

---

### P3. `_sync_collectors()` Runs on Every Request

**File:** [collector_manager.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/collector_manager.py#L143)

`_sync_collectors()` is called at the start of every `collect_all()`. It acquires the TokenCache lock, iterates all accounts, and checks for new dynamic collectors — every single time. For the common case (no new accounts), this is pure overhead.

**Fix:** Add a simple timestamp check — only re-sync if >60 seconds have passed since the last sync.

---

## 🏗 Architecture

### A1. `Settings` Class Doesn't Use Pydantic

**File:** [config.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/core/config.py#L53)

The `Settings` class manually calls `os.getenv()` for every field. `pydantic-settings` is already in `requirements.txt` but not used. This means:
- No type validation on environment variables
- No `.env` file parsing through Pydantic (currently handled by `python-dotenv` separately)
- `int(os.getenv(...))` will crash with an unhelpful `ValueError` if the env var contains a non-integer

**Fix:** Refactor `Settings` to extend `pydantic_settings.BaseSettings`. This gives you automatic `.env` loading, type coercion and validation, and a cleaner declaration.

---

### A2. Frontend Polling Architecture Doesn't Scale

**File:** [app.js](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/frontend/js/app.js#L96-L101)

The frontend polls `/api/limits` on a fixed interval (30s/60s/5m). Each poll triggers full server-side collection. As the number of providers and accounts grows, this becomes the bottleneck.

For 1.0, this works. Post-1.0, consider:
- **Server-Sent Events (SSE):** The server pushes updates when new data arrives (natural fit with background polling from Phase 4C). The frontend opens a single persistent connection.
- This eliminates the "poll → collect → respond" cycle entirely and makes the dashboard feel real-time.

---

### A3. `ExternalMetricService` Writes to Disk on Every Ingest

**File:** [external_metrics.py](file:///Users/bjoern/Documents/Projects/AI-Usage-Tracker/app/services/external_metrics.py#L46-L68)

Every `update_metrics()` and `metrics_update_from_ingest()` call writes the entire metrics dict to disk via `json.dump()`. For a sidecar sending data every 60 seconds across 5 providers, that's 5 disk writes per minute — each serializing the entire state.

**Fix:** Debounce disk writes. Write at most once every N seconds (e.g., 30s), or only on shutdown. The in-memory dict is the source of truth during runtime; the file is just crash recovery.

---

## 📋 Summary Table

| ID | Category | Severity | Effort | Description |
|:---|:---|:---|:---|:---|
| **S1** | Security | 🔴 High | Trivial | Exception handler leaks internals |
| **S2** | Security | 🔴 High | Small | No rate limiting on endpoints |
| **S3** | Security | 🟡 Med | Trivial | Health endpoint exposes cache metadata |
| **S4** | Security | 🟡 Med | Trivial | GitHub token non-atomic write |
| **S5** | Security | 🟡 Med | Trivial | ChatGPT token non-atomic write |
| **S6** | Security | 🟡 Med | Small | CORS origins hardcoded |
| **T1** | Stability | 🔴 High | Trivial | Dual CollectorManager instances |
| **T2** | Stability | 🟡 Med | Small | Double-caching in collectors |
| **T3** | Stability | 🟡 Med | Trivial | No lock on `_sync_collectors()` |
| **T4** | Stability | 🟡 Med | Trivial | Side effect in getter + no persistence |
| **T5** | Stability | 🟢 Low | Trivial | httpx client never closed |
| **T6** | Stability | 🟢 Low | Trivial | Shallow copy on cached metadata |
| **T7** | Stability | 🟡 Med | Trivial | Dockerfile healthcheck triggers collection |
| **P1** | Performance | 🟡 Med | Small | No request coalescing |
| **P2** | Performance | 🟢 Low | Trivial | Redundant credential reads in loop |
| **P3** | Performance | 🟢 Low | Trivial | `_sync_collectors` on every request |
| **A1** | Architecture | 🟡 Med | Small | Settings class not using pydantic-settings |
| **A2** | Architecture | 🟢 Low | Medium | Polling doesn't scale (post-1.0) |
| **A3** | Architecture | 🟢 Low | Small | Disk writes on every ingest |

---

## 💡 Feature Ideas

### For 1.0

- **API Versioning:** Prefix all routes with `/api/v1/` before going public. Avoids a painful migration later.
- **Structured Logging:** Add a JSON logging formatter option (`LOG_FORMAT=json`) for Docker/production. Currently only human-readable plaintext.
- **Single-Flight Collection:** Request coalescing (P1 above) should ship before 1.0 — it's a correctness issue under concurrent load.

### Post-1.0

- **Server-Sent Events (SSE):** Replace frontend polling with push-based updates. Natural fit with Phase 4C background refresh.
- **Per-Provider Refresh:** Allow the frontend to request a refresh for a single provider (e.g., "refresh just Anthropic") instead of triggering all collectors.
- **Usage Alerts / Budget Caps:** User-defined thresholds (e.g., "alert me when Claude usage exceeds $50/month") stored in SQLite, evaluated by the background loop.
- **Multi-User Mode:** Multiple Runway users sharing a single server (e.g., team deployment). Requires auth layer + per-user account isolation.
