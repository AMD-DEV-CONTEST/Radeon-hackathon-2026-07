"""
agents/analytics_agent.py - Student Performance Analytics & Adaptive Exam Agent
Module 3 & 4: Processes scores, classifies students, generates adaptive exams.
Module 6: Student profiling with AI insights.
"""

import io
import pandas as pd
from typing import Optional
from schemas import StudentProfile, AdaptiveExamPaper, Question, ClassInsight
from llm_service import generate_structured, generate_text
from database import (
    save_student_profile,
    save_student_scores,
    get_students_by_cohort,
    get_all_students,
    save_exam_paper,
    get_course_outcomes,
    get_class_logs,
    get_evaluations,
    get_student_scores,
    get_course,
)
from config import COHORT_THRESHOLDS, SYSTEM_PROMPT_EXAM_CONTROLLER, SYSTEM_PROMPT_STUDENT_ADVISOR


class AnalyticsAgent:
    """Agent responsible for student performance analysis, exam generation, and profiling."""

    DIFFICULTY_DISTRIBUTIONS = {
        "Remedial": {"Remember": 35, "Understand": 35, "Apply": 30, "Analyze": 0, "Evaluate": 0, "Create": 0},
        "Average": {"Remember": 15, "Understand": 15, "Apply": 40, "Analyze": 30, "Evaluate": 0, "Create": 0},
        "Advanced": {"Remember": 0, "Understand": 0, "Apply": 20, "Analyze": 50, "Evaluate": 20, "Create": 10},
    }

    def __init__(self):
        pass

    def classify_cohort(self, average_score: float, weak_co_count: int) -> str:
        if weak_co_count >= 3:
            return "Remedial"
        if average_score < COHORT_THRESHOLDS["remedial_max"]:
            return "Remedial"
        if average_score >= COHORT_THRESHOLDS["advanced_min"]:
            return "Advanced"
        return "Average"

    def process_student_scores(self, course_id: str, csv_content: str) -> list[StudentProfile]:
        df = pd.read_csv(io.StringIO(csv_content))
        required = {"student_id", "student_name", "co_id", "score", "max_score"}
        if not required.issubset(set(df.columns)):
            missing = required - set(df.columns)
            raise ValueError(f"CSV missing required columns: {missing}")

        profiles: list[StudentProfile] = []
        grouped = df.groupby("student_id")

        for student_id, group in grouped:
            student_name = group["student_name"].iloc[0]
            co_groups = group.groupby("co_id")
            co_avgs: dict[str, float] = {}
            raw_scores: list[dict] = []

            for co_id, co_df in co_groups:
                total_score = co_df["score"].sum()
                total_max = co_df["max_score"].sum()
                co_pct = (total_score / total_max * 100) if total_max > 0 else 0
                co_avgs[co_id] = co_pct
                for _, row in co_df.iterrows():
                    raw_scores.append({
                        "co_id": co_id, "score": row["score"],
                        "max_score": row["max_score"],
                        "assessment_type": row.get("assessment_type", "unknown"),
                    })

            overall = sum(co_avgs.values()) / len(co_avgs) if co_avgs else 0
            weak_cos = [co for co, avg in co_avgs.items() if avg < 50.0]
            strength_cos = [co for co, avg in co_avgs.items() if avg >= 75.0]
            cohort = self.classify_cohort(overall, len(weak_cos))

            profile = StudentProfile(
                student_id=str(student_id), student_name=str(student_name),
                average_score=round(overall, 2), cohort=cohort,
                weak_cos=weak_cos, strength_cos=strength_cos,
            )
            save_student_profile(profile.model_dump(), course_id)
            save_student_scores(str(student_id), course_id, raw_scores)
            profiles.append(profile)

        return profiles

    def get_cohort_summary(self, course_id: str) -> str:
        students = get_all_students(course_id)
        if not students:
            return "⚠️ No student data found."

        cohorts: dict[str, list] = {"Remedial": [], "Average": [], "Advanced": []}
        for s in students:
            c = s.get("cohort", "Average")
            cohorts.setdefault(c, []).append(s)

        total = len(students)
        scores = [s["average_score"] for s in students]
        mean_score = sum(scores) / len(scores) if scores else 0

        md = "## Student Cohort Analysis\n\n"
        md += f"**Total Students:** {total} | **Mean Score:** {mean_score:.1f}%\n\n"
        md += "| Cohort | Count | % |\n|--------|-------|---|\n"
        for name, members in cohorts.items():
            pct = (len(members) / total * 100) if total > 0 else 0
            md += f"| {name} | {len(members)} | {pct:.0f}% |\n"

        for name, members in cohorts.items():
            if not members:
                continue
            md += f"\n### {name} Cohort ({len(members)})\n"
            md += "| ID | Name | Avg | Weak COs |\n|---|---|---|---|\n"
            for s in members:
                weak = ", ".join(s.get("weak_cos", [])) or "—"
                md += f"| {s['student_id']} | {s['student_name']} | {s['average_score']:.1f}% | {weak} |\n"

        return md

    def generate_class_insight(self, course_id: str) -> str:
        """Generate AI-powered class-level insights and recommendations."""
        course = get_course(course_id)
        students = get_all_students(course_id)
        logs = get_class_logs(course_id)
        evaluations = get_evaluations(course_id)
        outcomes = get_course_outcomes(course_id)

        if not students:
            return "⚠️ No student data available for analysis."

        # Build context
        student_data = []
        for s in students:
            student_data.append(
                f"- {s['student_name']} (ID: {s['student_id']}): "
                f"Avg={s['average_score']:.1f}%, Cohort={s['cohort']}, "
                f"Weak COs={s.get('weak_cos', [])}, Strong COs={s.get('strength_cos', [])}"
            )

        eval_data = []
        for e in evaluations[:10]:
            eval_data.append(
                f"- {e.get('student_name', 'Unknown')}: {e['assessment_type']} "
                f"= {e['percentage']:.1f}% ({e.get('recommended_cohort', 'N/A')}"
            )

        feedback_data = []
        for log in logs[-10:]:
            entry = f"Class {log['lecture_num']}: {log['topics_covered']}"
            if log.get("teacher_comments"):
                entry += f" | Feedback: {log['teacher_comments']}"
            if log.get("student_questions"):
                entry += f" | Questions: {log['student_questions']}"
            feedback_data.append(entry)

        co_text = "\n".join(
            f"- {co['co_id']}: {co['statement']}" for co in outcomes
        )

        user_prompt = f"""Analyze the following class data and provide actionable insights.

Course: {course.get('course_code', '')} - {course.get('course_title', '')}

Course Outcomes:
{co_text}

Student Performance Data:
{chr(10).join(student_data)}

Recent Evaluations:
{chr(10).join(eval_data) if eval_data else 'No evaluations yet.'}

Recent Class Feedback:
{chr(10).join(feedback_data) if feedback_data else 'No class feedback yet.'}

Provide a JSON response with:
- summary: overall class health summary (2-3 sentences)
- top_performers: list of student names doing well
- at_risk_students: list of student names who need intervention
- weak_topics: topics/COs where the class is struggling
- class_focus_areas: what the teacher should focus on in upcoming classes
- recommended_teacher_actions: specific actionable recommendations"""

        try:
            insight = generate_structured(SYSTEM_PROMPT_STUDENT_ADVISOR, user_prompt, ClassInsight)

            md = "## 📊 Class Intelligence Report\n\n"
            md += f"### Summary\n{insight.summary}\n\n"
            md += f"### 🌟 Top Performers\n"
            for name in insight.top_performers:
                md += f"- {name}\n"
            md += f"\n### ⚠️ At-Risk Students\n"
            for name in insight.at_risk_students:
                md += f"- {name}\n"
            md += f"\n### 📚 Weak Topics\n"
            for t in insight.weak_topics:
                md += f"- {t}\n"
            md += f"\n### 🎯 Focus Areas\n"
            for f in insight.class_focus_areas:
                md += f"- {f}\n"
            md += f"\n### 💡 Recommended Actions\n"
            for a in insight.recommended_teacher_actions:
                md += f"- {a}\n"

            return md

        except Exception as e:
            raw = generate_text(SYSTEM_PROMPT_STUDENT_ADVISOR, user_prompt)
            return f"## 📊 Class Intelligence Report\n\n{raw}"

    def generate_adaptive_exam(
        self, course_id: str, cohort_target: str, target_co: str, num_questions: int
    ) -> AdaptiveExamPaper:
        distribution = self.DIFFICULTY_DISTRIBUTIONS.get(cohort_target, self.DIFFICULTY_DISTRIBUTIONS["Average"])
        dist_text = ", ".join(f"{pct}% {level}" for level, pct in distribution.items() if pct > 0)

        outcomes = get_course_outcomes(course_id)
        co_statement = ""
        for co in outcomes:
            if co["co_id"] == target_co:
                co_statement = co.get("statement", "")
                break

        marks_per_question = 10

        user_prompt = f"""Generate an adaptive exam paper:

- Target Cohort: {cohort_target}
- Target CO: {target_co}{f' — "{co_statement}"' if co_statement else ''}
- Number of Questions: {num_questions}
- Marks per Question: {marks_per_question}

COGNITIVE DIFFICULTY DISTRIBUTION:
{dist_text}

REQUIREMENTS:
1. Distribute questions across Bloom's levels per the percentages above.
2. Each question must specify target CO and Bloom's level.
3. Include complete sample answer/marking key.
4. Questions at {cohort_target.lower()} difficulty level.
5. Clear, unambiguous university-level language."""

        paper = generate_structured(SYSTEM_PROMPT_EXAM_CONTROLLER, user_prompt, AdaptiveExamPaper)
        save_exam_paper(course_id, paper.model_dump())
        return paper

    def format_exam_output(self, paper: AdaptiveExamPaper) -> str:
        md = f"# {paper.title}\n"
        md += f"**Target Cohort:** {paper.cohort_target} | **Total Marks:** {paper.total_marks}\n\n---\n"
        for q in paper.questions:
            md += f"### Q{q.question_id} [{q.marks} Marks] (CO: {q.target_co} | Bloom's: {q.blooms_level})\n"
            md += f"{q.question_text}\n\n**Answer Key:**\n{q.sample_answer}\n\n---\n"
        return md
