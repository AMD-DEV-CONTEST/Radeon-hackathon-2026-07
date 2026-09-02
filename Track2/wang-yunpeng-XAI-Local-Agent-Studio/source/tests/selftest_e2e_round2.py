#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XAI 统一操作台 — 端到端自测 第二轮（命令全量 + 边界 + 并发）

覆盖第一轮未覆盖的命令与边界：
  /task /scan /channels /mcp /models /skill /automate /clear
  空输入(400) / 未知命令 / 错误审批ID / 长文本 / 并发请求
"""

import json
import sys
import time
import threading
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
RESULTS = []


def log(name, passed, detail=""):
    RESULTS.append((name, passed, detail))
    print(f"[{'✅ PASS' if passed else '❌ FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    sys.stdout.flush()


def post_chat(text, session="default", timeout=90):
    payload = json.dumps({"text": text, "session": session}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    events, full = [], ""
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").rstrip("\n")
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                continue
            try:
                ev = json.loads(data)
            except json.JSONDecodeError:
                continue
            events.append(ev)
            if ev.get("type") == "token":
                full += ev.get("text", "")
            elif ev.get("type") == "answer":
                full += ev.get("answer", "")
    return events, full


def event_types(events):
    return [e.get("type") for e in events]


def post_chat_status(text, session="default"):
    """返回 HTTP 状态码（用于测试 400 等边界）。"""
    payload = json.dumps({"text": text, "session": session}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


# ---------------------------------------------------------------------------
def test_task():
    ev, txt = post_chat("/task 用一句话总结什么是 Agent", session="r2_task")
    ok = "token" in event_types(ev) or "answer" in event_types(ev)
    log("命令 /task", ok, f"len={len(txt)}")
    return ok


def test_scan():
    ev, txt = post_chat("/scan server_xai.py", session="r2_scan")
    has_err = any(e.get("type") == "error" for e in ev)
    ok = (not has_err) and "answer" in event_types(ev)
    log("命令 /scan", ok, f"has_error={has_err} len={len(txt)}")
    return ok


def test_channels():
    ev, txt = post_chat("/channels", session="r2_ch")
    ok = "answer" in event_types(ev) and len(txt) > 0
    log("命令 /channels", ok, f"len={len(txt)}")
    return ok


def test_mcp():
    ev, txt = post_chat("/mcp", session="r2_mcp")
    ok = "answer" in event_types(ev) and len(txt) > 0
    log("命令 /mcp", ok, f"len={len(txt)}")
    return ok


def test_models():
    ev, txt = post_chat("/models", session="r2_models")
    ok = "answer" in event_types(ev) and "DEEPSEEK_API_KEY" not in txt  # 不应暴露真实 key 内容
    log("命令 /models（不泄露 key）", ok, f"len={len(txt)}")
    return ok


def test_skill_list():
    ev, txt = post_chat("/skill list", session="r2_skill")
    ok = "answer" in event_types(ev) and len(txt) > 0
    log("命令 /skill list", ok, f"len={len(txt)}")
    return ok


def test_automate_noarg():
    ev, txt = post_chat("/automate", session="r2_auto")
    ok = "answer" in event_types(ev)
    log("命令 /automate（无参）", ok, f"len={len(txt)}")
    return ok


def test_clear():
    # 先写一条，再清空
    post_chat("/remember 清空测试标记", session="r2_clear")
    ev, txt = post_chat("/clear", session="r2_clear")
    ok = "answer" in event_types(ev) and "已清空" in txt
    # 验证 history 已空
    try:
        with urllib.request.urlopen(BASE + "/api/session/r2_clear", timeout=10) as r:
            d = json.loads(r.read())
            empty = len(d.get("messages", [])) == 0
    except Exception:
        empty = False
    log("命令 /clear", ok and empty, f"cleared_ok={ok} history_empty={empty}")
    return ok and empty


def test_unknown_cmd():
    ev, txt = post_chat("/foobar xyz", session="r2_unk")
    ok = "answer" in event_types(ev) and ("未知命令" in txt or "帮助" in txt)
    log("未知命令处理", ok, f"txt={txt[:30]}")
    return ok


def test_bad_approve():
    ev, txt = post_chat("/approve NONEXIST", session="r2_bad")
    ok = "answer" in event_types(ev) and "不存在" in txt
    log("错误审批ID处理", ok, f"txt={txt[:30]}")
    return ok


def test_empty_input():
    st = post_chat_status("")
    ok = st == 400
    log("空输入返回 400", ok, f"status={st}")
    return ok


def test_long_input():
    long_text = "请分析一下" + "量化投资的风险管理，" * 50
    ev, txt = post_chat(long_text, session="r2_long")
    ok = ("token" in event_types(ev) or "answer" in event_types(ev)) and len(txt) > 0
    log("超长输入", ok, f"len={len(txt)}")
    return ok


def test_concurrency():
    """并发 4 个请求，验证线程安全（无崩溃 / 无串台）。"""
    results = {}
    def worker(i):
        try:
            ev, txt = post_chat(f"用一句话说第{i}点关于AI", session=f"r2_conc_{i}")
            results[i] = ("token" in event_types(ev) or "answer" in event_types(ev)) and len(txt) > 0
        except Exception as e:
            results[i] = False
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    ok = all(results.values())
    log("并发 4 请求", ok, f"results={results}")
    return ok


def main():
    print("=" * 60)
    print("XAI 统一操作台 — 端到端自测 第二轮")
    print("=" * 60)
    time.sleep(0.3)
    test_task()
    test_scan()
    test_channels()
    test_mcp()
    test_models()
    test_skill_list()
    test_automate_noarg()
    test_clear()
    test_unknown_cmd()
    test_bad_approve()
    test_empty_input()
    test_long_input()
    test_concurrency()
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"总计: {passed}/{total} 通过")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
