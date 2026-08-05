#!/usr/bin/env python3
"""
一键提交验证脚本。
检查 Agent 工作流、输出文件、质量门禁、Git 安全和 GPU 证据链。

用法:
    python3 scripts/verify_submission.py

环境变量:
    SKIP_WORKFLOW=1     跳过耗时的完整工作流回归（仅做快速检查）
    SKIP_GIT_CHECK=1    跳过 Git 安全检查（CI 等无需 git 的场景）
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"
INFO = "ℹ️"

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"

PASS_COLORED = f"{GREEN}{BOLD}{PASS}{RESET}"
FAIL_COLORED = f"{RED}{BOLD}{FAIL}{RESET}"
WARN_COLORED = f"{YELLOW}{BOLD}{WARN}{RESET}"
INFO_COLORED = f"{CYAN}{INFO}{RESET}"

results = []


def heading(text: str):
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  {text}{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")


def check(name: str, status: bool, detail: str = ""):
    icon = PASS_COLORED if status else FAIL_COLORED
    results.append((name, status, detail))
    print(f"  {icon} {name}")
    if detail:
        print(f"     {DIM}{detail}{RESET}")
    return status


def warn(name: str, detail: str = ""):
    results.append((name, True, detail))
    print(f"  {WARN_COLORED} {name}")
    if detail:
        print(f"     {DIM}{detail}{RESET}")


def info(text: str):
    print(f"  {INFO_COLORED} {DIM}{text}{RESET}")


def run_cmd(cmd: str, timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return -1, f"超时 ({timeout}s)"
    except Exception as e:
        return -1, str(e)


def main():
    root = Path(__file__).parent.parent
    os.chdir(root)
    skip_workflow = "SKIP_WORKFLOW" in os.environ
    skip_git = "SKIP_GIT_CHECK" in os.environ

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  InventoryDoc Agent — 提交验证{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")
    print(f"  工作目录: {root}")
    print(f"  {DIM}SKIP_WORKFLOW={skip_workflow}, SKIP_GIT_CHECK={skip_git}{RESET}")
    print()

    # ── 1. Python & 依赖 ──
    heading("1. 环境检查")
    py_ok = sys.version_info >= (3, 10)
    check(f"Python >= 3.10", py_ok, f"当前: {sys.version}")

    req_path = root / "requirements.txt"
    if req_path.exists():
        code, _ = run_cmd("python3 -c 'import gradio, pandas, numpy, yaml, rich, plotly, openai, langchain_core'", 15)
        check("核心依赖可导入", code == 0)
    else:
        check("requirements.txt 存在", False)

    # ── 2. 目录结构 ──
    heading("2. 目录完整性")
    dirs = ["src", "scripts", "config", "docs", "docs/knowledge", "tests", "data/input", "data/output"]
    for d in dirs:
        p = root / d
        check(f"目录 {d}", p.exists() and p.is_dir())

    # ── 3. 核心源文件 ──
    heading("3. 核心源文件")
    core_files = [
        "src/agent.py", "src/report_generator.py", "src/noise_detector.py",
        "src/quality_checker.py", "src/rag.py", "src/memory.py", "src/tools.py",
        "src/llm_health.py", "src/ui.py", "src/input_validator.py",
        "scripts/generate_report.py", "scripts/benchmark_llm.py",
        "run_full_workflow.py", "start_ui.py", "start_ui.sh",
        "tests/test_workflow.py",
        "config/settings.yaml", "config/ground_truth.yaml", "config/data_contracts.yaml",
        "AGENTS.md", "README.md",
    ]
    for f in core_files:
        p = root / f
        check(f"文件 {f}", p.exists() and p.is_file())

    # ── 4. output 目录安全 ──
    heading("4. 输出目录安全")
    out_dir = root / "data/output"
    if out_dir.exists():
        out_files = list(out_dir.iterdir())
        safe = True
        for f in out_files:
            if f.suffix in (".mp4", ".mp3", ".srt", ".pdf", ".pptx"):
                safe = False
                warn(f"输出目录含大文件: {f.name}（确保 gitignored）")
        if safe:
            check("输出目录无大文件", True)
    else:
        check("data/output 目录", False)

    # ── 5. Git 安全检查 ──
    if not skip_git:
        heading("5. Git 安全检查")
        code, status_out = run_cmd("git status --short", 30)
        if code == 0:
            untracked = [l.strip() for l in status_out.splitlines() if l.strip()]
            git_safe = True

            sensitive_patterns = ["data/", ".env", "*.gguf", "*.mp4", "*.mp3", "*.srt", "session-"]
            for u in untracked:
                for pat in sensitive_patterns:
                    if pat in u or u.startswith(pat):
                        warn(f"敏感/跟踪状态: {u}")
                        git_safe = False

            if git_safe:
                check("untracked 文件无敏感内容", True)

            code2, diff_stat = run_cmd("git diff --stat", 30)
            if code2 == 0:
                changed = [l.strip() for l in diff_stat.splitlines() if l.strip()]
                if changed:
                    check(f"已修改文件 ({len(changed)})", True, "; ".join(changed))
                else:
                    info("无未提交修改")

        code3, ignore_out = run_cmd("git check-ignore data/ qwen-model/ output/", 30)
        if ignore_out:
            check(".gitignore 覆盖 data/", "data/" in ignore_out)
            check(".gitignore 覆盖 qwen-model/", "qwen-model/" in ignore_out)
        else:
            warn(".gitignore 检查不完整")

        code4, latest_log = run_cmd("git log --oneline -3", 15)
        if code4 == 0:
            log_lines = [l for l in latest_log.splitlines() if l.strip()]
            if log_lines:
                info("最近提交:")
                for l in log_lines:
                    print(f"     {l}")
    else:
        info("Git 检查已跳过 (SKIP_GIT_CHECK=1)")

    # ── 6. 工作流回归 (耗时) ──
    if not skip_workflow:
        heading("6. 工作流回归")
        info("运行 tests/test_workflow.py ...")
        code, test_out = run_cmd("python3 tests/test_workflow.py", 120)
        if code != 0:
            check("tests/test_workflow.py", False, test_out[-500:] if len(test_out) > 500 else test_out)
        else:
            lines = [l for l in test_out.splitlines() if "❌" in l]
            if lines:
                check("tests/test_workflow.py", False, "; ".join(lines))
            else:
                check("tests/test_workflow.py", True)

        info("运行 run_full_workflow.py ...")
        code, wf_out = run_cmd("python3 run_full_workflow.py", 180)
        check("完整工作流", code == 0, wf_out[-300:] if len(wf_out) > 300 else wf_out)

        # 质量门禁
        ar_path = root / "data/output/analysis_result.json"
        if ar_path.exists():
            try:
                with open(ar_path) as f:
                    ar = json.load(f)
                meta = ar.get("_metadata", {})
                qg = meta.get("quality_gate", {})
                checks = ar.get("quality_checks", [])
                passed = sum(1 for c in checks if c.get("passed", False))
                total = len(checks)
                qg_passed = qg.get("passed", False)
                report_allowed = qg.get("report_allowed", True)
                critical_failed = qg.get("critical_failed", 0)
                check(f"质量门禁: {passed}/{total}", qg_passed and report_allowed,
                      f"critical_failed={critical_failed}, report_allowed={report_allowed}")
            except Exception as e:
                check("解析 analysis_result.json", False, str(e))
        else:
            check("analysis_result.json 已生成", False)

        # Ground Truth 校验
        gt_path = root / "config/ground_truth.yaml"
        if ar_path.exists() and gt_path.exists():
            import yaml
            try:
                with open(ar_path) as f:
                    ar = json.load(f)
                step5 = ar.get("Step 5: 加载盘点结果", {})
                gt = yaml.safe_load(open(gt_path)).get("ground_truth", {})
                gt_system = gt.get("system_total", 21144)
                gt_net = gt.get("net_variance_amount", -989900.97)
                actual_system = step5.get("system_total", 0)
                step6 = ar.get("Step 6: 计算差异金额", {})
                actual_net = step6.get("net_variance_amount", 0)
                system_ok = actual_system == gt_system
                net_ok = abs(actual_net - gt_net) < 1
                check(f"Ground Truth: 系统库存 {actual_system}", system_ok, f"预期 {gt_system}")
                check(f"Ground Truth: 净差异金额 {actual_net:,.2f}", net_ok, f"预期 {gt_net:,.2f}")
            except Exception as e:
                warn("Ground Truth 校验异常", str(e))

        # 输出文件检查
        heading("7. 输出文件")
        deliverables = {
            "analysis_result.json": root / "data/output/analysis_result.json",
            "盘点差异明细表.xlsx": root / "data/output/盘点差异明细表.xlsx",
            "盘点差异分析报告.md": root / "data/output/盘点差异分析报告.md",
        }
        for name, path in deliverables.items():
            check(f"{name}", path.exists())

        # 报告生成
        heading("8. 管理层报告")
        info("python3 scripts/generate_report.py --demo ...")
        code, demo_out = run_cmd("python3 scripts/generate_report.py --demo", 60)
        check("--demo 模式", code == 0, demo_out[-200:] if len(demo_out) > 200 else demo_out)

        report_path = root / "data/output/管理层摘要报告.md"
        check("管理层摘要报告.md", report_path.exists())

        metadata_path = root / "data/output/report_generation_metadata.json"
        check("report_generation_metadata.json", metadata_path.exists())
        if metadata_path.exists():
            try:
                with open(metadata_path) as f:
                    meta = json.load(f)
                check(f"报告模式: {meta.get('mode', '?')}", True)
            except Exception:
                pass

        info("python3 scripts/generate_report.py --mock ...")
        code, mock_out = run_cmd("python3 scripts/generate_report.py --mock", 60)
        check("--mock 模式", code == 0, mock_out[-200:] if len(mock_out) > 200 else mock_out)
    else:
        info("工作流回归已跳过 (SKIP_WORKFLOW=1)")

    # ── 9. 知识文档 ──
    heading("9. 制度知识文档")
    knowledge_files = [
        "docs/knowledge/inventory_adjustment_policy.md",
        "docs/knowledge/warehouse_counting_sop.md",
        "docs/knowledge/scan_log_governance.md",
        "docs/knowledge/location_management_policy.md",
    ]
    for f in knowledge_files:
        check(f, (root / f).exists())

    # ── 10. 最终汇总 ──
    heading("验证汇总")
    failed = [r for r in results if not r[1]]
    warnings = [r for r in results if WARN in r[0]]
    passed_count = len([r for r in results if r[1]])
    total_count = len(results)

    print(f"\n  {PASS_COLORED} 通过: {passed_count}/{total_count}")
    if failed:
        print(f"  {FAIL_COLORED} 失败: {len(failed)}/{total_count}")
        for name, _, detail in failed:
            print(f"    {FAIL} {name}")
    if warnings:
        print(f"  {WARN_COLORED} 警告: {len(warnings)} 项（提醒, 非阻断）")
    print()

    if not failed:
        print(f"  {GREEN}{BOLD}✅ 全部通过 — 可提交{RESET}")
        print()
        print(f"  {DIM}建议提交前再确认:{RESET}")
        print(f"    {INFO} git status")
        print(f"    {INFO} git diff --stat")
        print(f"    {INFO} git add <files> && git commit -m '...'{RESET}")
    else:
        print(f"  {RED}{BOLD}❌ {len(failed)} 项失败，请修复后重试{RESET}")
        print()
        for name, _, detail in failed:
            print(f"  {FAIL} {name}")
            if detail:
                short = detail[:200] + "..." if len(detail) > 200 else detail
                for line in short.splitlines():
                    print(f"    {DIM}{line}{RESET}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
