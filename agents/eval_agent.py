"""
agents/eval_agent.py - Assignment & Quiz Evaluation Agent
Evaluates scanned/photographed assignments and quizzes,
assigns marks, and saves results to student profiles.
"""

import os
from llm_service import generate_text
from database import (
    get_course_outcomes,
    get_planned_topic,
    get_lesson_plan,
    save_evaluation,
    save_student_scores,
    save_student_profile,
)
from config import SYSTEM_PROMPT_EVALUATOR, COHORT_THRESHOLDS


class EvalAgent:
    """Evaluates assignments/quizzes from uploaded images."""

    def __init__(self):
        pass

    def evaluate_assignment(
        self,
        course_id: str,
        image_path: str,
        assessment_type: str,
        max_marks: float,
        lecture_num: int = None,
        rubric: str = "",
    ) -> dict:
        """
        Evaluate a scanned assignment/quiz image.
        
        Since local LLMs may not support vision, we use a text-based approach:
        - The teacher is prompted to paste or describe the student's answers
        - The LLM evaluates against COs and rubrics
        
        For true image support, a vision model or OCR pipeline would be needed.
        """
        outcomes = get_course_outcomes(course_id)
        co_text = "\n".join(
            f"- {co['co_id']}: {co['statement']} (Bloom's: {co['blooms_level']})"
            for co in outcomes
        )

        # Get topic context if lecture_num provided
        topic_context = ""
        if lecture_num:
            planned = get_planned_topic(course_id, lecture_num)
            if planned:
                topic_context = f"\nTopic: {planned['topic_description']} (CO: {planned['target_co']})"

        user_prompt = f"""Evaluate the following student assignment/quiz.

Assessment Type: {assessment_type}
Maximum Marks: {max_marks}{topic_context}

Course Outcomes:
{co_text}

{f'Rubric: {rubric}' if rubric else 'No specific rubric provided. Use standard university marking criteria.'}

The assignment image is at: {image_path}
Note: Since we cannot directly view the image, please describe or paste the student's 
answers below. In a production system, this would use OCR or a vision model.

For now, return the evaluation as JSON with these fields:
- student_id: "unknown" if not identifiable
- student_name: "unknown" if not identifiable  
- assessment_type: "{assessment_type}"
- total_marks_awarded: number
- total_marks_possible: {max_marks}
- percentage: calculated percentage
- questions: array of {{question_num, student_answer_summary, marks_awarded, marks_possible, feedback, co_id}}
- overall_feedback: comprehensive feedback string
- recommended_cohort: "Remedial", "Average", or "Advanced" based on performance

Since we cannot process the image directly, provide a sample evaluation structure
that demonstrates the expected output format. The actual evaluation will happen
when the teacher provides the student's answers as text."""

        result_text = generate_text(SYSTEM_PROMPT_EVALUATOR, user_prompt)

        # Build evaluation result dict
        eval_data = {
            "student_id": "pending",
            "student_name": "pending",
            "assessment_type": assessment_type,
            "image_path": image_path,
            "total_marks_awarded": 0,
            "total_marks_possible": max_marks,
            "percentage": 0,
            "questions": [],
            "overall_feedback": result_text,
            "recommended_cohort": "Average",
        }

        return eval_data

    def evaluate_text_answers(
        self,
        course_id: str,
        student_id: str,
        student_name: str,
        assessment_type: str,
        answers_text: str,
        max_marks: float,
        lecture_num: int = None,
        rubric: str = "",
    ) -> dict:
        """
        Evaluate student answers provided as text.
        This is the primary evaluation method when OCR is not available.
        """
        outcomes = get_course_outcomes(course_id)
        co_text = "\n".join(
            f"- {co['co_id']}: {co['statement']} (Bloom's: {co['blooms_level']})"
            for co in outcomes
        )

        topic_context = ""
        if lecture_num:
            planned = get_planned_topic(course_id, lecture_num)
            if planned:
                topic_context = f"\nTopic: {planned['topic_description']} (CO: {planned['target_co']})"

        user_prompt = f"""Evaluate the following student's answers for a {assessment_type}.

Student: {student_name} (ID: {student_id})
Maximum Total Marks: {max_marks}{topic_context}

Course Outcomes:
{co_text}

{f'Rubric: {rubric}' if rubric else 'Use standard university marking criteria. Award partial marks where appropriate.'}

STUDENT'S ANSWERS:
{answers_text}

EVALUATION INSTRUCTIONS:
1. Read each answer carefully
2. Award marks proportionally to correctness and completeness
3. Map each question to the most relevant Course Outcome
4. Provide specific feedback for each question
5. Give overall feedback with strengths and areas for improvement
6. Based on the percentage, recommend a cohort:
   - Below {COHORT_THRESHOLDS['remedial_max']}% → Remedial
   - {COHORT_THRESHOLDS['average_min']}% - {COHORT_THRESHOLDS['average_max']}% → Average
   - Above {COHORT_THRESHOLDS['advanced_min']}% → Advanced

Return as JSON with these exact fields:
- student_id: "{student_id}"
- student_name: "{student_name}"
- assessment_type: "{assessment_type}"
- total_marks_awarded: number
- total_marks_possible: {max_marks}
- percentage: number (0-100)
- questions: array of objects, each with: question_num (int), student_answer_summary (str), marks_awarded (float), marks_possible (float), feedback (str), co_id (str)
- overall_feedback: str
- recommended_cohort: str"""

        from llm_service import generate_structured
        from schemas import EvaluationResult

        try:
            result = generate_structured(SYSTEM_PROMPT_EVALUATOR, user_prompt, EvaluationResult)
            eval_data = result.model_dump()
            eval_data["image_path"] = None

            # Save evaluation
            save_evaluation(course_id, eval_data)

            # Save individual scores per CO
            if eval_data.get("student_id") and eval_data["student_id"] != "pending":
                scores = []
                for q in eval_data.get("questions", []):
                    scores.append({
                        "co_id": q.get("co_id", "CO1"),
                        "score": q.get("marks_awarded", 0),
                        "max_score": q.get("marks_possible", 0),
                        "assessment_type": assessment_type,
                    })
                if scores:
                    save_student_scores(eval_data["student_id"], course_id, scores)

            return eval_data

        except Exception as e:
            # Fallback: return raw text evaluation
            raw = generate_text(SYSTEM_PROMPT_EVALUATOR, user_prompt)
            eval_data = {
                "student_id": student_id,
                "student_name": student_name,
                "assessment_type": assessment_type,
                "image_path": None,
                "total_marks_awarded": 0,
                "total_marks_possible": max_marks,
                "percentage": 0,
                "questions": [],
                "overall_feedback": f"Evaluation completed but structured parsing failed.\n\nRaw evaluation:\n{raw}",
                "recommended_cohort": "Average",
            }
            save_evaluation(course_id, eval_data)
            return eval_data
