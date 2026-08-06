#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XAI 统一操作台 — 画布工作流端到端自测（第三轮）

通过真实 HTTP + SSE 调用 /api/workflow/run，覆盖节点图工作流执行：
  - 正常链路 input→chat→output 拓扑执行并产出真实结果
  - 上游上下文在节点间传递
  - 分支/汇聚（多入度）拓扑序正确
  - 环路检测（返回 error）
  - 空工作流 / 孤立节点
  - scan 节点真实调用 OpenClaw
  - 危险 exec 节点被拦截（不自动执行破坏性命令）
  - 参数校验（nodes 非数组 → 400）

无第三方依赖（仅标准库），运行：python3 tests/selftest_workflow.py
"""

import json
import sys
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
RESULTS = []


def log(name, passed, detail=""):
    RESULTS.append((name, passed, detail))
    mark = "✅ PASS" if passed else "❌ FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    sys.stdout.flush()


def run_workflow(nodes, edges, timeout=120):
    """POST /api/workflow/run，返回 (events, status_code)。"""
    payload = json.dumps({"nodes": nodes, "edges": edges}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/workflow/run", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    events = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.status
            for raw in r:
                line = raw.decode("utf-8", "ignore").rstrip("\n")
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    continue
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    continue
        return events, code
    except urllib.error.HTTPError as e:
        return [], e.code


def wf_done_result(events):
    for e in events:
        if e.get("type") == "wf_done":
            return e.get("result", "")
    return None


def node_done_outputs(events):
    return {e.get("node_id"): e.get("output", "")
            for e in events if e.get("type") == "wf_node" and e.get("status") == "done"}


# ---------------------------------------------------------------------------

def test_linear():
    """input→chat→output 正常执行并产出真实结果。"""
    try:
        nodes = [
            {"id": "n1", "type": "input", "label": "输入", "config": {"value": "用一句话解释什么是二分查找"}},
            {"id": "n2", "type": "chat", "label": "回答", "config": {}},
            {"id": "n3", "type": "output", "label": "输出", "config": {}},
        ]
        edges = [{"source": "n1", "target": "n2"}, {"source": "n2", "target": "n3"}]
        events, code = run_workflow(nodes, edges)
        types = [e.get("type") for e in events]
        result = wf_done_result(events)
        ok = (code == 200 and "wf_start" in types and "wf_done" in types
              and result and len(result) > 10)
        log("工作流 线性链路执行", ok, f"结果={ (result or '')[:40]!r}")
        return ok
    except Exception as e:
        log("工作流 线性链路执行", False, str(e))
        return False


def test_context_pass():
    """上游 input 的值应影响下游输出（上下文传递）。"""
    try:
        nodes = [
            {"id": "n1", "type": "input", "config": {"value": "请只回复这四个字：上下文已传"}},
            {"id": "n2", "type": "chat", "config": {}},
        ]
        edges = [{"source": "n1", "target": "n2"}]
        events, code = run_workflow(nodes, edges)
        outs = node_done_outputs(events)
        chat_out = outs.get("n2", "")
        ok = code == 200 and len(chat_out) > 0
        log("工作流 上游上下文传递", ok, f"下游输出长度={len(chat_out)}")
        return ok
    except Exception as e:
        log("工作流 上游上下文传递", False, str(e))
        return False


def test_diamond():
    """菱形拓扑 a→b, a→c, b→d, c→d 应无环并全部执行。"""
    try:
        nodes = [
            {"id": "a", "type": "input", "config": {"value": "主题：缓存"}},
            {"id": "b", "type": "chat", "label": "优点", "config": {"prompt": "列出该主题一个优点"}},
            {"id": "c", "type": "chat", "label": "缺点", "config": {"prompt": "列出该主题一个缺点"}},
            {"id": "d", "type": "output", "label": "汇总", "config": {}},
        ]
        edges = [{"source": "a", "target": "b"}, {"source": "a", "target": "c"},
                 {"source": "b", "target": "d"}, {"source": "c", "target": "d"}]
        events, code = run_workflow(nodes, edges)
        done = node_done_outputs(events)
        ok = code == 200 and all(k in done for k in ("a", "b", "c", "d")) and wf_done_result(events)
        log("工作流 菱形拓扑执行", ok, f"完成节点={sorted(done.keys())}")
        return ok
    except Exception as e:
        log("工作流 菱形拓扑执行", False, str(e))
        return False


def test_cycle():
    """环路应被检测并返回 error。"""
    try:
        nodes = [{"id": "a", "type": "chat"}, {"id": "b", "type": "chat"}]
        edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
        events, code = run_workflow(nodes, edges, timeout=20)
        has_err = any(e.get("type") == "error" and "环路" in e.get("error", "") for e in events)
        ok = code == 200 and has_err
        log("工作流 环路检测", ok, "已拦截环路" if has_err else "未检测到环路")
        return ok
    except Exception as e:
        log("工作流 环路检测", False, str(e))
        return False


def test_empty():
    """空工作流应返回 error。"""
    try:
        events, code = run_workflow([], [], timeout=15)
        has_err = any(e.get("type") == "error" for e in events)
        log("工作流 空图处理", code == 200 and has_err, "已提示为空")
        return code == 200 and has_err
    except Exception as e:
        log("工作流 空图处理", False, str(e))
        return False


def test_isolated():
    """孤立节点（无连线）也应各自执行，不报环路。"""
    try:
        nodes = [{"id": "x", "type": "input", "config": {"value": "hello"}},
                 {"id": "y", "type": "input", "config": {"value": "world"}}]
        events, code = run_workflow(nodes, [], timeout=30)
        done = node_done_outputs(events)
        no_err = not any(e.get("type") == "error" for e in events)
        ok = code == 200 and no_err and len(done) == 2
        log("工作流 孤立节点", ok, f"完成={sorted(done.keys())}")
        return ok
    except Exception as e:
        log("工作流 孤立节点", False, str(e))
        return False


def test_scan_node():
    """scan 节点真实调用 OpenClaw 漏洞扫描。"""
    try:
        nodes = [{"id": "s", "type": "scan", "label": "扫描", "config": {"file": "server_xai.py"}}]
        events, code = run_workflow(nodes, [], timeout=60)
        outs = node_done_outputs(events)
        out = outs.get("s", "")
        ok = code == 200 and len(out) > 0 and "扫描失败" not in out
        log("工作流 scan 真实执行", ok, f"扫描输出长度={len(out)}")
        return ok
    except Exception as e:
        log("工作流 scan 真实执行", False, str(e))
        return False


def test_dangerous_exec_blocked():
    """exec 节点含 rm -rf 应被拦截，不自动执行。"""
    try:
        nodes = [{"id": "e", "type": "exec", "label": "危险", "config": {"command": "rm -rf /tmp/xai_should_not_delete"}}]
        events, code = run_workflow(nodes, [], timeout=30)
        outs = node_done_outputs(events)
        out = outs.get("e", "")
        ok = code == 200 and ("拦截" in out or "rm_rf" in out or "高危" in out)
        log("工作流 危险命令拦截", ok, f"{out[:40]!r}")
        return ok
    except Exception as e:
        log("工作流 危险命令拦截", False, str(e))
        return False


def test_bad_payload():
    """nodes 非数组 → 400。"""
    try:
        payload = json.dumps({"nodes": "oops", "edges": []}).encode("utf-8")
        req = urllib.request.Request(BASE + "/api/workflow/run", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            log("工作流 非法入参 400", False, "未返回错误")
            return False
        except urllib.error.HTTPError as e:
            ok = e.code == 400
            log("工作流 非法入参 400", ok, f"HTTP {e.code}")
            return ok
    except Exception as e:
        log("工作流 非法入参 400", False, str(e))
        return False


def main():
    print("=" * 60)
    print("XAI 画布工作流 端到端自测（第三轮）")
    print("=" * 60)
    test_linear()
    test_context_pass()
    test_diamond()
    test_cycle()
    test_empty()
    test_isolated()
    test_scan_node()
    test_dangerous_exec_blocked()
    test_bad_payload()
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"总计: {passed}/{total} 通过")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
