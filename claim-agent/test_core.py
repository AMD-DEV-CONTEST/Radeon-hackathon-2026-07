import requests, json, base64, sys
import config as cfg

# Test 1: model connectivity
print("=== Test 1: Model connectivity ===")
print(f"endpoint: {cfg.MODEL_URL}  model: {cfg.MODEL_ID}")
try:
    r = requests.post(cfg.MODEL_URL,
        json={"model": cfg.MODEL_ID, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10},
        timeout=30)
    print(f"Model status: {r.status_code}, response: {r.text[:200]}")
except Exception as e:
    print(f"Model error: {e}")

print()

# Test 2: verify API
print("=== Test 2: Verify API ===")
try:
    params = {"fpdm": "", "fphm": "26442000007766995501", "date": "20260708", "code": "777.35", "channel": cfg.VERIFY_CHANNEL}
    r = requests.get(cfg.VERIFY_URL, params=params, timeout=cfg.VERIFY_TIMEOUT, verify=False)
    text = r.content.decode("gbk", errors="replace")
    data = json.loads(text)
    print(f"Verify status: {r.status_code}, code: {data.get('code')}, msg: {data.get('message')}")
except Exception as e:
    print(f"Verify error: {e}")
    import traceback
    traceback.print_exc()

print()

# Test 3: model with image (streaming) - use the working Chinese prompt
print("=== Test 3: Model streaming with image ===")
try:
    with open("C:\\Users\\OKONE\\fake_ocr_test\\fapiao2.jpg", "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    prompt = "请仔细识别这张中国发票，提取以下字段（只返回JSON格式，不要多余文字）：\n{\n  \"fpdm\": \"发票代码（数电票留空）\",\n  \"fphm\": \"发票号码（20位）\",\n  \"date\": \"开票日期（yyyyMMdd格式）\",\n  \"code\": \"价税合计金额（数字，如136.00）\"\n}"
    payload = {
        "model": cfg.MODEL_ID,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        ]}],
        "max_tokens": 500,
        "temperature": 0.1,
        "stream": True
    }
    resp = requests.post(cfg.MODEL_URL, json=payload, stream=True, timeout=180)
    collected = ""
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data: "):
            d = line[6:].strip()
            if d == "[DONE]":
                break
            try:
                chunk = json.loads(d)
                c = chunk["choices"][0].get("delta", {}).get("content", "")
                if c:
                    collected += c
                    print(c, end="", flush=True)
            except json.JSONDecodeError:
                continue
    print()
    print(f"\nFull result: {collected}")
except Exception as e:
    print(f"Error: {e}")

print()
print("=== All tests done ===")
