# ChatGPT Collector

**File:** `app/services/collectors/chatgpt.py`

ChatGPT Codex quota collector with OAuth-backed API and local session cache fallback.

## Overview

- **Collection Strategy**: OAuth API → Local session cache
- **Cards**: 1 card (primary window usage)
- **Authentication:** `CHATGPT_OAUTH_TOKEN` env var OR `~/.codex/auth.json`

## Data Sources

### Primary: ChatGPT wham/usage API
**Endpoint:** `chatgpt.com/backend-api/wham/usage`
**Auth:** Bearer token

**Token Sources:**
1. `CHATGPT_OAUTH_TOKEN` environment variable
2. `~/.codex/auth.json` (Codex CLI cache)

### Secondary: Local Session Cache
**Location:** `~/.codex/sessions/*.jsonl`
**Tracks:** `used_percent`, `resets_at` from latest session file

## Output Format

```python
{
    "service": "ChatGPT Codex",
    "icon": "💬",
    "remaining": "54.5%",
    "unit": "remaining",
    "reset": "Resets in 4h 30m",
    "health": "good",
    "pace": "Stable",
    "detail": "API: wham/usage",
    "used_value": 45.5,
    "limit_value": 100.0,
    "is_unlimited": False,
    "unit_type": "percent",
    "reset_at": "2026-04-07T15:00:00+00:00",
    "data_source": "oauth",
    "tier": None,
    "usage_url": None,
    "updated_at": "2026-04-07T10:30:00+00:00"
}
```

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `CHATGPT_OAUTH_TOKEN` | Optional | OAuth token for API access |

## Sidecar Support

Sidecar extracts token from `~/.codex/auth.json`. See [sidecar documentation](../sidecar.md).

## Troubleshooting

### "No logs/auth" error
**Fix:**
1. `export CHATGPT_OAUTH_TOKEN="your-token"`
2. Or install Codex CLI: `npm install -g @openai/codex && codex auth login`

### API Error (401)
**Fix:** Token expired - re-authenticate with Codex CLI or extract new token from browser

## Related Files

| File | Purpose |
|------|---------|
| `app/services/collectors/chatgpt.py` | Main collector |
| `scripts/sidecar.py` | Sidecar implementation |

## References

- **Codex CLI:** https://github.com/openai/codex
