# Future Ideas & Improvements

This document tracks planned enhancements and architectural recommendations for Runway. Items are organized by category and status.

---

## 🏗️ Core Platform Evolution (2026 Roadmap)

### 1. Stateful Usage & Configuration Hub
**Effort:** Large | **Status:** Architecture Approved (April 2026)
This is the foundational shift from a purely stateless monitor to a stateful local-first application using **SQLite** and **SQLModel**.

*   **Usage History:** A "Max Variant" schema capturing universal metrics (cost, tokens) and provider-specific JSON metadata for deep-dive trends.
*   **Settings UI:** A dedicated management page with a Top Navbar (Dashboard | History | Settings) to replace/augment `.env` configuration.
*   **Machine-Key Encryption:** Securing API keys in the local DB using `cryptography.fernet` to maintain Docker-friendly security.
*   **Passive Background Polling:** A 15-minute background loop ensuring data is captured even when the UI is closed, synchronized via TTL caches.
*   **Token Health & Proactive Refresh:** A "Health Dashboard" within settings showing exact expiry times for cookies/OAuth tokens. Includes a proactive background service to renew browser sessions before they expire and break workflows.

### 2. Sidecar Fleet Management
**Effort:** Medium | **Status:** Planned
*   **Sidecar Registry:** A UI overview of all remote machines sending data to the central Runway instance.
*   **Centralized Remote Configuration:** Control exactly which APIs and log files each sidecar monitors directly from the main Runway Settings UI. Sidecars pull their specific configuration profile (e.g., enable/disable GitHub Copilot tracking on a specific machine) from the server upon connection.
*   **Environment/Project Tagging:** Allow users to assign "Tags" to sidecars (e.g., `Work_Laptop`, `Personal_Desktop`) to enable history filtering and accurate cost center reporting.
*   **Advanced Auth:** Support for rotating secrets or OIDC-based tokens for high-security multi-host deployments.

### 3. Intelligent Polling & Power Efficiency
**Effort:** Medium
*   **Dynamic Backoff ("Sleep Mode"):** Automatically detect user inactivity (no usage changes across 3 polls) and drop polling frequency to once every 2 hours to save battery and bandwidth.
*   **Instant Wake:** Snaps back to high-frequency polling as soon as fresh usage is detected or the UI is opened.

### 4. Multi-Account & Tenant Isolation
**Effort:** Large | **Status:** Brainstorming
*   **The Problem:** Currently, the `TokenCache` and backend key tokens and snapshots solely by `provider_id` (e.g., `anthropic`). If multiple sidecars send different accounts' cookies, or one user rotates multiple accounts, they overwrite each other. This causes race conditions and broken "oscillating" history charts as the poll flips between different account limits.
*   **Account-Based Keying:** Refactor the backend to key tokens and database snapshots by a unique `account_id` or `profile_name` (e.g., `(provider_id, account_hash)`).
*   **Smart Collector Iteration:** Update collectors to iterate through all known active accounts for a provider, polling each independently and generating separate `LimitCard` entries (e.g., "Claude Pro (Work)", "Claude Free (Personal)").
*   **UI Aggregation:** Add the ability for users to choose whether to aggregate multiple accounts into a single "Total Quota" or split them out individually.

---

## 📊 Dashboard & UI Enhancements

### 5. Context-Aware Dashboard Reorganization (Evolution)
**Effort:** Medium | **Status:** Architecture Approved (April 2026)
As the number of providers, sidecars, and multi-account configurations grows, the flat grid will be reorganized into a more structured hierarchy.
- **Grouping by Provider (Sectioned Grid):** Transition from a single flat grid to horizontal sections grouped by `provider_id` (e.g., an "Anthropic" section followed by an "OpenAI" section), each with its own header and logo.
- **Context Filters:** Add segmented control pills at the top of the dashboard (e.g., `[All]`, `[Work]`, `[Personal Laptop]`, `[Alice's Account]`) to instantly filter visible cards based on sidecar tags or account profiles.
- **Visual Badging & Avatars:** Add elegant corner badges or tiny avatars to cards to identify their source (e.g., a laptop icon for a specific sidecar, or an initial for a user account) without breaking the glassmorphism aesthetic.

### 6. Chart.js Visualizations
**Effort:** Medium
Replace static cards with interactive time-series charts showing financial burn rates, token volume trends, and comparative provider usage.

### 7. Metrics Export & Webhooks
*   **CSV Expense Reporting:** Add a "Download CSV" button to the History page to generate formatted expense reports for tax write-offs or employer reimbursement.
*   **Prometheus:** Add `/api/limits?format=prometheus` for external monitoring integrations.
*   **Webhooks:** Send Discord/Slack alerts when quotas cross critical thresholds (e.g., >90% used).

---

## 💻 Desktop Integration

### 8. Native Desktop Sidecar (Binary + Menubar App)
**Effort:** Large  
**Goal:** Distribute the sidecar as a true, zero-dependency desktop application (PyInstaller) that provides real-time visibility and configuration across both GUI and headless environments.

*   **OS-Native Desktop Notifications:** Leverages macOS/Windows notification centers to warn users about critical quota limits or expired browser sessions directly on their desktop.
*   **Hybrid Operation (GUI & Headless):**
    *   **Desktop Mode:** A system tray icon (Windows) or Menubar app (macOS) with a right-click menu showing connection status, last sync, and a "Settings..." option.
    *   **Headless Mode:** Automatically detects environments without a display (Linux servers, Docker, VPS) or uses a `--headless` flag to run as a pure background daemon.
*   **Lightweight Configuration:**
    *   **GUI Settings:** Uses Python's built-in `tkinter` for a zero-dependency, native dialog box to configure the Central Runway URL and Ingest API Key.
    *   **Unified Config:** Reads settings from `~/.runway/sidecar.json`, CLI flags, or environment variables (`RUNWAY_URL`, `INGEST_API_KEY`).
*   **Deployment & Persistence:**
    *   **Linux Systemd:** Provides a one-line install script to register the headless binary as a `systemd` service for permanent background execution on code servers.
    *   **Auto-Update:** The compiled executable checks GitHub releases for a new binaries and hot-swaps itself.

---

## 📝 Documentation & Security

### 9. Architecture Decision Records (ADRs)
**File:** `docs/adr/` | **Effort:** 1 day
Formally document the transition to stateful local-first design and environment vs. UI-based credentials.

### 10. Troubleshooting & Setup Guide
**File:** `docs/TROUBLESHOOTING.md`
Centralized guide for expired tokens, 429 rate limits, and cross-platform cookie extraction.

---

## 🔍 Established Architecture (Design Principles)

*These principles ensure Runway remains resilient and performant.*

### Collector Pattern & Multi-Tier Fallback
Each provider implements a multi-tier strategy to ensure the UI remains functional:
1. **OAuth API**: Primary source for high-quality, real-time data.
2. **Web API**: Secondary source using browser sessions/cookies.
3. **Local Log Parsing**: Tertiary source for offline/unauthenticated metrics.
4. **Graceful Error Cards**: Prevents UI crashes during total collection failure.

### Smart Differential Fetching
The `SmartCollector` wrapper manages the lifecycle of data fetching:
- **TTL Caching**: Prevents API rate limiting (e.g., Gemini: 5m, Claude: 10m).
- **Error Backoff**: Prevents hammering APIs during outages or 429 errors.
- **Graceful Degradation**: Serves stale data with a `[Cached]` tag during temporary failures.

---

*Last updated: 2026-04-11*
