# -*- coding: utf-8 -*-
"""增强版 RC 监控：401 时静默重试并提示，状态变化或 ready 时输出。"""
import sys, time, json, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
URL = "https://developer.amd.com.cn/radeon/api/notebook/status"
last = None
while True:
    try:
        cookies = open("rc_cookies.txt", encoding="utf-8").read().strip()
        req = urllib.request.Request(URL, headers={"Accept": "application/json", "Cookie": cookies})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        status = data.get("status")
        ready = data.get("ready")
        url = data.get("url")
        sig = (status, ready, bool(url))
        if sig != last:
            print(json.dumps({"t": time.strftime("%H:%M:%S"), "status": status,
                              "phase": data.get("phase"), "ready": ready, "url": url,
                              "message": (data.get("message") or "")[:200]},
                             ensure_ascii=False), flush=True)
            last = sig
        if ready or url or status == "failed":
            print("=== TERMINAL STATE ===", flush=True)
            break
    except urllib.error.HTTPError as e:
        if e.code == 401:
            if last != ("LOGIN_NEEDED", False, False):
                print(json.dumps({"t": time.strftime("%H:%M:%S"), "info": "会话过期，需要重新登录 Radeon Cloud (aliyun 验证码需人工)。登录后刷新 rc_cookies.txt 即自动恢复监控。"}, ensure_ascii=False), flush=True)
                last = ("LOGIN_NEEDED", False, False)
        else:
            print(json.dumps({"t": time.strftime("%H:%M:%S"), "error": str(e)[:150]}, ensure_ascii=False), flush=True)
    except Exception as e:
        print(json.dumps({"t": time.strftime("%H:%M:%S"), "error": str(e)[:150]}, ensure_ascii=False), flush=True)
    time.sleep(45)
