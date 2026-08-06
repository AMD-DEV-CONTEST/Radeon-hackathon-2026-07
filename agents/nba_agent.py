"""
agents/nba_agent.py - NBA/ABET Accreditation Export Agent
Module 5: Aggregates CO/PO attainment metrics and generates
          continuous improvement reports for accreditation audits.
"""

from typing import Optional
from schemas import NBAAttainmentReport
from llm_service import generate_text
from database import (
    get_course,
    get_course_outcomes,
    compute_co_attainment,
    get_all_students,
    get_class_logs,
    save_nba_report,
    get_nba_reports,
)
from config import NBA_ATTAINMENT_BENCHMARK, SYSTEM_PROMPT_OBE_AUDITOR


class NBAAgent:
    """
    Agent responsible for generating NBA/ABET accreditation course file reports.
    """

    def __init__(self):
        pass

    def generate_improvement_action(self, co_id: str, actual_pct: float, target_pct: float) -> str:
        """Generate a continuous improvement action for an underperforming CO."""
        gap = target_pct - actual_pct

        if gap < 10:
            return (
                f"Small gap ({gap:.1f}%) for {co_id}. "
                f"Increase practice sessions, provide additional resources, "
                f"and conduct focused revision classes."
            )
        elif gap < 20:
            return (
                f"Moderate gap ({gap:.1f}%) for {co_id}. "
                f"Revise teaching methodology — introduce more hands-on labs, "
                f"case studies, and peer-learning activities. "
                f"Consider formative assessments to track progress."
            )
        else:
            return (
                f"Significant gap ({gap:.1f}%) for {co_id}. "
                f"Fundamental restructuring needed: curriculum revision, "
                f"additional tutorial hours, guest lectures, and intensive "
                f"remedial coaching. Consider re-evaluating CO alignment with course content."
            )

    def compute_attainment(self, course_id: str) -> list[NBAAttainmentReport]:
        """Compute CO attainment for the entire course term."""
        outcomes = get_course_outcomes(course_id)
        attainment = compute_co_attainment(course_id)

        reports: list[NBAAttainmentReport] = []

        for co in outcomes:
            co_id = co["co_id"]
            actual = attainment.get(co_id, 0.0)
            target = NBA_ATTAINMENT_BENCHMARK
            status = "Attained" if actual >= target else "Not Attained"

            if status == "Attained":
                action = (
                    f"Maintain current pedagogy for {co_id}. "
                    f"Consider enrichment activities and advanced problem sets."
                )
            else:
                action = self.generate_improvement_action(co_id, actual, target)

            report = NBAAttainmentReport(
                co_id=co_id,
                target_score_pct=target,
                actual_score_pct=round(actual, 2),
                attainment_status=status,
                continuous_improvement_action=action,
            )
            reports.append(report)

        # Persist to database
        save_nba_report(course_id, reports)

        return reports

    def compile_course_file(self, course_id: str) -> str:
        """Compile the full NBA Course File Report in Markdown format."""
        # Gather data
        course = get_course(course_id)
        outcomes = get_course_outcomes(course_id)
        reports = self.compute_attainment(course_id)
        students = get_all_students(course_id)
        logs = get_class_logs(course_id)

        if not course:
            return "⚠️ No course found. Please upload a syllabus first."

        # Build report
        md = "# 📋 NBA Course File Report\n\n"
        md += "---\n\n"

        # Section 1: Course Information
        md += "## 1. Course Information\n\n"
        md += f"| Field | Value |\n|-------|-------|\n"
        md += f"| Course Code | {course.get('course_code', 'N/A')} |\n"
        md += f"| Course Title | {course.get('course_title', 'N/A')} |\n"
        md += f"| Course ID | `{course_id}` |\n\n"

        # Section 2: Course Outcomes & Bloom's Mapping
        md += "## 2. Course Outcomes & Bloom's Taxonomy Mapping\n\n"
        md += "| CO ID | Statement | Bloom's Level | Valid |\n"
        md += "|-------|-----------|---------------|-------|\n"
        for co in outcomes:
            icon = "✅" if co.get("is_valid") else "❌"
            md += f"| {co['co_id']} | {co.get('statement', '')[:60]} | {co.get('blooms_level', '')} | {icon} |\n"

        # Section 3: CO-PO Mapping Placeholder
        md += "\n## 3. CO-PO Mapping\n\n"
        md += "| CO | PO1 | PO2 | PO3 | PO4 | PO5 |\n"
        md += "|-----|-----|-----|-----|-----|------|\n"
        for co in outcomes:
            # Simple mapping: alternate checkmarks for demonstration
            marks = []
            for i in range(5):
                marks.append("✓" if (hash(co["co_id"]) + i) % 3 == 0 else "—")
            md += f"| {co['co_id']} | {' | '.join(marks)} |\n"
        md += "\n*Note: CO-PO mapping should be customized per institutional requirements.*\n"

        # Section 4: Direct CO Attainment Table
        md += "\n## 4. Direct CO Attainment\n\n"
        md += "| CO ID | Target % | Actual % | Status | Gap | Action |\n"
        md += "|-------|----------|----------|--------|-----|--------|\n"
        attained_count = 0
        not_attained_count = 0
        for r in reports:
            icon = "✅" if r.attainment_status == "Attained" else "❌"
            gap = r.target_score_pct - r.actual_score_pct
            if r.attainment_status == "Attained":
                attained_count += 1
            else:
                not_attained_count += 1
            action_short = r.continuous_improvement_action[:60] + "..."
            md += f"| {r.co_id} | {r.target_score_pct}% | {r.actual_score_pct}% | {icon} {r.attainment_status} | {gap:.1f}% | {action_short} |\n"

        # Section 5: Attainment Summary
        total_cos = len(reports)
        attainment_rate = (attained_count / total_cos * 100) if total_cos > 0 else 0
        md += f"\n## 5. Attainment Summary\n\n"
        md += f"- **Total Course Outcomes:** {total_cos}\n"
        md += f"- **Attained:** {attained_count}\n"
        md += f"- **Not Attained:** {not_attained_count}\n"
        md += f"- **CO Attainment Rate:** {attainment_rate:.0f}%\n"
        md += f"- **Benchmark:** {NBA_ATTAINMENT_BENCHMARK}%\n\n"

        # Section 6: Continuous Improvement Plan
        md += "## 6. Continuous Improvement Plan\n\n"
        for r in reports:
            md += f"### {r.co_id}\n"
            md += f"**Status:** {r.attainment_status} ({r.actual_score_pct}% / {r.target_score_pct}%)\n\n"
            md += f"**Action:** {r.continuous_improvement_action}\n\n"

        # Section 7: Student Performance Distribution
        if students:
            cohorts = {"Remedial": 0, "Average": 0, "Advanced": 0}
            for s in students:
                c = s.get("cohort", "Average")
                cohorts[c] = cohorts.get(c, 0) + 1

            md += "## 7. Student Performance Distribution\n\n"
            md += "| Cohort | Count | Percentage |\n"
            md += "|--------|-------|------------|\n"
            total_students = len(students)
            for name, count in cohorts.items():
                pct = (count / total_students * 100) if total_students > 0 else 0
                md += f"| {name} | {count} | {pct:.0f}% |\n"

        # Section 8: Class Progress Summary
        if logs:
            total_planned = len(get_course_outcomes(course_id))  # rough proxy
            on_track = sum(1 for l in logs if l.get("completed_on_schedule"))
            md += "\n## 8. Class Progress Summary\n\n"
            md += f"- **Total Lectures Delivered:** {len(logs)}\n"
            md += f"- **On Schedule:** {on_track}\n"
            md += f"- **Behind Schedule:** {len(logs) - on_track}\n"

        md += "\n---\n\n"
        md += "*Report generated by EduCopilot — Autonomous Virtual TA & Accreditation Engine*\n"

        return md

    def get_attainment_table(self, course_id: str) -> str:
        """Generate a formatted attainment table for the dashboard."""
        reports = get_nba_reports(course_id)

        # If no reports exist yet, compute them
        if not reports:
            self.compute_attainment(course_id)
            reports = get_nba_reports(course_id)

        if not reports:
            return "⚠️ No attainment data available. Please ensure student scores have been uploaded."

        md = "## CO Attainment Table\n\n"
        md += "| CO ID | Target % | Actual % | Status | Action |\n"
        md += "|-------|----------|----------|--------|--------|\n"

        for r in reports:
            icon = "✅" if r.get("attainment_status") == "Attained" else "❌"
            action_short = r.get("continuous_improvement_action", "")[:50]
            md += f"| {r['co_id']} | {r['target_score_pct']}% | {r['actual_score_pct']}% | {icon} {r['attainment_status']} | {action_short}... |\n"

        return md
