"""
agents/planner_agent.py - Syllabus Parsing & Lesson Planning Agent
Module 1: Extracts topics, maps COs to Bloom's Taxonomy, generates schedule.
"""

import time
from typing import Optional
from schemas import LessonPlan, CourseOutcome
from llm_service import generate_structured, generate_text
from database import save_course, save_course_outcomes, save_lesson_plan
from config import SYSTEM_PROMPT_OBE_AUDITOR, BLOOMS_LEVELS, BLOOMS_VERBS


class PlannerAgent:
    """Agent responsible for syllabus onboarding and lesson plan generation."""

    def __init__(self):
        pass

    def parse_syllabus(
        self,
        syllabus_text: str,
        num_classes: int = 30,
        teacher_instructions: str = "",
    ) -> LessonPlan:
        """Parse raw syllabus text into a structured LessonPlan."""

        instruction_context = ""
        if teacher_instructions:
            instruction_context = f"""

ADDITIONAL TEACHER INSTRUCTIONS (MUST consider these when planning):
{teacher_instructions}
"""

        user_prompt = f"""Analyze the following syllabus and extract structured data.

INSTRUCTIONS:
1. Extract the course_code and course_title.
2. Identify all Course Outcomes (COs). For each CO, provide:
   - co_id: identifier like CO1, CO2, etc.
   - statement: the full outcome statement
   - blooms_level: one of [{', '.join(BLOOMS_LEVELS)}]
   - is_valid: True if the statement contains a clear action verb matching the declared Bloom's level, False otherwise
   - feedback: if invalid, suggest a better verb or rewording
3. Generate a lecture schedule with EXACTLY {num_classes} lectures covering all topics.
   Distribute topics evenly across {num_classes} classes. For each lecture:
   - lecture_num: sequential number from 1 to {num_classes}
   - module_name: which unit/module this belongs to
   - topic_description: specific topic to cover
   - target_co: which CO this lecture supports
   - pedagogy: one of Lecture, Lab, Case Study, Group Discussion
{instruction_context}
VALID BLOOM'S VERBS:
{chr(10).join(f'- {level}: {", ".join(verbs)}' for level, verbs in BLOOMS_VERBS.items())}

SYLLABUS TEXT:
{syllabus_text}"""

        return generate_structured(SYSTEM_PROMPT_OBE_AUDITOR, user_prompt, LessonPlan)

    def validate_co_verbs(self, outcomes: list[CourseOutcome]) -> list[CourseOutcome]:
        """Validate CO action verbs against Bloom's Taxonomy."""
        for outcome in outcomes:
            statement_lower = outcome.statement.lower()
            valid_verbs = BLOOMS_VERBS.get(outcome.blooms_level, [])
            verb_found = any(verb in statement_lower for verb in valid_verbs)

            if verb_found:
                outcome.is_valid = True
                outcome.feedback = None
            else:
                outcome.is_valid = False
                suggested = valid_verbs[0] if valid_verbs else "use an appropriate action verb"
                outcome.feedback = (
                    f"No recognized '{outcome.blooms_level}' verb. "
                    f"Consider: {', '.join(valid_verbs[:3])}."
                )
        return outcomes

    def save_to_database(
        self,
        plan: LessonPlan,
        num_classes: int = 30,
        teacher_instructions: str = "",
        course_materials: str = "",
    ) -> str:
        """Persist the parsed lesson plan to the SQLite database."""
        course_id = f"{plan.course_code}_{int(time.time())}"
        save_course(
            course_id, plan.course_code, plan.course_title,
            num_classes=num_classes,
            teacher_instructions=teacher_instructions,
            course_materials=course_materials,
        )
        save_course_outcomes(course_id, plan.outcomes)
        save_lesson_plan(course_id, plan.schedule)
        return course_id

    def process_syllabus(
        self,
        syllabus_text: str,
        num_classes: int = 30,
        teacher_instructions: str = "",
    ) -> tuple[str, str]:
        """Main entry point: parse, validate, save, and format output."""
        try:
            plan = self.parse_syllabus(syllabus_text, num_classes, teacher_instructions)
            plan.outcomes = self.validate_co_verbs(plan.outcomes)
            course_id = self.save_to_database(
                plan, num_classes, teacher_instructions, syllabus_text
            )

            summary = f"### Course: {plan.course_code} - {plan.course_title}\n"
            summary += f"**Extracted COs:** {len(plan.outcomes)} | "
            summary += f"**Total Classes:** {len(plan.schedule)} | "
            summary += f"**Course ID:** `{course_id}`\n\n"

            summary += "#### Course Outcomes\n"
            summary += "| CO ID | Statement | Bloom's Level | Valid |\n"
            summary += "|-------|-----------|---------------|-------|\n"
            for co in plan.outcomes:
                icon = "✅" if co.is_valid else "❌"
                summary += f"| {co.co_id} | {co.statement[:60]}... | {co.blooms_level} | {icon} |\n"

            summary += "\n#### Lesson Plan Schedule\n"
            summary += "| Class # | Module | Topic | CO | Pedagogy |\n"
            summary += "|---------|--------|-------|-----|----------|\n"
            for item in plan.schedule:
                summary += f"| {item.lecture_num} | {item.module_name} | {item.topic_description} | {item.target_co} | {item.pedagogy} |\n"

            return summary, plan.model_dump_json(indent=2)

        except Exception as e:
            return f"❌ Error processing syllabus: {str(e)}", ""
