"""
agents/tracking_agent.py - Daily Pacing & Progress Tracking Agent
Module 2: Compares logged class progress against target timelines,
          dynamically recalculates delivery schedules when behind.
"""

from typing import Optional
from schemas import ClassLogEntry
from llm_service import generate_text
from database import (
    get_planned_topic,
    get_lesson_plan,
    get_class_logs,
    get_last_completed_lecture,
    log_class_progress,
)
from config import SYSTEM_PROMPT_OBE_AUDITOR


class TrackingAgent:
    """Agent responsible for tracking daily class progress."""

    def __init__(self):
        pass

    def log_progress(
        self,
        course_id: str,
        lecture_num: int,
        topics_covered: str,
        teacher_comments: str = "",
        student_questions: str = "",
        pace_notes: str = "",
    ) -> dict:
        """Log class progress with enhanced feedback fields."""

        planned = get_planned_topic(course_id, lecture_num)

        if planned is None:
            log_class_progress(
                course_id, lecture_num, topics_covered,
                completed_on_schedule=True,
                teacher_comments=teacher_comments,
                student_questions=student_questions,
                pace_notes=pace_notes,
            )
            return {
                "status": "no_plan",
                "planned_topic": None,
                "actual_topic": topics_covered,
                "message": f"Lecture {lecture_num} logged. No planned topic for this lecture number.",
                "catch_up_plan": None,
            }

        planned_topic = planned["topic_description"]
        planned_words = set(planned_topic.lower().split())
        actual_words = set(topics_covered.lower().split())
        overlap = len(planned_words & actual_words) / max(len(planned_words), 1)
        on_schedule = overlap >= 0.3

        delay_reason = None
        if not on_schedule:
            delay_reason = f"Covered '{topics_covered}' instead of planned '{planned_topic}'"

        log_class_progress(
            course_id, lecture_num, topics_covered,
            completed_on_schedule=on_schedule,
            delay_reason=delay_reason,
            teacher_comments=teacher_comments,
            student_questions=student_questions,
            pace_notes=pace_notes,
        )

        result = {
            "status": "on_track" if on_schedule else "behind",
            "planned_topic": planned_topic,
            "actual_topic": topics_covered,
            "message": "",
            "catch_up_plan": None,
        }

        if on_schedule:
            result["message"] = f"✅ Lecture {lecture_num} is **on track**. Planned: '{planned_topic}'"
        else:
            result["message"] = (
                f"⚠️ Lecture {lecture_num} is **behind schedule**. "
                f"Planned: '{planned_topic}', Covered: '{topics_covered}'"
            )
            result["catch_up_plan"] = self.generate_catch_up_plan(course_id)

        return result

    def generate_catch_up_plan(self, course_id: str) -> str:
        """Generate an adjusted delivery strategy when behind schedule."""
        full_plan = get_lesson_plan(course_id)
        logs = get_class_logs(course_id)
        last_lec = get_last_completed_lecture(course_id) or 0

        total_planned = len(full_plan)
        completed = len(logs)
        pending = [p for p in full_plan if p["lecture_num"] > last_lec]

        if not pending:
            return "No pending lectures — course is complete."

        lines = []
        for p in pending[:15]:
            lines.append(
                f"  - Lecture {p['lecture_num']}: {p['topic_description']} (CO: {p['target_co']})"
            )
        pending_text = "\n".join(lines)

        user_prompt = f"""The course delivery is behind schedule.

- Total planned lectures: {total_planned}
- Lectures completed: {completed}
- Pending: {len(pending)}

Pending topics:
{pending_text}

Generate a compressed catch-up strategy. Suggest:
1. Topics that can be merged
2. Topics for self-study
3. Adjusted schedule
Format as a clear markdown plan."""

        return generate_text(SYSTEM_PROMPT_OBE_AUDITOR, user_prompt)

    def get_progress_summary(self, course_id: str) -> str:
        """Generate a visual progress summary for the dashboard."""
        full_plan = get_lesson_plan(course_id)
        logs = get_class_logs(course_id)

        total = len(full_plan)
        completed = len(logs)

        if total == 0:
            return "⚠️ No lesson plan found. Please create the course first."

        pct = (completed / total) * 100 if total > 0 else 0
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)

        on_track = sum(1 for l in logs if l.get("completed_on_schedule"))
        behind = completed - on_track

        md = f"## Course Progress\n\n"
        md += f"**Progress:** `[{bar}]` {pct:.0f}% ({completed}/{total} classes)\n\n"
        md += f"| Metric | Value |\n|--------|-------|\n"
        md += f"| On Track | {on_track} |\n"
        md += f"| Behind Schedule | {behind} |\n"
        md += f"| Remaining | {total - completed} |\n\n"

        if logs:
            md += "### Completed Classes\n"
            md += "| # | Topics | Comments | Questions | Status |\n"
            md += "|---|--------|----------|-----------|--------|\n"
            for log in logs:
                status = "✅" if log.get("completed_on_schedule") else "⚠️"
                comments = (log.get("teacher_comments") or "—")[:30]
                questions = (log.get("student_questions") or "—")[:30]
                md += f"| {log['lecture_num']} | {log['topics_covered'][:30]} | {comments} | {questions} | {status} |\n"

        last_lec = get_last_completed_lecture(course_id) or 0
        upcoming = [p for p in full_plan if p["lecture_num"] > last_lec]
        if upcoming:
            md += "\n### Upcoming\n"
            md += "| # | Module | Topic | CO |\n"
            md += "|---|--------|-------|----|\n"
            for p in upcoming[:10]:
                md += f"| {p['lecture_num']} | {p['module_name']} | {p['topic_description']} | {p['target_co']} |\n"
            if len(upcoming) > 10:
                md += f"\n*... and {len(upcoming) - 10} more*\n"

        return md

    def get_next_lecture_info(self, course_id: str) -> Optional[dict]:
        """Get information about the next lecture to be delivered."""
        last_lec = get_last_completed_lecture(course_id) or 0
        next_lec = last_lec + 1
        planned = get_planned_topic(course_id, next_lec)
        if planned is None:
            return None
        return {
            "lecture_num": planned["lecture_num"],
            "module_name": planned["module_name"],
            "topic": planned["topic_description"],
            "co": planned["target_co"],
            "pedagogy": planned["pedagogy"],
        }
