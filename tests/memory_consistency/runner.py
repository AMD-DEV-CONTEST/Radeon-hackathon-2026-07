"""Memory-consistency test runner (zero external dependencies).

Usage (from the repository root):

    # 用 mock 适配器做框架自检（无需 LLM / GPU / 网络）
    python -m tests.memory_consistency.runner --adapter mock
    python -m tests.memory_consistency.runner --adapter mock --mock-mode confused

    # 接真实 ReAct Agent（需 AMD ROCm + vLLM 环境；延迟 import src.agent.core）
    python -m tests.memory_consistency.runner --adapter react --memory-dir /tmp/mem_test

    # 只看单个场景 / 输出 markdown 报告
    python -m tests.memory_consistency.runner --adapter mock --scenario S2,S4,S10
    python -m tests.memory_consistency.runner --adapter mock --report-out artifacts/memory_report.md

Exit code: 0 = 全部 PASS, 1 = 存在 FAIL。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SCENARIOS = BASE_DIR / "scenarios.json"


# ── Loading ─────────────────────────────────────────────────────────


def load_scenarios(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else DEFAULT_SCENARIOS
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data["scenarios"]


# ── Runner ──────────────────────────────────────────────────────────


class ScenarioRunner:
    """Runs a scenario turn-by-turn through an adapter, then judges it.

    The runner owns `history` bookkeeping: within a session, all prior
    [user, assistant] pairs are accumulated; across sessions the history
    is reset (mimicking a fresh conversation), while the shared memory
    directory (AGENT_MEMORY_DIR) persists — that is exactly how the
    three-tier memory is meant to survive session boundaries.
    """

    def __init__(self, adapter, memory_dir: str | None = None):
        self.adapter = adapter
        self.memory_dir = memory_dir

    def _fresh_memory_env(self) -> str | None:
        """Point AGENT_MEMORY_DIR at an isolated temp dir (react mode)."""
        if not self.adapter.USES_MEMORY:
            return None
        tmp = tempfile.mkdtemp(prefix="mem_test_")
        os.environ["AGENT_MEMORY_DIR"] = tmp
        return tmp

    def run(self, scenario: dict) -> dict:
        from .judge import evaluate_scenario

        fresh_dir = self._fresh_memory_env()
        try:
            outputs: dict[int, str] = {}
            history: list[list[str]] = []
            turn_index = 0
            sessions = scenario.get("sessions", [])
            for sess in sessions:
                if sess.get("session", 1) > 1:
                    history = []  # new conversation: no prior messages
                for turn in sess.get("turns", []):
                    turn_index += 1
                    reply = self.adapter.respond(
                        prompt=turn["prompt"],
                        history=history,
                        scenario_id=scenario.get("id", ""),
                        session=sess.get("session", 1),
                        turn_index=turn_index,
                    )
                    outputs[turn.get("round", turn_index)] = reply
                    history.append([turn["prompt"], reply])

            result = evaluate_scenario(outputs, scenario)
            result["rounds"] = turn_index
            result["memory_dir"] = fresh_dir or "n/a (mock)"
            return result
        finally:
            if fresh_dir:
                import shutil
                shutil.rmtree(fresh_dir, ignore_errors=True)

    def run_all(self, scenarios: list[dict], filter_ids: list[str] | None = None) -> list[dict]:
        results = []
        for sc in scenarios:
            if filter_ids and sc.get("id") not in filter_ids:
                continue
            results.append(self.run(sc))
        return results


# ── Adapter factory ─────────────────────────────────────────────────


def build_adapter(args: argparse.Namespace):
    if args.adapter == "mock":
        from .adapters.mock import MockAdapter
        return MockAdapter(load_scenarios(), mode=args.mock_mode)
    if args.adapter == "react":
        from .adapters.react import ReactAdapter
        return ReactAdapter(max_iterations=args.max_iterations)
    raise SystemExit(f"未知 adapter: {args.adapter}")


# ── Reporting ───────────────────────────────────────────────────────


def format_console(results: list[dict]) -> str:
    lines: list[str] = []
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}
    lines.append(f"记忆一致性测试 | 共 {len(results)} 个场景")
    lines.append("-" * 72)
    for r in results:
        lines.append(f"{icon.get(r['status'], '?')} [{r['id']}] {r['name']}  ->  {r['status']}  ({r['rounds']} 轮)")
        for d in r["details"]:
            if not d["passed"]:
                why = "；".join(d["reasons"]) or "未通过"
                lines.append(f"      └─ R{d['round']} ✗ {why}  {('[' + d['note'] + ']') if d.get('note') else ''}")
    lines.append("-" * 72)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] != "PASS")
    lines.append(f"结果: PASS {passed} / FAIL+WARN {failed}")
    return "\n".join(lines)


def format_markdown(results: list[dict], meta: dict) -> str:
    lines = [
        "# 多轮记忆一致性测试报告",
        "",
        f"- 时间: {meta['time']}",
        f"- 适配器: `{meta['adapter']}`",
        f"- 场景数: {len(results)}",
        "",
        "| ID | 场景 | 状态 | 失败轮次 | 说明 |",
        "|----|------|------|---------|------|",
    ]
    for r in results:
        fail_str = ",".join(f"R{x}" for x in r["failed_rounds"]) or "-"
        lines.append(f"| {r['id']} | {r['name']} | {r['status']} | {fail_str} | {r.get('detail_note', '')} |")
    lines.append("")
    lines.append("## 明细")
    lines.append("")
    for r in results:
        lines.append(f"### {r['id']} {r['name']} — {r['status']}")
        lines.append("")
        for d in r["details"]:
            mark = "✅" if d["passed"] else "❌"
            why = "；".join(d["reasons"]) if d["reasons"] else "通过"
            lines.append(f"- {mark} R{d['round']}: {why}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="多轮记忆一致性测试")
    parser.add_argument("--adapter", choices=["mock", "react"], default="mock")
    parser.add_argument("--mock-mode", choices=["correct", "confused"], default="correct",
                        help="mock 适配器模式：correct=理想行为(应全PASS)；confused=故意串台(应全FAIL)")
    parser.add_argument("--max-iterations", type=int, default=6, help="react 模式 Agent 最大推理轮数")
    parser.add_argument("--memory-dir", default=None, help="react 模式记忆目录（默认临时目录，测试隔离）")
    parser.add_argument("--scenario", default=None, help="只跑指定场景，逗号分隔，如 S2,S4,S10")
    parser.add_argument("--report-out", default=None, help="输出 markdown 报告路径")
    args = parser.parse_args(argv)

    scenarios = load_scenarios()
    filter_ids = [s.strip() for s in args.scenario.split(",")] if args.scenario else None

    runner = ScenarioRunner(build_adapter(args), memory_dir=args.memory_dir)
    results = runner.run_all(scenarios, filter_ids=filter_ids)

    print(format_console(results))

    if args.report_out:
        out_path = Path(args.report_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            format_markdown(results, {
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "adapter": f"{args.adapter}({args.mock_mode})" if args.adapter == "mock" else "react",
            }),
            encoding="utf-8",
        )
        print(f"\n报告已写入: {out_path}")

    return 0 if all(r["status"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
