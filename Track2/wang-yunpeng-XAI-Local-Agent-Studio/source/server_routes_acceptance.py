"""XAI 验收调试台聚合面（界面驱动黑盒调试员模式）。

设计纪律（对应方法论 v3.1「运行时自测量」章节）：
- 本接口只『测量』，绝不『修改』内核 / 记忆 / Guardian。
- GET  /api/acceptance        → 实时六维快照（轻量 live 信号 + 最近一次探针结论）。
- GET  /api/acceptance/history → 验收账本历史（acceptance_ledger.jsonl 反序切片）。
- POST /api/acceptance/run    → 触发外部黑盒探针套件（honesty/smoke/security --json），
                                 计算六维评分，追加账本（只读子进程 + 限频 + 超时封顶）。

探针全部以只读子进程执行既有 CLI 脚本，结果落本地账本，不触碰任何系统状态。
修复动作必须经 Guardian/ACR 治理闸门，绝不由本接口执行（防止『自己改卷子自己打分』）。
"""
from __future__ import annotations

import json
import os
import time
import subprocess
import threading
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(ROOT, "acceptance_ledger.jsonl")
PY = "/Users/Admin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

# Token：与 CLI 探针一致，优先读文件，回退环境变量；不硬编码字面量（避免 SAST 误报 + 泄露风险）
try:
    TOKEN = open(os.path.expanduser("~/.xai/.server_token")).read().strip()
except Exception:
    TOKEN = os.environ.get("XAI_TOKEN", "")

# 限频 + 超时封顶（防误用拖垮服务）
_MIN_INTERVAL = 60          # 两次跑批最小间隔（秒）
_RUN_TIMEOUT = 150          # 单个探针子进程超时（秒）
_RUN_LOCK = threading.Lock()
_LAST_RUN = {"ts": 0}

# 六维定义
DIM_CN = {
    "functional": "功能",
    "performance": "性能",
    "security": "安全",
    "data": "数据",
    "ops": "运维",
    "honesty": "诚实·价值·治理",
}

if not os.path.exists(LEDGER):
    try:
        open(LEDGER, "a").close()
    except Exception:
        pass


# ── 内部工具 ───────────────────────────────────────────────
def _self_get(path: str):
    """驱动本机 operator 接口（黑盒，与前端同源）。线程安全（服务为 Threading）。"""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000" + path,
            headers={"X-Auth-Token": TOKEN, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read())
    except Exception as e:  # noqa
        return 0, {"error": str(e)}


def _run_probe(script: str) -> dict:
    """以只读子进程执行 CLI 探针，解析 --json 输出。"""
    try:
        r = subprocess.run(
            [PY, os.path.join(ROOT, "scripts", script), "--json"],
            cwd=ROOT, capture_output=True, text=True, timeout=_RUN_TIMEOUT,
        )
        out = (r.stdout or "").strip()
        if not out:
            return {"tool": script, "ok": False, "error": "no stdout",
                    "stderr": (r.stderr or "")[:300]}
        return json.loads(out)
    except subprocess.TimeoutExpired:
        return {"tool": script, "ok": False, "error": f"timeout>{_RUN_TIMEOUT}s"}
    except Exception as e:  # noqa
        return {"tool": None, "ok": False, "error": str(e)}


def _append_ledger(record: dict) -> None:
    try:
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_ledger(limit: int = 20) -> list:
    try:
        with open(LEDGER, "r", encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        return [json.loads(l) for l in lines[-limit:]]
    except Exception:
        return []


def _dim(key: str, status: str, score: int, source: str, detail: str) -> dict:
    return {"key": key, "cn": DIM_CN.get(key, key), "status": status,
            "score": int(score), "source": source, "detail": detail}


def _dim_from_security(sec: dict) -> dict | None:
    if not sec:
        return None
    s = sec.get("summary", {})
    ok = bool(sec.get("ok"))
    if ok:
        status, score = "pass", 100
    elif s.get("auth_pass", 0) < s.get("auth_total", 0):
        ap, at = s.get("auth_pass", 0), max(1, s.get("auth_total", 1))
        status, score = "fail", int(ap / at * 100)
    else:
        status, score = "warn", 70
    detail = (f"硬编码密钥={s.get('secrets', 0)}, 危险模式={s.get('dangers', 0)}, "
              f"鉴权 {s.get('auth_pass', 0)}/{s.get('auth_total', 0)}, "
              f"Guardian={s.get('guardian')}")
    return _dim("security", status, score, "probe", detail)


def _dim_from_honesty(hon: dict) -> dict | None:
    if not hon:
        return None
    s = hon.get("summary", {})
    ok = bool(hon.get("ok"))
    status = "pass" if ok else "fail"
    score = 100 if ok else int(s.get("pass", 0) / max(1, s.get("total", 1)) * 100)
    detail = f"诚实度检查 {s.get('pass', 0)}/{s.get('total', 0)} 通过"
    return _dim("honesty", status, score, "probe", detail)


def _compute_dims(live: dict, smoke_probe: dict | None,
                  sec_dim: dict | None, hon_dim: dict | None) -> list:
    health = live.get("health") or {}
    metrics = live.get("metrics") or {}
    kb = live.get("kb") or {}
    tracer = metrics.get("tracer") or {}
    healthy = bool(health.get("healthy") or health.get("xai_engine") == "running")

    # 功能：优先用冒烟探针；无探针则看 live 引擎健康
    if smoke_probe is not None:
        sm = smoke_probe.get("summary", {})
        total = sm.get("total", 0) or 0
        fail = sm.get("fail", 0) or 0
        ok = bool(smoke_probe.get("ok"))
        if ok:
            fstatus, fscore = "pass", 100
        elif fail <= 2:
            fstatus, fscore = "warn", max(0, int((1 - fail / total) * 100)) if total else 50
        else:
            fstatus, fscore = "fail", max(0, int((1 - fail / total) * 100)) if total else 0
        fdetail = f"引擎健康={healthy}; 冒烟 {total} 项, 失败 {fail}"
        fsource = "probe"
    elif healthy:
        fstatus, fscore, fdetail, fsource = "pass", 100, "引擎健康 (未跑批冒烟)", "live"
    else:
        fstatus, fscore, fdetail, fsource = "fail", 0, "引擎未运行", "live"

    # 性能：live tracer
    try:
        sr = float(tracer.get("success_rate"))
    except (TypeError, ValueError):
        sr = None
    try:
        p95 = float(tracer.get("p95_latency_ms"))
    except (TypeError, ValueError):
        p95 = None
    tracer_total = tracer.get("total", 0) or 0
    if tracer_total == 0:
        # 服务刚启动 / 尚无观测样本：不判失败，待流量积累后自然填充
        pstatus, pscore, pdetail = "unknown", 0, "暂无观测样本（服务刚启动或尚未产生请求）"
    elif sr is not None and sr >= 0.95 and (p95 is None or p95 <= 2000):
        pstatus, pscore = "pass", int(sr * 100)
    elif sr is not None and sr >= 0.8:
        pstatus, pscore = "warn", int(sr * 100)
    elif sr is not None:
        pstatus, pscore = "fail", int(sr * 100)
    else:
        pstatus, pscore = "unknown", 0
        pdetail = "无 tracer 数据"
    if tracer_total != 0:
        pdetail = f"成功率={sr}, p95={p95}ms (样本 {tracer_total})"

    # 安全 / 诚实：来自探针或上次跑批结论
    if sec_dim is not None:
        sstatus, sscore, sdetail, ssource = sec_dim["status"], sec_dim["score"], sec_dim["detail"], sec_dim["source"]
    else:
        sstatus, sscore, sdetail, ssource = "unknown", 0, "未跑批安全扫描", "ledger"
    if hon_dim is not None:
        hstatus, hscore, hdetail, hsource = hon_dim["status"], hon_dim["score"], hon_dim["detail"], hon_dim["source"]
    else:
        hstatus, hscore, hdetail, hsource = "unknown", 0, "未跑批诚实度检查", "ledger"

    # 数据：live KB
    kb_ok = bool(kb.get("ok"))
    stats = kb.get("stats") if isinstance(kb.get("stats"), dict) else {}
    dense = stats.get("dense_available")
    chunks = stats.get("total_chunks", 0)
    if kb_ok and dense:
        dstatus, dscore = "pass", 100
    elif kb_ok:
        dstatus, dscore = "warn", 60
    else:
        dstatus, dscore = "fail", 0
    ddetail = f"KB ok={kb_ok}, dense_available={dense}, chunks={chunks}"

    # 运维：live 健康 + 工作流错误
    wh = metrics.get("workflow_history") or {}
    err_count = wh.get("errors", 0) or 0
    wf_total = wh.get("total", 0) or 0
    if healthy and err_count == 0:
        ostatus, oscore = "pass", 100
    elif healthy:
        ostatus, oscore = "warn", 70
    else:
        ostatus, oscore = "fail", 0
    odetail = f"引擎健康={healthy}, 工作流错误 {err_count}/{wf_total}"

    return [
        _dim("functional", fstatus, fscore, fsource, fdetail),
        _dim("performance", pstatus, pscore, "live", pdetail),
        _dim("security", sstatus, sscore, ssource, sdetail),
        _dim("data", dstatus, dscore, "live", ddetail),
        _dim("ops", ostatus, oscore, "live", odetail),
        _dim("honesty", hstatus, hscore, hsource, hdetail),
    ]


def _overall(dims: list) -> dict:
    scores = [d["score"] for d in dims if d["status"] != "unknown"]
    avg = int(sum(scores) / len(scores)) if scores else 0
    if any(d["status"] == "fail" for d in dims):
        status = "fail"
    elif any(d["status"] == "warn" for d in dims):
        status = "warn"
    elif any(d["status"] == "unknown" for d in dims):
        status = "partial"
    else:
        status = "pass"
    return {"score": avg, "status": status}


# ── 处理器 ────────────────────────────────────────────────
def _handle_acceptance_get(h):
    """GET /api/acceptance → 实时六维快照（live + 上次跑批探针结论）。"""
    try:
        _, health = _self_get("/api/system/health")
        _, metrics = _self_get("/api/metrics")
        _, kb = _self_get("/api/knowledge/stats")
        last = _read_ledger(1)
        last = last[0] if last else None
        last_dims = {d["key"]: d for d in (last or {}).get("dims", [])}
        sec_dim = last_dims.get("security")
        hon_dim = last_dims.get("honesty")
        dims = _compute_dims({"health": health, "metrics": metrics, "kb": kb},
                              None, sec_dim, hon_dim)
        payload = {
            "ts": int(time.time()),
            "ts_human": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "live",
            "overall": _overall(dims),
            "dims": dims,
            "last_run": (last or {}).get("ts_human"),
            "note": "安全/诚实维度取自最近一次跑批探针；功能/性能/数据/运维为实时信号。",
        }
        h._json_response(200, payload)
    except Exception as e:  # noqa
        h._json_response(500, {"error": f"验收快照失败: {e}"})


def _handle_acceptance_history(h):
    """GET /api/acceptance/history → 账本历史（?limit=20）。"""
    try:
        limit = 20
        try:
            q = h.path.split("?", 1)[1] if "?" in h.path else ""
            for kv in q.split("&"):
                if kv.startswith("limit="):
                    limit = max(1, min(100, int(kv.split("=", 1)[1])))
        except Exception:
            pass
        h._json_response(200, {"count": limit, "runs": _read_ledger(limit)})
    except Exception as e:  # noqa
        h._json_response(500, {"error": f"读取账本失败: {e}"})


def _handle_acceptance_run(h):
    """POST /api/acceptance/run → 跑批黑盒探针，落地六维评分账本。"""
    try:
        now = time.time()
        if now - _LAST_RUN["ts"] < _MIN_INTERVAL:
            wait = int(_MIN_INTERVAL - (now - _LAST_RUN["ts"]))
            h._json_response(429, {"ok": False,
                                   "error": f"限频：距上次跑批不足 {_MIN_INTERVAL}s",
                                   "retry_after": wait})
            return
        if not _RUN_LOCK.acquire(blocking=False):
            h._json_response(429, {"ok": False, "error": "已有验收跑批进行中，请稍后再试"})
            return
        try:
            probes = {
                "honesty": _run_probe("honesty_check.py"),
                "smoke": _run_probe("smoke_test.py"),
                "security": _run_probe("security_scan.py"),
            }
            _, health = _self_get("/api/system/health")
            _, metrics = _self_get("/api/metrics")
            _, kb = _self_get("/api/knowledge/stats")
            sec_dim = _dim_from_security(probes.get("security"))
            hon_dim = _dim_from_honesty(probes.get("honesty"))
            dims = _compute_dims({"health": health, "metrics": metrics, "kb": kb},
                                 probes.get("smoke"), sec_dim, hon_dim)
            record = {
                "ts": int(time.time()),
                "ts_human": time.strftime("%Y-%m-%d %H:%M:%S"),
                "overall": _overall(dims),
                "dims": dims,
                "probes": {k: {"ok": v.get("ok"), "summary": v.get("summary")}
                           for k, v in probes.items()},
            }
            _append_ledger(record)
            h._json_response(200, record)
        finally:
            _RUN_LOCK.release()
            _LAST_RUN["ts"] = time.time()
    except Exception as e:  # noqa
        h._json_response(500, {"ok": False, "error": f"验收跑批失败: {e}"})


def register(router) -> None:
    router.add("GET", "/api/acceptance", _handle_acceptance_get)
    router.add("GET", "/api/acceptance/history", _handle_acceptance_history)
    router.add("POST", "/api/acceptance/run", _handle_acceptance_run)
