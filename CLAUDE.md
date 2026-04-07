# CLAUDE.md - Runway (AI Usage Tracker)

## 🎯 Project Identity & Context
**Runway** is a local-first, stateless monitoring tool for tracking AI provider quotas and balances (Claude, Gemini, ChatGPT, GitHub Copilot, etc.). It is designed to be modular and resilient, often running in containerized or headless environments.

## 🏗️ Architecture & Data Fetching
- **Modular Services**: Each provider has a dedicated collector in `app/services/collectors/`.
- **API First & Local Fallback**: Prefers direct HTTP requests; falls back to local log parsing (e.g., `~/.claude/activity.log`) when necessary.
- **Sidecar Ingestion**: Supports external metrics via `POST /api/ingest` (Ingestion API).
- **Stateless**: No centralized database. Uses Pydantic for validation and in-memory aggregation.

## 🚫 Absolute Constraints (The Docker Rule)
Avoid writing code that relies on native desktop UI features if the app is intended for a headless Docker environment:
- **DO NOT** attempt to scrape desktop-only keychains if not supported by the environment.
- **Paths**: Use environment variables or relative paths configurable via `.env`.

## 💻 Tech Stack & Coding Standards
- **Runtime**: Python 3.9+ (FastAPI).
- **Concurrency**: `httpx` (async) for all network calls.
- **Validation**: Pydantic v2 for models (`app/models/`).
- **Styling**: Vanilla CSS (Modern glassmorphism) + Tailwind CSS in the frontend.

### Commands
- **Install**: `pip install -r requirements.txt`
- **Run (Dev)**: `uvicorn app.main:app --reload --port 8765`
- **Run (Production)**: `python3 -m app.main`
- **Test (Ingest API)**: `python3 scripts/test_ingest.py`
- **Manual Test (CURL)**: `curl -X POST http://localhost:8765/api/ingest -H "Content-Type: application/json" -d '{"provider": "claude", "metrics": {...}}'`

### Coding Patterns
- **Error Handling**: Graceful degradation. If a provider API fails, catch the error and return an "Error Card" status instead of crashing the dashboard.
- **Async**: Everything from endpoint to collector should be `async`.
- **Typing**: Use explicit type hints and Pydantic models for all API responses and internal data structures.
- **Surgical Precision**: Only modify what is strictly necessary. Preserve existing comments and structure.
- **Reasoning Phase**: For complex logic changes, briefly explain the architectural approach before outputting code.

## 🤖 Behavior Guidelines
1. **Be Resilient**: Always consider what happens if an external API is down or a file is missing.
2. **Prioritize UI**: Frontend changes should be premium, high-performance, and maintain the glassmorphism aesthetic.
3. **Keep it Stateless**: Avoid adding persistent databases unless strictly required for a new feature (prefer local file parsing/ENV).