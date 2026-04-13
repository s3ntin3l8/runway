# UI Redesign — Runway Dashboard, History & Settings

**Date:** 2026-04-13
**Status:** Approved design, pending implementation

---

## Overview

A focused visual and usability overhaul across three areas: the Dashboard (provider card design, overview bar, drill-down modal), the History tab (charts, filters), and the Settings tab (layout, per-provider config). The core aesthetic (dark glassmorphism, Tailwind/Zinc palette) is unchanged — this is a restructuring and information-density improvement, not a visual rebrand.

---

## 1. Dashboard

### 1A. Top Health Bar

Replaces the implicit "scan the cards to know the overall state" experience with an explicit KPI row at the top of the Dashboard view, above all provider sections.

**Design:** Four stat tiles in a horizontal row (Critical / Warning / Good / Unlimited), each showing a large count and a label. A proportional segmented bar (colored by health state, widths proportional to count) runs across the full width below the tile row.

```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│    2     │ │    1     │ │    4     │ │    1     │
│ Critical │ │ Warning  │ │  Good    │ │Unlimited │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
(red)  (amber)             (green)          (violet)
```

- Tiles have colored borders matching health state (red/amber/green/violet)
- Bar segment widths are proportional to counts, not equal
- Unlimited tile uses violet to distinguish from "good"
- Tiles with zero count are dimmed but still shown (maintains layout stability)

### 1B. Provider Summary Cards

Each provider collapses into a single aggregate card. Cards are grouped in a grid. The card has two zones:

**Top zone:**
- Provider icon + name (uppercase, small, zinc-400)
- Tier badge next to provider name (e.g. `PRO` in amber) — uses the account's tier; one tier per account
- Account email label below the provider name (small, zinc-500)
- Health badge top-right (CRIT / WARN / GOOD in colored pill)
- Large bold worst-metric number (e.g. `91%`) colored by health
- Sub-label: which service holds the worst value (e.g. `Haiku · worst`)

**Bottom zone (darker background):**
- Proportional segmented bar (same logic as health bar, per-service health distribution)
- Per-service breakdown rows: `● Service name` on left, `Tier badge · % value` on right
- Health dot color per row matches service health

**Multi-account variant:** When a provider has multiple accounts, account labels appear as small pills (e.g. `john@work.com` `jane@personal.com`). The breakdown rows append a short account hint `(john)` / `(jane)` after the service name. Multi-account tier handling is deferred — show the dominant (most common) tier.

**Interaction:** Clicking anywhere on the card opens the provider modal.

### 1C. Provider Drill-down Modal

A centered modal (existing modal infrastructure) showing full detail for all services under a provider.

**Modal header:**
- Provider icon + name
- Account email + service count + window type
- Close button

**Service rows** (one per service, ordered by health severity):
- Service name (bold)
- Badges row: health badge + tier + data source + pace icon
- Sparkline (64×28px SVG) showing the last 7 days of `used_value` trend, colored by health — dot at the rightmost point
- Used/limit formatted values + reset time
- Progress bar (3px, colored by health)

The modal reuses the existing modal backdrop/animation infrastructure. No new navigation is introduced.

---

## 2. History Tab

### 2A. Sparkline Summary Strip

A row of small sparkline cards sits above the main chart, one per provider. Each card shows:
- Provider icon + name
- 7-day mini sparkline (SVG, colored by current health)
- Current usage value with a trend arrow (↑ / → / ↓ based on 7d slope)

Clicking a sparkline card filters the main chart to that provider (toggles it; clicking again deselects). Active provider cards are highlighted with a colored border.

### 2B. Main Chart Controls

The existing Chart.js stacked bar / line chart gains a controls row above it:

- **Time range selector:** `7d` / `30d` / `90d` pill buttons (default: 7d). Updates both the sparkline strip and main chart. Passes `days` param to `/api/v1/usage/history`.
- **Per-provider toggle chips:** Auto-generated from live data. Active providers shown as colored chips, inactive as dim. Synced with sparkline card selection.
- **Metric switcher:** `% used` / `tokens` / `cost` — switches the Y-axis unit and data series. Requires backend to return the right fields (already available in snapshots).

### 2C. History Table

Unchanged structurally. CSV download button inherits the active time range and provider filters (passes them as query params). Table shows up to 50 rows matching the active filter.

---

## 3. Settings Tab

### 3A. Layout

The single narrow glass panel is replaced by a two-pane layout:

- **Left:** Sidebar nav with four items — `🔌 Providers`, `🔑 Tokens`, `🔔 Webhooks`, `⚙️ System`. Active item highlighted. Width: ~120px fixed.
- **Right:** Content pane for the selected section, full remaining width.

Default section on first open: **Providers**.

### 3B. Providers Section (Master-Detail)

Within the Providers content pane, a secondary split:

- **Left column (~130px):** Scrollable list of configured providers. Each row: provider icon + name + active/disabled badge. Selected provider highlighted. `+ Add` button at top.
- **Right column (flex):** Config form for the selected provider.

**Provider config form fields:**

| Field | Type | Notes |
|---|---|---|
| Enabled | Toggle | Disables polling without removing config |
| API Key | Masked text input + edit button | Stored encrypted if `DB_ENCRYPTION_KEY` set |
| Account Label | Text input | Overrides auto-detected email |
| Poll Interval | Select or text input | Default: 15m. Override per-provider. |
| Browser Preference | Text input | Comma-separated order e.g. `safari,chrome,firefox` |

Save / Discard buttons at bottom right of the form. Save writes to a new `provider_configs` table (or extends existing settings). Changes take effect on the next poll cycle — no restart required.

> **Note:** API keys entered here take precedence over env vars. Env vars remain as a fallback and for Docker/CI deployments. This is additive — no breaking change to existing env-var users.

### 3C. Tokens Section

Existing token health panel, promoted to its own section. Shows all cached OAuth credentials with status badges (VALID / EXPIRING / EXPIRED / UNKNOWN), expiry timestamps, and REFRESH buttons for supported providers (Anthropic, Gemini OAuth).

### 3D. Webhooks Section

Existing webhook CRUD UI, promoted to its own section. Replace `prompt()` / `alert()` interactions with inline form rows. No functional change to the webhook API.

### 3E. System Section

Read-only system info: Run Mode, Host:Port, Local Collectors status, Credential Scraping status, Database Encryption status. Displayed as a compact key-value list.

---

## Out of Scope

- Multi-account tier differentiation on provider cards (deferred)
- Fleet tab redesign (not discussed)
- Light/bright mode refinement (not discussed)
- Server-Sent Events / live push (post-1.0 roadmap item)
- Per-provider webhook thresholds UI (covered by existing webhook CRUD)

---

## Backend Changes Required

| Change | Reason |
|---|---|
| New `provider_configs` table (or extend settings model) | Store per-provider API keys, labels, poll intervals, browser pref |
| `GET/PUT /api/v1/system/provider-config` | Read/write provider config from Settings UI |
| History endpoint `days` param already exists | Frontend just needs to wire it to the time range selector — no backend change |
| History endpoint `provider_id` filter already exists | Frontend wires active provider toggle chips to it — no backend change |

---

## Implementation Notes

- All sparklines are lightweight inline SVGs — no additional Chart.js instances
- Modal sparklines (1C) require a `GET /api/v1/usage/history?provider_id=X&days=7` fetch on modal open — the data isn't in the existing card payload
- Provider modal reuses existing `#modal-container` / `#modal-content` infrastructure
- Sidebar nav state persists in `localStorage` (remembers last section)
- Provider config form uses the same glass-panel card language as the rest of the app
- No new dependencies required
