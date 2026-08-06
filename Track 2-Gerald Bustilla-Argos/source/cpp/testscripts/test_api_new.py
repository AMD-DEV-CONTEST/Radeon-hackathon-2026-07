import urllib.request
import json
import sys

API_URL = "https://developer.amd.com.cn/radeon/spaces/u-4408-1fb1befd/8000/v1/chat/completions"
API_KEY = "rc-c042ad0acc56669f7b46e70f924189b5ac51664ce329f5b2"
MODEL = "minicpm-v"

body = json.dumps({
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "You are Argos, a faithful AI companion. Reply briefly."},
        {"role": "user", "content": "Say hello and tell me what tools you have."}
    ]
}).encode("utf-8")

req = urllib.request.Request(API_URL, data=body, method="POST")
req.add_header("Authorization", f"Bearer {API_KEY}")
req.add_header("Content-Type", "application/json")

print(f"Testing API: {API_URL}")
print(f"Model: {MODEL}")
print(f"Sending request...")

try:
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read().decode("utf-8"))
    print(f"\nStatus: {resp.status}")
    print(f"Response:\n{json.dumps(data, indent=2)}")
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(f"\nAI says: {content}")
    print("\nAPI TEST: SUCCESS")
except urllib.error.HTTPError as e:
    print(f"\nHTTP Error: {e.code}")
    print(f"Response: {e.read().decode('utf-8')}")
    print("\nAPI TEST: FAILED (HTTP error)")
except Exception as e:
    print(f"\nError: {e}")
    print("\nAPI TEST: FAILED (connection error)")
    sys.exit(1)
