"""
Quick re-test: find correct model IDs for AMD Fireworks models + Fireworks AI provider.
"""
import urllib.request, urllib.error, json, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

AMD_KEY = "rc-c042ad0acc56669f7b46e70f924189b5ac51664ce329f5b2"
AMD_URL = "https://developer.amd.com.cn/radeon/api/v1"

def test(name, base_url, api_key, model):
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = json.dumps({"model": model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 50}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content is None: content = "(empty)"
            return f"200 OK — {content[:80]}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")[:200] if hasattr(e, 'read') else ""
        return f"HTTP {e.code} — {body}"
    except Exception as e:
        return f"ERR — {e}"

# Try listing AMD models
print("=== AMD Model List ===")
try:
    req = urllib.request.Request(
        AMD_URL + "/models",
        headers={"Authorization": f"Bearer {AMD_KEY}"},
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        models = body.get("data", [])
        for m in models:
            print(f"  {m.get('id', '?')}")
except Exception as e:
    print(f"  Could not list models: {e}")

# Try various model ID formats for AMD Fireworks models
print("\n=== AMD Fireworks Model ID Tests ===")
candidates = [
    "deepseek-v4-pro",
    "DeepSeek-V4-Pro",
    "deepseek-ai/DeepSeek-V4-Pro",
    "radeon-deepseek/DeepSeek-V4-Pro",
    "glm-5.2",
    "GLM-5.2",
    "zai/GLM-5.2",
    "kimi-k3",
    "Kimi-K3",
    "moonshot/Kimi-K3",
    "kimi-k2.6",
    "Kimi-K2.6",
    "moonshot/Kimi-K2.6",
    "gpt-oss-120b",
    "openai/gpt-oss-120b",
]
for model_id in candidates:
    result = test("AMD", AMD_URL, AMD_KEY, model_id)
    tag = "OK" if "200" in result else "  "
    print(f"  [{tag}] {model_id:40s} {result[:80]}")

# Fix Fireworks AI provider model name
print("\n=== Fireworks AI Provider Test ===")
fw_models = [
    "accounts/fireworks/models/llama-v3p3-70b-instruct",
    "accounts/fireworks/models/llama3.3-70b-instruct",
    "accounts/fireworks/models/deepseek-v3",
    "accounts/fireworks/models/qwen2p5-72b-instruct",
]
for model_id in fw_models:
    result = test("Fireworks", "https://api.fireworks.ai/inference/v1", "test-key", model_id)
    tag = "OK" if "401" in result or "403" in result else "  "
    print(f"  [{tag}] {model_id:55s} {result[:60]}")
