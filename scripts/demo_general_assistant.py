#!/usr/bin/env python3
"""Demo — 通用量化助理：意图路由 + 本地能力 + 外部工具降级全链路。

在 AMD ROCm 环境或本地（mock 模式，零网络）运行，逐题演示 Agent 的
自主规划。每道题打印：意图分类 → RAG → 降级原因 → 工具与模式 →
steps 审计轨迹（评委可见的决策链）。

用法：
    cd track2-agentic-ai
    EXTERNAL_TOOLS_MODE=mock  python scripts/demo_general_assistant.py   # 演示/CI
    EXTERNAL_TOOLS_MODE=real python scripts/demo_general_assistant.py   # 现场（需 akshare/TAVILY_API_KEY）

录制建议：终端背景深色，宽 110 列；先跑 --all 录一条，再针对 1-2 题
加 --slow 慢速逐行展示 steps，评委最能记住"自主规划"这一幕。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.external.registry import handle_query  # noqa: E402
from src.tools.external.knowledge_store import store  # noqa: E402

# (标签, 问题, 期望路由)
CASES = [
    ("策略生成", "帮我写一个双均线策略：5 日上穿 20 日买入，跌破卖出，仓位 30%，止损 5%",
     "dsl_pipeline"),
    ("行情查询", "510300 最新行情怎么样", "external_fallback"),
    ("公告查询", "510300 最近有什么公告", "external_fallback"),
    ("资讯研究", "美联储议息声明，做鹰派鸽派情绪分析", "external_fallback"),
    ("规则知识", "A股 T+1 交易规则是什么", "rag"),
    ("本地计算", "计算组合的 VaR 和 CVaR", "local_compute"),
    ("闲聊", "你好，介绍一下你自己", "general"),
]


def _print_steps(steps: list[dict]) -> None:
    print("  ┌─ steps 审计轨迹（评委可见的自主规划）")
    for s in steps:
        print(f"  │  {json.dumps(s, ensure_ascii=False)}")
    print("  └─")


def run_case(label: str, question: str, expected: str, slow: bool) -> bool:
    print("=" * 78)
    print(f"▶ [{label}] {question}")
    t0 = time.time()
    result = handle_query(question)
    elapsed = time.time() - t0
    d = result.to_dict()

    print(f"  route={d['route']}  tool={d['tool']}  mode={d['data_mode']}  ({elapsed*1000:.0f} ms)")
    if slow:
        _print_steps(d["steps"])
    else:
        print(f"  steps: {len(d['steps'])} 步 → {', '.join(s['step'] for s in d['steps'])}")

    if d["route"] == "external_fallback":
        for r in d["data"]["results"]:
            n = len(r["data"].get("rows", [])) if isinstance(r.get("data", {}).get("rows"), list) else 0
            print(f"  └─ {r['tool']}: source={r['source']}  conf={r['source_confidence']}  "
                  f"ttl~{r['effective_until'][11:19]}  rows={n}")

    ok = d["route"] == expected
    print(f"  {'✅' if ok else '❌'} 预期 route={expected}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="通用量化助理演示")
    parser.add_argument("--all", action="store_true", help="跑全部 7 题")
    parser.add_argument("--slow", action="store_true", help="逐题打印完整 steps 审计轨迹")
    parser.add_argument("--only", default=None, help="只跑指定标签（逗号分隔），如 --only 策略生成,行情查询")
    args = parser.parse_args()

    cases = CASES
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in CASES if c[0] in wanted]

    results = []
    for label, question, expected in cases:
        try:
            results.append((label, run_case(label, question, expected, args.slow)))
        except Exception as exc:  # pragma: no cover
            print(f"  ❌ {label} 异常: {exc}")
            results.append((label, False))

    print("=" * 78)
    passed = sum(1 for _, ok in results if ok)
    print(f"结果: {passed}/{len(results)} 通过")
    print(f"候选知识区: {len(store.list_valid())} 条有效快照（TTL 隔离，未自动进长期记忆）")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
