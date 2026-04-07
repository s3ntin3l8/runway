# Kimi Coding Collector (IDE)

**File:** `app/services/collectors/kimi_coding.py`

Kimi For Coding IDE quota collector with weekly and rate limit tracking.

> **Note:** This collector tracks IDE quotas (weekly + rate limits). For API balance, see [Kimi API Collector](kimi_api.md).

---

## Overview

The Kimi Coding collector retrieves quota information from the Kimi For Coding IDE (https://www.kimi.com/code). This is a separate service from the Moonshot API and uses different authentication and endpoints.

### Key Features

- **Membership Tiers**: Andante, Moderato, Allegretto with different quotas
- **Dual Limits**: Weekly request quota + 5-hour rate limit
- **Multiple Auth Methods**: Environment variable or Chrome cookie
- **Tier Detection**: Automatically detects membership level from quota

---

## Data Source

### Primary: Kimi Coding API

**Endpoint:** `POST https://www.kimi.com/apiv2/kimi.gateway.billing.v1.BillingService/GetUsages`

**Authentication Priority:**
1. `KIMI_AUTH_TOKEN` environment variable
2. Chrome cookie `kimi-auth` (cross-platform)

**Cookie Extraction:**
- **macOS:** `~/Library/Application Support/Google/Chrome/Default/Cookies`
- **Linux:** `~/.config/google-chrome/Default/Cookies`
- **Windows:** `%LOCALAPPDATA%/Google/Chrome/User Data/Default/Cookies`

**Response Format:**
```json
{
  "usages": [{
    "scope": "FEATURE_CODING",
    "detail": {
      "limit": "2048",
      "used": "214",
      "remaining": "1834",
      "resetTime": "2026-01-09T15:23:13.716839300Z"
    },
    "limits": [{
      "window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
      "detail": {
        "limit": "200",
        "used": "139",
        "remaining": "61",
        "resetTime": "2026-01-06T13:33:02.717479433Z"
      }
    }]
  }]
}
```

---

## Membership Tiers

| Tier | Price | Weekly Quota | Best For |
|------|-------|--------------|----------|
| **Andante** | ¥49/month | 1,024 requests | Light usage |
| **Moderato** | ¥99/month | 2,048 requests | Regular coding |
| **Allegretto** | ¥199/month | 7,168 requests | Heavy usage |

**All tiers include:**
- 200 requests per 5-hour rate limit window
- Same model access (Kimi K2.5)
- Same 2M token context window

---

## Collection Flow

```mermaid
graph TD
    A[Start] --> B{KIMI_AUTH_TOKEN set?}
    B -->|Yes| D[Use env var token]
    B -->|No| C[Extract Chrome cookie]
    C -->|Found| D
    C -->|Not found| E[Return Error: No Auth]
    
    D --> F[POST to Kimi API]
    F --> G{Success?}
    G -->|Yes| H[Parse Response]
    G -->|401| I[Return Error: Unauthorized]
    G -->|Other| J[Return Error: HTTP {code}]
    
    H --> K[Extract Weekly Quota]
    H --> L[Extract Rate Limit]
    
    K --> M[Create Weekly Card]
    L --> N[Create Rate Limit Card]
    
    M --> O[Return 2 Cards]
    N --> O
    E --> P[Return Error Card]
    I --> P
    J --> P
```

---

## Output Format

### Weekly Quota Card

```python
{
    "service": "Kimi Coding (Weekly)",
    "icon": "🌙",
    "remaining": "1834",         # remaining requests
    "unit": "2048 req",          # total weekly quota
    "reset": "Weekly",           # or specific date
    "health": "good",            # based on % used
    "pace": "Moderato",          # detected tier
    "detail": "214 used · Moderato"
}
```

### Rate Limit Card (5h Window)

```python
{
    "service": "Kimi Coding (5h)",
    "icon": "⏱️",
    "remaining": "61",           # remaining in window
    "unit": "200 req",           # window limit
    "reset": "5h window",        # when window resets
    "health": "good",            # based on % used
    "pace": "Stable",
    "detail": "139 used · Rate limit"
}
```

### Error Card (No Auth)

```python
{
    "service": "Kimi Coding",
    "icon": "🌙",
    "remaining": "ERR",
    "unit": "Check State",
    "reset": "—",
    "health": "critical",
    "pace": "Stopped",
    "detail": "No Auth (set KIMI_AUTH_TOKEN or login in Chrome)"
}
```

---

## Health Calculation

### Weekly Quota
```python
if pct_used < 50:
    health = "good"      # Green
elif pct_used < 80:
    health = "warning"   # Yellow
else:
    health = "critical"  # Red
```

### Rate Limit (5h)
```python
if pct_used < 70:
    health = "good"      # Green
else:
    health = "warning"   # Yellow
```

---

## Configuration

### Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `KIMI_AUTH_TOKEN` | Optional* | JWT auth token | `eyJhbG...`** |

*Either env var OR Chrome cookie required

**Get from browser:**
1. Login to https://www.kimi.com/code
2. Open DevTools (F12)
3. Application → Cookies → kimi.com
4. Copy `kimi-auth` value

### Cookie Extraction

If `KIMI_AUTH_TOKEN` is not set, the collector will try to extract it from Chrome cookies. Requires:
- Chrome installed and logged into kimi.com
- Appropriate permissions to read cookie database

---

## Getting Auth Token

### Method 1: Environment Variable (Recommended for Servers)

1. Login to https://www.kimi.com/code in Chrome
2. Open DevTools → Application → Cookies
3. Find `kimi-auth` cookie
4. Copy value
5. Set environment variable:
   ```bash
   export KIMI_AUTH_TOKEN="eyJhbG..."
   ```

### Method 2: Chrome Cookie (Automatic)

Just login to https://www.kimi.com/code in Chrome. The collector will automatically extract the token.

---

## Comparison: Kimi API vs Kimi Coding

| Aspect | Kimi API (Balance) | Kimi Coding (IDE) |
|--------|-------------------|-------------------|
| **Service** | Moonshot API | Kimi For Coding IDE |
| **Endpoint** | `api.moonshot.cn` | `kimi.com` |
| **Auth** | API Key (`KIMI_API_KEY`) | JWT Token (`KIMI_AUTH_TOKEN`) |
| **Returns** | Prepaid balance ($) | Weekly + rate limits |
| **Model** | Pay-as-you-go | Subscription tiers |
| **Best for** | API integration | IDE coding assistant |

---

## Deployment Modes

### Standalone
Set `KIMI_AUTH_TOKEN` env var or login to Chrome.

### Multi-Host
Run sidecar with `KIMI_AUTH_TOKEN` set on each machine.

### Docker
Set `KIMI_AUTH_TOKEN` as environment variable (cookie extraction won't work in containers without Chrome).

---

## Troubleshooting

### Issue: "No Auth" error

**Cause:** Neither env var nor Chrome cookie found

**Fix:**
```bash
# Option 1: Set env var
export KIMI_AUTH_TOKEN="your-jwt-token"

# Option 2: Login in Chrome
# Open https://www.kimi.com/code and login
```

### Issue: "Unauthorized" error

**Cause:** Token expired

**Fix:** Get fresh token from Chrome cookies or re-login

### Issue: No Chrome cookie found

**Cause:** Not logged in, or using different browser

**Check:**
```bash
# List Chrome cookies (macOS)
sqlite3 ~/Library/Application\ Support/Google/Chrome/Default/Cookies \
  "SELECT name FROM cookies WHERE host_key LIKE '%kimi.com%'"
```

---

## Related Files

| File | Purpose |
|------|---------|
| `app/services/collectors/kimi_coding.py` | Main collector implementation |
| `app/services/collectors/kimi_api.py` | API balance collector (complementary) |
| `app/core/chrome_cookies.py` | Cookie extraction (`get_kimi_auth_cookie()`) |
| `app/core/config.py` | Configuration (`KIMI_AUTH_TOKEN`) |
| `tests/unit/test_collectors.py` | Unit tests (TestKimiCodingCollector) |

---

## References

- **Kimi For Coding:** https://www.kimi.com/code
- **Kimi Documentation:** https://platform.moonshot.cn/docs/

---

*Last updated: 2026-04-07*

## Troubleshooting

### Issue: "No Auth" error
**Cause:** No token or cookie found
**Fix:**
1. Set `KIMI_AUTH_TOKEN` env var (get from browser cookie)
2. Or login to https://www.kimi.com/code in Chrome
3. Ensure Chrome cookies accessible

### Issue: "401 Unauthorized"
**Cause:** Token expired
**Fix:**
1. Re-login to https://www.kimi.com/code
2. Extract fresh `kimi-auth` cookie
3. Update `KIMI_AUTH_TOKEN` env var

### Issue: Wrong tier detected
**Cause:** Quota limit doesn't match known tiers
**Fix:**
- Tier auto-detected from weekly limit
- Custom plans may show as "Basic"
- Check actual quota at https://www.kimi.com/code/console

### Issue: No Chrome cookie found
**Cause:** Not logged in or different browser
**Fix:**
1. Verify login at https://www.kimi.com/code
2. Check cookie name: `kimi-auth`
3. Try setting `KIMI_AUTH_TOKEN` manually

