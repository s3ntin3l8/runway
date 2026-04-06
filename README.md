# Runway — AI Subscription Limits Dashboard

**Runway** is a local-first, stateless monitoring tool designed to track remaining capacity and reset timers across your entire generative AI stack. Instead of digging through opaque usage menus, Runway aggregates everything into a single, high-performance glassmorphism dashboard.

![Runway Dashboard](file:///Users/bjoern/.gemini/antigravity/brain/53ba3247-9958-4671-8ffc-419e940bc0eb/runway_dashboard_final_1775511401280.png)

## 🚀 Features

- **9+ Services Integrated**: Support for Claude, Gemini, GPT-4, OpenCode, and more.
- **Real-Time Sync**: Pings live APIs and parses local log/state files simultaneously.
- **Stateless & Secure**: No database required. Keeps your API keys safe in a local `.env` file.
- **Health Indicators**: Dynamic visual cues (Good/Warning/Critical) based on your remaining quota.
- **Humanized Timers**: Countdown clocks for when your limits will reset.

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.9+) with `httpx` for async concurrency.
- **Frontend**: Vanilla HTML5, JavaScript, and Tailwind CSS.
- **Local Parsing**: Supports SQLite (OpenCode TUI), JSONL (Claude/Codex), and JSON (Gemini/Antigravity).

## 🔌 Supported Services

Currently monitoring **11 data sources**:
1.  **Claude Pro**: Parses local `~/.claude` activity for 5h rolling windows.
2.  **Gemini CLI**: Monitors `~/.gemini` session logs.
3.  **OpenCode TUI**: Local SQLite metrics from `opencode.db`.
4.  **OpenCode Go**: Live cloud usage via `api.opencode.ai`.
5.  **GitHub Copilot**: Live API rate limit tracking.
6.  **zAI (GLM Coding)**: Verified monitoring via `api.z.ai/api/monitor`.
7.  **Kimi K2.5**: Prepaid balance tracking via Moonshot API.
8.  **ChatGPT Codex**: Local `~/.codex` rollout event parsing.
9.  **Antigravity IDE**: Multi-model telemetry (`gemini-3.1-pro`, `claude-3-5-sonnet`, `o3-mini`) from `~/.antigravity/state/quota.json`.

## 📦 Setup

1.  **Install Dependencies**:
    ```bash
    pip install fastapi uvicorn httpx python-dotenv aiosqlite
    ```

2.  **Configure Environment**:
    Copy `.env.example` to `.env` and add your API keys:
    ```bash
    cp .env.example .env
    ```

3.  **Run the App**:
    ```bash
    python3 -m uvicorn main:app --reload --port 8765
    ```
    Access the dashboard at `http://localhost:8765`.

---
*Built for the 2026 Developer Workflow.*
