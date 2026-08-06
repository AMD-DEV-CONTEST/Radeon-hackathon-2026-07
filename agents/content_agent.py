"""
agents/content_agent.py - Content Generation Agent
Generates slides, handouts, and teacher notes for upcoming classes,
incorporating feedback from previous classes.
"""

from llm_service import generate_text
from database import (
    get_course,
    get_course_outcomes,
    get_planned_topic,
    get_class_logs,
    get_last_completed_lecture,
    get_lesson_plan,
    save_generated_content,
)
from config import SYSTEM_PROMPT_CONTENT_CREATOR


class ContentAgent:
    """Generates teaching materials for upcoming lectures."""

    def __init__(self):
        pass

    def _build_context(self, course_id: str, lecture_num: int) -> dict:
        """Gather all context needed for content generation."""
        course = get_course(course_id)
        outcomes = get_course_outcomes(course_id)
        planned = get_planned_topic(course_id, lecture_num)
        all_logs = get_class_logs(course_id)
        recent_logs = all_logs[-5:] if all_logs else []

        # Build feedback summary from recent classes
        feedback_summary = ""
        if recent_logs:
            feedback_parts = []
            for log in recent_logs:
                part = f"Lecture {log['lecture_num']}: {log['topics_covered']}"
                if log.get("teacher_comments"):
                    part += f" | Teacher note: {log['teacher_comments']}"
                if log.get("student_questions"):
                    part += f" | Student questions: {log['student_questions']}"
                if log.get("pace_notes"):
                    part += f" | Pace: {log['pace_notes']}"
                feedback_parts.append(part)
            feedback_summary = "\n".join(feedback_parts)

        # Build CO context
        co_text = "\n".join(
            f"- {co['co_id']}: {co['statement']} (Bloom's: {co['blooms_level']})"
            for co in outcomes
        )

        return {
            "course": course,
            "outcomes": outcomes,
            "co_text": co_text,
            "planned": planned,
            "feedback_summary": feedback_summary,
            "recent_logs": recent_logs,
        }

    def generate_slides(self, course_id: str, lecture_num: int) -> str:
        """Generate lecture slides in markdown format."""
        ctx = self._build_context(course_id, lecture_num)

        if not ctx["planned"]:
            return f"⚠️ No planned topic found for lecture {lecture_num}."

        topic = ctx["planned"]["topic_description"]
        module_name = ctx["planned"]["module_name"]
        target_co = ctx["planned"]["target_co"]
        pedagogy = ctx["planned"]["pedagogy"]
        course = ctx["course"]

        instructions = course.get("teacher_instructions", "") if course else ""

        user_prompt = f"""Generate lecture slides for the following class.

Course: {course.get('course_code', '')} - {course.get('course_title', '')}
Lecture #{lecture_num}: {topic}
Module: {module_name}
Target CO: {target_co}
Pedagogy: {pedagogy}

Course Outcomes:
{ctx['co_text']}

Teacher Instructions: {instructions or 'None specified'}

Feedback from previous classes (use this to improve the content):
{ctx['feedback_summary'] or 'No previous class feedback available.'}

FORMAT REQUIREMENTS — CRITICAL:
- Start with a single # heading: the lecture title
- Use ## for each slide title (each ## becomes one slide)
- Under each ##, write the slide content as bullet points, short paragraphs, or tables
- Keep each slide focused — 4-6 bullet points max per slide
- Use ### sparingly for sub-sections within a slide
- Include one ## slide for "Learning Objectives" near the start
- Include one ## slide for "Summary" or "Key Takeaways" at the end
- Optionally include a ## "Discussion Questions" or "Activity" slide
- Target 8-12 slides total (including title, objectives, content, and summary)
- Use bold for key terms, bullet lists for points
- If feedback mentions pace issues, adjust content depth accordingly"""

        slides_md = generate_text(SYSTEM_PROMPT_CONTENT_CREATOR, user_prompt)

        # Save to DB
        title = f"Lecture {lecture_num} Slides: {topic}"
        save_generated_content(course_id, "slides", title, slides_md, lecture_num)

        return slides_md

    def generate_handout(self, course_id: str, lecture_num: int) -> str:
        """Generate a student handout for the lecture."""
        ctx = self._build_context(course_id, lecture_num)

        if not ctx["planned"]:
            return f"⚠️ No planned topic found for lecture {lecture_num}."

        topic = ctx["planned"]["topic_description"]
        target_co = ctx["planned"]["target_co"]
        course = ctx["course"]

        user_prompt = f"""Generate a student handout for the following lecture:

Course: {course.get('course_code', '')} - {course.get('course_title', '')}
Lecture #{lecture_num}: {topic}
Target CO: {target_co}

Previous class feedback:
{ctx['feedback_summary'] or 'No previous feedback.'}

FORMAT:
- Title with course code and lecture number
- Key concepts with clear definitions
- Worked examples or diagrams (described in text)
- Practice exercises (3-5 questions with varying difficulty)
- Space for student notes
- References to textbook sections if applicable
- Keep language accessible and student-friendly"""

        handout_md = generate_text(SYSTEM_PROMPT_CONTENT_CREATOR, user_prompt)

        title = f"Lecture {lecture_num} Handout: {topic}"
        save_generated_content(course_id, "handout", title, handout_md, lecture_num)

        return handout_md

    def generate_teacher_notes(self, course_id: str, lecture_num: int) -> str:
        """Generate teacher notes for the lecture."""
        ctx = self._build_context(course_id, lecture_num)

        if not ctx["planned"]:
            return f"⚠️ No planned topic found for lecture {lecture_num}."

        topic = ctx["planned"]["topic_description"]
        pedagogy = ctx["planned"]["pedagogy"]
        target_co = ctx["planned"]["target_co"]
        course = ctx["course"]

        user_prompt = f"""Generate detailed teacher notes for the following lecture:

Course: {course.get('course_code', '')} - {course.get('course_title', '')}
Lecture #{lecture_num}: {topic}
Target CO: {target_co}
Pedagogy: {pedagogy}

Previous class feedback (CRITICAL — address these issues):
{ctx['feedback_summary'] or 'No previous feedback.'}

FORMAT:
- Pre-class preparation checklist
- Lesson flow with time allocations (for a typical 50-60 min class)
- Key talking points and explanations
- Common student misconceptions to address
- Engagement strategies (questions to ask, activities)
- How this topic connects to previous lectures
- Assessment check: quick formative assessment idea
- Notes on pace adjustments based on previous feedback
- Homework/reading assignment suggestion"""

        notes_md = generate_text(SYSTEM_PROMPT_CONTENT_CREATOR, user_prompt)

        title = f"Lecture {lecture_num} Teacher Notes: {topic}"
        save_generated_content(course_id, "teacher_notes", title, notes_md, lecture_num)

        return notes_md

    def reprompt_content(self, existing_content: str, instruction: str,
                         course_id: str = "", lecture_num: int = 0) -> str:
        """Re-generate or revise existing content based on user instructions."""
        user_prompt = f"""You previously generated the following educational content:

---EXISTING CONTENT---
{existing_content}
---END EXISTING CONTENT---

The teacher wants you to revise this content with the following instruction:
"{instruction}"

Return the FULL revised content in the same format as the original. Do not add meta-commentary.
Keep the same overall structure unless the instruction asks to change it."""

        return generate_text(SYSTEM_PROMPT_CONTENT_CREATOR, user_prompt)
