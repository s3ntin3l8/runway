import requests
import json

# Configuration
API_URL = "http://localhost:8765/api/ingest"
API_KEY = "sidecar-default-secret"

# Mock data
data = {
    "provider": "anthropic",
    "api_key": API_KEY,
    "metrics": [
        {
            "service": "Claude (External)",
            "icon": "🟠",
            "remaining": "12,500",
            "unit": "tokens",
            "reset": "1h 45m",
            "health": "good",
            "pace": "Stable",
            "detail": "Pushed via sidecar"
        }
    ]
}

def test_ingest():
    print(f"Sending data to {API_URL}...")
    try:
        response = requests.post(API_URL, json=data)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        # Verify it shows up in /limits
        print("\nVerifying in /api/limits...")
        limits_res = requests.get("http://localhost:8765/api/limits")
        limits = limits_res.json()["limits"]
        found = any("Claude (External)" in l["service"] for l in limits)
        if found:
            print("SUCCESS: Data found in limits response!")
        else:
            print("FAILURE: Data NOT found in limits response.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_ingest()
