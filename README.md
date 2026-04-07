# Runway — AI Subscription Limits Dashboard

**Runway** is a local-first, stateless monitoring tool designed to track remaining capacity and reset timers across your entire generative AI stack. Instead of digging through opaque usage menus, Runway aggregates everything into a single, high-performance glassmorphism dashboard.

![Runway Dashboard](file:///Users/bjoern/.gemini/antigravity/brain/53ba3247-9958-4671-8ffc-419e940bc0eb/runway_dashboard_final_1775511401280.png)

## 🚀 Features

- **11+ Services Integrated**: Support for Claude, Gemini, GPT-4, OpenCode, and more.
- **Resilient Rendering**: Individual API failures or malformed responses won't break the dashboard; failing services gracefully show "Error Cards."
- **Real-Time Sync**: Pings live APIs and parses local log/state files simultaneously.
- **Stateless & Secure**: No database required. Keeps your API keys safe in a local `.env` file.
- **Health Indicators**: Dynamic visual cues (Good/Warning/Critical) based on your remaining quota or prepaid balance.
- **Humanized Timers**: Countdown clocks for when your limits will reset.

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.9+) with `httpx` for async concurrency.
- **Frontend**: Vanilla HTML5, JavaScript, and Tailwind CSS (Glassmorphism UI).
- **Local Parsing**: Supports SQLite (OpenCode TUI), JSONL (Claude/Codex), and JSON (Gemini/Antigravity).

## 🔌 Supported Services

Currently monitoring **11 data sources**:
1.  **Claude (OAuth)**: Primary cloud monitoring for Pro/Personal accounts (supports 5h and 7d windows).
2.  **Claude (Local Logs)**: Fallback parser for local `~/.claude` activity logs.
3.  **Gemini CLI**: Monitors `~/.gemini/state/quota.json` for terminal-based usage.
4.  **OpenCode TUI**: Tracks local line-change metrics from `opencode.db`.
5.  **OpenCode Go**: Live cloud usage and USD balance via `api.opencode.ai`.
6.  **GitHub Copilot**: Live API rate limit tracking for Copilot Chat and Indent.
7.  **zAI (GLM)**: Prepaid balance tracking via BigModel Cloud (BigModel API).
8.  **Kimi K2.5**: Prepaid balance tracking via Moonshot AI.
9.  **ChatGPT Codex**: Local `~/.codex` session log parsing.
10. **Antigravity IDE**: Multi-model telemetry (`gemini-3.1-pro`, `claude-3-5-sonnet`, `o3-mini`) from `~/.antigravity` state.

## 📦 Setup

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment**:
    Create a `.env` file in the root directory (see `.env.example` for details).

3.  **Run the App**:
    ```bash
    python3 -m app.main
    ```
    Access the dashboard at `http://127.0.0.1:8765`.

---
*Built for the 2026 Developer Workflow.*
