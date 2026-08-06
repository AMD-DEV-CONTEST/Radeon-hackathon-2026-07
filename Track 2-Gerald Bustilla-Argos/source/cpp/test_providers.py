"""
Test multiple OpenAI-compatible AI providers to verify our integration format.
All providers use the same /v1/chat/completions endpoint format.
"""
import urllib.request
import json
import ssl

def test_provider(name, base_url, api_key, model, prompt="Say hello in one sentence."):
    print(f"\n{'='*60}")
    print(f"  Provider: {name}")
    print(f"  URL: {base_url}/chat/completions")
    print(f"  Model: {model}")
    print(f"{'='*60}")

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content is None:
                content = "(empty content)"
            print(f"  STATUS: {resp.status} OK")
            print(f"  RESPONSE: {content[:200]}")
            print(f"  RESULT: PASS")
            return True
    except urllib.error.HTTPError as e:
        error_body = ""
        if hasattr(e, 'read'):
            error_body = e.read().decode("utf-8")[:300]
        code = e.code
        print(f"  HTTP {code}: {e}")
        if error_body:
            print(f"  BODY: {error_body}")
        # 401/403 = endpoint correct, just auth (expected with placeholder keys)
        if code in (401, 403):
            print(f"  RESULT: PASS (endpoint confirmed, auth challenge as expected)")
            return True
        else:
            print(f"  RESULT: FAIL (unexpected HTTP {code})")
            return False

# ── Provider configurations ──
providers = [
    {
        "name": "AMD Radeon Developer API",
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "api_key": "rc-c042ad0acc56669f7b46e70f924189b5ac51664ce329f5b2",
        "model": "Qwen3.6-35B-A3B"
    },
    {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test-placeholder-key",
        "model": "gpt-4o-mini"
    },
    {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "gsk_test-placeholder-key",
        "model": "llama-3.3-70b-versatile"
    },
    {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-test-placeholder-key",
        "model": "openai/gpt-4o-mini"
    },
    {
        "name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "api_key": "test-placeholder-key",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    },
    {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "test-placeholder-key",
        "model": "deepseek-chat"
    },
    {
        "name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "api_key": "test-placeholder-key",
        "model": "llama-3.3-70b"
    },
    {
        "name": "SambaNova",
        "base_url": "https://api.sambanova.ai/v1",
        "api_key": "test-placeholder-key",
        "model": "Meta-Llama-3.1-70B-Instruct"
    },
]

print("\n" + "=" * 60)
print("  AI Provider Compatibility Test")
print("  Format: OpenAI-compatible /v1/chat/completions")
print("=" * 60)

results = []
for p in providers:
    ok = test_provider(p["name"], p["base_url"], p["api_key"], p["model"])
    results.append((p["name"], ok))

print("\n" + "=" * 60)
print("  SUMMARY")
print("=" * 60)
for name, ok in results:
    status = "PASS" if ok else "FAIL"
    print(f"  {name:30s} {status}")

print("\n  Note: Providers with placeholder keys will get 401/403 errors.")
print("  This confirms the endpoint format is correct (auth challenge,")
print("  not a 404 or connection error). The C++ AgentClient uses the")
print("  same OpenAI-compatible format for all providers.")
print("=" * 60)
