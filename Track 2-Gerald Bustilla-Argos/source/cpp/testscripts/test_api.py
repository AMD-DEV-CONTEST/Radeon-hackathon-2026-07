import urllib.request
import json

url = "https://developer.amd.com.cn/radeon/api/v1/chat/completions"
headers = {
    "Authorization": "Bearer rc-c042ad0acc56669f7b46e70f924189b5ac51664ce329f5b2",
    "Content-Type": "application/json"
}
data = json.dumps({
    "model": "Qwen3.6-35B-A3B",
    "messages": [{"role": "user", "content": "Hello, say hi in one sentence."}]
}).encode("utf-8")

req = urllib.request.Request(url, data=data, headers=headers, method="POST")
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        print("STATUS:", resp.status)
        print("RESPONSE:", body)
except Exception as e:
    print("ERROR:", e)
    if hasattr(e, 'read'):
        print("BODY:", e.read().decode("utf-8"))
