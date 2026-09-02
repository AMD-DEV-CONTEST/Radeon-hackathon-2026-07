"""Phase C 全场景验收测试脚本。

创建覆盖 7 种状态的任务表 + 模拟证据，跑完整流水线并输出所有报告，
对照 APPLICATION_DEVELOPER_WORKPLAN.zh-CN.md 阶段 C 的要求逐项验证。
"""

from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from datetime import date, timedelta

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# Ensure the project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from app.tools.task_reader import read_tasks, TaskRecord
from app.tools.task_checker import check_task
from app.reports.generator import (
    TaskEvaluation,
    TaskStatus,
    evaluate_with_rules,
    generate_weekly_report,
    generate_risk_csv,
    generate_next_week_plan,
)

# ===========================================================================
# 1. 创建上周任务表 (CSV)
# ===========================================================================

today = date.today()

TASK_CSV = f"""任务名称,负责人,截止日期,优先级,验收标准,来源
接口开发,张三,{today + timedelta(days=3)},high,API文档和测试通过,需求文档
UI开发,李四,{today + timedelta(days=5)},normal,代码完成加文档,设计稿
数据库迁移,王五,{today + timedelta(days=7)},normal,数据一致性和回滚预案,DBA方案
性能优化,赵六,{today + timedelta(days=14)},low,响应时间降低50%,压测报告
旧版维护,孙七,{today - timedelta(days=5)},high,旧版稳定运行无故障,运维周报
系统测试,周八,{today + timedelta(days=1)},high,测试计划、测试用例、测试执行、测试报告,测试方案
废弃功能,吴九,{today + timedelta(days=10)},low,功能已下线无报错,产品决策"""

# ===========================================================================
# 2. 模拟证据（模拟 RAG 检索结果）
# ===========================================================================

EVIDENCE: dict[str, list[str]] = {
    # ✅ 已完成：证据充分，验收标准全满足
    "接口开发": [
        "[source:接口文档] API 文档已交付，所有接口已定义并通过评审",
        "[source:测试报告] 接口自动化测试全部通过，覆盖率 95%",
        "[source:周报] 接口开发已完成，已上线预发布环境",
        "[source:代码仓库] PR #42 已合入主分支，接口开发工作结束",
    ],
    # 🟡 基本完成：代码写完了，文档还在收尾
    "UI开发": [
        "[source:代码仓库] UI 组件开发已完成，PR #45 已合入",
        "[source:设计评审] UI 还原度评审通过",
        "[source:周报] 页面开发已完成，文档还在整理中",
    ],
    # 🔵 进行中：有进展，但没有任何完成信号
    "数据库迁移": [
        "[source:迁移方案] 数据库迁移方案已评审通过",
        "[source:周报] 迁移脚本正在开发，数据迁移进度约 40%",
    ],
    # ⚪ 未开始：没有任何进展证据
    "性能优化": [],
    # 🔴 已延期：已过截止日期，证据很少
    "旧版维护": [
        "[source:周报] 旧版本周出现 2 次小故障，已临时修复",
    ],
    # 🟠 待确认：只有计划和部分记录，没有最终报告（关键验收场景！）
    "系统测试": [
        "[source:测试计划] 系统测试计划已编写完成并通过评审",
        "[source:周报] 测试用例正在编写，目前完成约 60%，部分用例已评审",
        "[source:会议纪要] 测试环境已搭建，部分模块开始执行",
    ],
    # ❌ 已取消：明确取消
    "废弃功能": [
        "[source:产品决策] 产品会议决定废弃该功能，不再维护",
        "[source:周报] 相关代码已标记为 deprecated",
    ],
}

# ===========================================================================
# 3. 跑流水线
# ===========================================================================


def main() -> None:
    print("=" * 72)
    print("Phase C 全场景验收测试")
    print(f"运行日期: {today}")
    print("=" * 72)

    # --- Step 1: 写入 CSV ---
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
    ) as f:
        f.write(TASK_CSV)
        csv_path = f.name

    try:
        # --- Step 2: 读取任务 ---
        print("\n📂 读取任务表…")
        tasks = read_tasks(csv_path)
        print(f"   共读取 {len(tasks)} 个任务：")
        for t in tasks:
            print(f"   - [{t.priority:6s}] {t.title:10s} | {t.assignee:4s} | {t.deadline or '无截止':12s}")
            if t.acceptance_criteria:
                print(f"     验收标准: {t.acceptance_criteria}")

        # --- Step 3: 逐任务核验 ---
        print(f"\n🔍 规则核验（check_task）…")
        evaluations: list[TaskEvaluation] = []
        for t in tasks:
            evidence = EVIDENCE.get(t.title, [])
            ev = evaluate_with_rules(t, evidence)

            # 规则核验详情
            cr = ev.check_result
            if cr:
                print(f"\n   {'─' * 60}")
                print(f"   任务: {t.title}")
                print(f"   证据数: {len(evidence)} | 时间: {cr.time_status}")
                print(f"   完成关键词: {cr.completion_keywords_found or '无'}")
                print(f"   验收标准匹配: {cr.acceptance_criteria_matched}")
                print(f"   缺失项: {cr.missing_items or '无'}")
                print(f"   规则状态: {cr.rule_based_status}")
                print(f"   最终状态: {ev.status.value} ({ev.display_status})")
                print(f"   风险: {ev.risk_level.upper()} | {ev.risk_reason or '无风险'}")
                print(f"   建议: {ev.recommendation}")
            evaluations.append(ev)

        # --- Step 4: 生成 Markdown 周报 ---
        print(f"\n{'=' * 72}")
        print(f"📄 生成 Markdown 周报")
        print(f"{'=' * 72}")

        weekly = generate_weekly_report(
            evaluations, project_name="ProjectPack Office Agent Demo", week_label="上周"
        )
        print(weekly)

        # --- Step 5: 生成 CSV 风险清单 ---
        print(f"\n{'=' * 72}")
        print(f"📊 生成 CSV 风险清单")
        print(f"{'=' * 72}")

        risk_csv = generate_risk_csv(evaluations)
        print(risk_csv)

        # --- Step 6: 生成下周计划 ---
        print(f"\n{'=' * 72}")
        print(f"📅 生成下周计划草案")
        print(f"{'=' * 72}")

        plan = generate_next_week_plan(
            evaluations, project_name="ProjectPack Office Agent Demo"
        )
        print(plan)

        # --- Step 7: 验收标准核对 ---
        print(f"\n{'=' * 72}")
        print(f"✅ 验收标准核对（对照 WORKPLAN 阶段 C）")
        print(f"{'=' * 72}")

        results: list[tuple[bool, str, str]] = []

        # 验收标准 1: 从 XLSX/CSV 读取任务
        results.append((len(tasks) == 7,
            f"1. 从 CSV 读取任务（标题/负责人/截止日/优先级/验收标准/来源）",
            f"期望 7，实际 {len(tasks)} | {'✅' if len(tasks) == 7 else '❌'}"))

        # 验收标准 2: 系统测试判为待确认/进行中（核心验收标准）
        sys_test_ev = next(e for e in evaluations if e.task.title == "系统测试")
        check_2_ok = sys_test_ev.status in (TaskStatus.NEEDS_CONFIRMATION, TaskStatus.IN_PROGRESS)
        results.append((check_2_ok,
            f"2. 「系统测试」只有计划+部分记录、无最终报告 → 待确认/进行中",
            f"实际状态: {sys_test_ev.status.value} ({sys_test_ev.display_status}) | {'✅' if check_2_ok else '❌'}"))

        # 验证不是误判为 completed
        check_2b = sys_test_ev.status != TaskStatus.COMPLETED
        results.append((check_2b,
            f"2b. 「系统测试」不被误判为已完成",
            f"实际状态: {sys_test_ev.status.value} | {'✅' if check_2b else '❌'}"))

        # 验收标准 3: 7 种状态全部支持
        all_statuses = {e.status.value for e in evaluations}
        expected_statuses = {"completed", "mostly_completed", "in_progress",
                            "not_started", "delayed", "needs_confirmation", "cancelled"}
        check_3 = expected_statuses.issubset(all_statuses)
        results.append((check_3,
            f"3. 支持 7 种状态（已完成/基本完成/进行中/未开始/已延期/待确认/已取消）",
            f"实际出现: {all_statuses} | {'✅' if check_3 else '❌'}"))

        # 验收标准 4: Markdown 周报含状态和风险
        check_4 = "ProjectPack Office Agent Demo" in weekly and "⚠️ 重点关注" in weekly
        results.append((check_4,
            f"4. Markdown 周报包含项目名和高风险关注区块",
            f"{'✅' if check_4 else '❌'}"))

        # 验收标准 5: 高风险项出现在风险 CSV
        risk_reader = csv.reader(io.StringIO(risk_csv))
        risk_rows = list(risk_reader)
        check_5 = len(risk_rows) > 1  # Header + at least 1 risk
        results.append((check_5,
            f"5. CSV 风险清单含中高风险项（{len(risk_rows) - 1} 项）",
            f"{'✅' if check_5 else '❌'}"))

        # 验收标准 6: 下周计划标注草案
        check_6 = "草案" in plan and "请勿直接覆盖原始任务列表" in plan
        results.append((check_6,
            f"6. 下周计划标注「草案」且声明不覆盖原任务",
            f"{'✅' if check_6 else '❌'}"))

        # 验收标准 7: 每个评价有来源或证据缺口
        check_7 = all(e.evidence_summary for e in evaluations)
        results.append((check_7,
            f"7. 每项评估都有 evidence_summary（来源或证据缺口）",
            f"{'✅' if check_7 else '❌'}"))

        # --- 打印验收结果 ---
        print()
        all_pass = True
        for ok, desc, detail in results:
            status = "✅ PASS" if ok else "❌ FAIL"
            print(f"{status} | {desc}")
            print(f"        {detail}")
            if not ok:
                all_pass = False
        print()

        if all_pass:
            print("🎉 全部验收标准通过！")
        else:
            print("⚠️ 存在未通过的验收标准，需要检查。")

        # --- Step 8: 详细状态合理性分析 ---
        print(f"\n{'=' * 72}")
        print(f"📋 各任务状态合理性分析")
        print(f"{'=' * 72}")

        expected: dict[str, str] = {
            "接口开发": "completed / mostly_completed",
            "UI开发": "mostly_completed / completed",
            "数据库迁移": "in_progress",
            "性能优化": "not_started",
            "旧版维护": "delayed",
            "系统测试": "needs_confirmation / in_progress（关键：不能是 completed）",
            "废弃功能": "cancelled",
        }

        for ev in evaluations:
            exp = expected.get(ev.task.title, "?")
            match = "✅" if ev.status.value in exp or any(
                s.strip() in exp for s in ev.status.value.split("/")
            ) else "⚠️"
            print(f"   {match} {ev.task.title:10s} → {ev.status.value:20s} ({ev.display_status})  期望: {exp}")

    finally:
        os.unlink(csv_path)


if __name__ == "__main__":
    main()
