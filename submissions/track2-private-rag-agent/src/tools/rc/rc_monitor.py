# -*- coding: utf-8 -*-
"""后台监控 Radeon Cloud 实例状态，状态变化时输出。用法: python rc_monitor.py [interval_s]"""
import sys, time, json, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

URL = "https://developer.amd.com.cn/radeon/api/notebook/status"
INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 30

last_status = None
last_phase = None

while True:
    try:
        cookies = open("rc_cookies.txt", encoding="utf-8").read().strip()
        req = urllib.request.Request(URL, headers={"Accept": "application/json", "Cookie": cookies})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        status = data.get("status")
        phase = data.get("phase")
        ready = data.get("ready")
        url = data.get("url")
        if (status != last_status) or (phase != last_phase) or ready or url:
            print(json.dumps({
                "t": time.strftime("%H:%M:%S"),
                "status": status,
                "phase": phase,
                "ready": ready,
                "url": url,
                "api_base_url": data.get("api_base_url"),
                "api_key": data.get("api_key"),
                "message": (data.get("message") or "")[:200],
            }, ensure_ascii=False), flush=True)
            last_status, last_phase = status, phase
        if ready or url or status == "failed":
            print("=== TERMINAL STATE REACHED ===", flush=True)
            break
    except Exception as e:
        print(json.dumps({"t": time.strftime("%H:%M:%S"), "error": str(e)[:150]}, ensure_ascii=False), flush=True)
    time.sleep(INTERVAL)
