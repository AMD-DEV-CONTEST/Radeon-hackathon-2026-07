#!/usr/bin/env python3
"""XAI 成功指标一键快照（T6 · 六维验收·维度六 治理回看）

定期（建议每周）运行，打印当前成功指标快照，对照 SUCCESS_METRICS.md 看趋势。
组合：服务可观测(/api/metrics) + 诚实检查 + 端到端冒烟 + 测试规模。

用法：python3 scripts/metrics_snapshot.py
"""
from __future__ import annotations
import glob
import json
import os
import subprocess
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = "/Users/Admin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
TOKEN = open(os.path.expanduser("~/.xai/.server_token")).read().strip()


def _run(script: str):
    try:
        return subprocess.run([PY, script], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
    except Exception as e:  # noqa
        return None


def main():
    print("=" * 62)
    print("XAI 成功指标快照   ", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 62)

    # 1. 服务可观测
    print("\n[服务 / 可观测]")
    try:
        req = urllib.request.Request("http://127.0.0.1:8000/api/metrics",
                                     headers={"X-Auth-Token": TOKEN})
        m = json.loads(urllib.request.urlopen(req, timeout=5).read())
        t = m.get("tracer", {})
        print(f"  uptime        : {m.get('uptime_human')}")
        print(f"  tracer        : total={t.get('total')} success_rate={t.get('success_rate')} "
              f"p95={t.get('p95_latency_ms')}ms")
        wh = m.get("workflow_history", {})
        print(f"  workflow      : errors={wh.get('errors')}/{wh.get('total')}")
    except Exception as e:
        print(f"  未在线（{e}）— 跳过可观测指标（启动服务后重跑）")

    # 2. 诚实检查
    print("\n[诚实·价值·治理]")
    r = _run("scripts/honesty_check.py")
    if r and r.returncode == 0:
        for line in r.stdout.strip().splitlines()[-6:]:
            print("  ", line)
    else:
        print("  (honesty_check 未运行/异常)")

    # 3. 端到端冒烟
    print("\n[端到端冒烟]")
    r = _run("scripts/smoke_test.py")
    if r and r.returncode == 0:
        for line in r.stdout.strip().splitlines()[-4:]:
            print("  ", line)
    else:
        print("  (smoke_test 未运行/异常)")

    # 4. 测试规模
    tests = glob.glob(os.path.join(ROOT, "tests", "test_*.py"))
    print(f"\n[测试规模] {len(tests)} 个测试文件")
    print("  （完整通过率请跑：python3 -m pytest tests/ -q）")

    print("\n快照完成。对照 SUCCESS_METRICS.md 看趋势；完整 6 维见 ACCEPTANCE_XAI_LIVE_*.md")


if __name__ == "__main__":
    main()
