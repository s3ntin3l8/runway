# Future Ideas & Improvements

This document tracks planned enhancements for Runway, organized by category and priority. Items that have been implemented are periodically removed to keep this document focused and actionable.

---

## High Priority

### 1. GitHub OAuth Device Flow
**File**: `app/services/collectors/github.py` + frontend  
**Severity**: High  
**Effort**: 6-8 hours

Replace manual `GITHUB_TOKEN` entry with the official [Device Flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow). 
- Display user code in frontend.
- Poll for access token in background.
- Particularly useful for headless/Docker environments where browser redirects are difficult.

### 2. ChatGPT Web Dashboard Scraping
**File**: `app/services/collectors/chatgpt.py` (new)  
**Severity**: High  
**Effort**: 1-2 days

Implement optional scraping of `https://chatgpt.com/codex/settings/usage` to get rate limits, credits, and detailed usage charts.
- Support manual `Cookie:` header input for headless environments.
- Support automatic cookie extraction from Safari/Chrome/Firefox on macOS (experimental).

---

## Medium Priority

### 1. Dashboard Auto-Refresh UI Toggle
**File**: `frontend/index.html` + `frontend/js/app.js`  
**Severity**: Medium  
**Effort**: 2-3 hours

**Current Issue**: Dashboard doesn't auto-refresh, static view.

**Suggested Implementation**:
Add an "Auto-refresh" toggle with configurable intervals (30s, 60s, 5m). Store preference in `localStorage`.

### 2. Move Away from Hardcoded Limits
**Files**: `app/services/collectors/*.py`  
**Severity**: Medium  
**Effort**: 1-2 days

**Current State**: Some collectors (like Claude local fallback) have hardcoded limits (e.g., 2M tokens).

**Suggested Approach**:
- Query local IDE config files for plan information.
- For Anthropic: check `~/.claude/.credentials.json` for subscription tier.
- Store limits in config, not in code.

### 3. Multi-Browser Cookie Support
**Files**: `app/core/chrome_cookies.py`, `app/services/collectors/*.py`  
**Severity**: Medium  
**Effort**: 4-6 hours

Currently only Chrome is supported for automatic cookie extraction. Add support for:
- **Firefox** (`cookies.sqlite`)
- **Safari** (`Cookies.binarycookies`, macOS only)
- **Edge** (similar to Chrome)

### 4. Error Card Categorization (Field Addition)
**File**: `app/core/utils.py`  
**Severity**: Medium  
**Effort**: 2-3 hours

**Current Issue**: All errors look identical.

**Suggested Enhancement**:
Add an `error_type` field to the `error_card()` return dictionary.
- Types: `missing_config`, `auth_failed`, `rate_limited`, `timeout`, `parse_error`.
- Update frontend to style these categories differently (e.g., color-coded dots or icons).

---

## Sidecar & Ingestion

### 1. Daemon Mode
**File**: `scripts/sidecar.py`  
**Severity**: Medium  
**Effort**: 2-3 hours

Support a `--daemon` flag to run as a persistent process with a configurable sleep interval, providing more real-time updates than 30m crontab tasks.

### 2. Offline Queuing
**File**: `scripts/sidecar.py`  
**Severity**: Medium  
**Effort**: 4-6 hours

If the ingestion API is unreachable, cache collected metrics in a local SQLite/JSON file and retry upon the next successful connection.

### 3. Binary Sidecar Distribution
**File**: `sidecar/` (build scripts)  
**Severity**: Medium  
**Effort**: 1-2 days

Distribute the sidecar as a single-binary (using PyInstaller) to avoid Python dependency issues on host machines.

---

## Architecture & Refinement

### 1. Formalize Strategy Pattern
**File**: `app/services/collectors/base.py`  
**Severity**: Low  
**Effort**: 2-3 hours

The 3-tier fallback is described in docstrings but not enforced by the `BaseCollector` interface. Implement formal abstract methods like `_primary_strategy()`, `_fallback_strategy()`, and `_error_handler()` to enforce consistency across new collectors.

### 2. Lazy Load Collectors
**File**: `app/services/collector_manager.py`  
**Severity**: Low  
**Effort**: 2-3 hours

Currently all collectors instantiate on startup. Could lazy-load only requested ones based on configuration to reduce memory footprint and startup time.

### 3. Concurrent Collector Timeout Protection
**File**: `app/services/collector_manager.py`  
**Severity**: Low  
**Effort**: 2-3 hours

Add global timeout across all collectors (not just individual ones) to ensure the API never hangs indefinitely.

### 4. Docker Multi-Stage Build Optimization
**File**: `Dockerfile`  
**Severity**: Low  
**Effort**: 1-2 hours

Transition the `Dockerfile` to a multi-stage build to reduce final image size.
- Use a builder stage to install `gcc`, `libsqlite3-dev`, and pip packages into a `/opt/venv`.
- Copy only the `/opt/venv` and source code to the final `python:3.12-slim-bookworm` stage.
- Expected to significantly decrease image footprint and improve security.

---

## Documentation

### 1. Architecture Decision Records (ADRs)
**File**: `docs/adr/`  
**Severity**: Low  
**Effort**: 1 day

Document key decisions:
- Choice of local-first over centralized API.
- Stateless design (no database).
- Environment-based credentials.

### 2. Troubleshooting Guide
**File**: `docs/TROUBLESHOOTING.md`  
**Severity**: Low  
**Effort**: 2-3 hours

Guide for common issues: expired tokens, 429 rate limits, cookie extraction failures.

---

## Future Research (Low Priority)

### 1. Historical Tracking & Burndown Charts
Track usage over time in a local SQLite DB (`~/.runway/history.db`) to provide trend analysis and ETA for quota exhaustion. (Note: violates current stateless principle).

### 2. Metrics Export Formats (Prometheus/CSV)
Add `/api/limits?format=prometheus` or `format=csv` for integration with external monitoring systems or spreadsheets.

### 3. Webhook Notifications
Send Discord/Slack alerts when quotas cross certain thresholds (e.g., >90% used).

### 4. Antigravity: Active API Connection
Research connecting to the running Antigravity process/language server via local port discovery (similar to CodexBar analysis) instead of reading JSON files.

### 5. Anthropic "Extra Usage" Support
Implement detection and rendering for paid credits (`extra_usage` field in OAuth API) showing spend vs limit.

---

## Collector-Specific Ideas (from docs migration)

### Claude

#### CLI PTY Parsing (5th Tier Fallback)
**Status**: Not implemented
**File**: `app/services/collectors/anthropic.py`

Spawn `claude` CLI in a PTY and parse `/usage` output. Would slot as 4th tier (before error cards):
```
OAuth API → Web API → Local Logs → CLI PTY → Error Cards
```

| Aspect | CLI PTY |
|--------|---------|
| **Requires** | CLI binary |
| **Data Quality** | Complete (same as OAuth) |
| **Speed** | Slow (process spawn) |
| **Reliability** | Low (fragile parsing) |

#### Alternative Endpoint: v1/rate_limits
**Endpoint**: `https://api.anthropic.com/v1/rate_limits`

Simpler data structure (single window vs per-window). Could add as fallback between OAuth and Web API:
```
OAuth API → v1/rate_limits → Web API → Local Logs → Error
```

#### Firefox/Safari Cookie Support
Extend `chrome_cookies.py` to support Firefox (`cookies.sqlite`), Safari (`Cookies.binarycookies`), and Edge.

#### Windows Credential Store
Add Windows Credential Manager support for sidecar token extraction (currently macOS Keychain only).

---

### Gemini

#### CLI `/stats` Parsing (Tertiary Fallback)
Parse `gemini /stats` CLI output for quota percentages. Would slot between OAuth API and session logs:
```
OAuth API → CLI /stats (quota %) → Session Logs (token counts)
```

| Aspect | CLI /stats |
|--------|------------|
| **Requires** | gemini CLI binary |
| **Data Quality** | Quota % visible |
| **Speed** | Slow (subprocess) |
| **Reliability** | Low (fragile parsing) |

---

### GitHub Copilot

#### OAuth Device Flow
Already tracked in High Priority section above.

---

### ChatGPT

#### Web Dashboard Scraping
Already tracked in High Priority section above.

---

### OpenCode

#### Direct API Key Authentication
**Status**: Deprecated

OpenCode previously supported `OPENCODE_GO_API_KEY` for direct API access, but endpoints (`api.opencode.ai/v1/user/usage`) now return 404. Continue using Chrome cookie authentication.

---

### Kimi API

#### Usage History API
Query usage history for daily/monthly spend tracking, model-specific breakdown, cost per 1K tokens.

#### Tier Detection
Show current pricing tier if Moonshot introduces tiers (currently single tier).

---

### Antigravity

#### File Watching
Use `watchdog` or `inotify` to watch for quota file changes instead of polling.

#### API Fallback
If Antigravity exposes an API, add as fallback to file-based collection.

#### LSP Protocol Approach
**Reference**: [CodexBar Implementation](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md)

Use active LSP protocol instead of passive file reading:
1. Detect `language_server_macos` process with Antigravity markers
2. Probe listening ports with HTTPS POST to `/GetUnleashData`
3. Call `GetUserStatus` endpoint with CSRF token

| Aspect | File-Based (Current) | LSP Protocol |
|--------|---------------------|--------------|
| **Requires** | File permission | Process + port scan |
| **Reliability** | IDE-dependent | Real-time |
| **Complexity** | Low | High |

**Priority**: Low-Medium

---

*Last updated: 2026-04-08*
