"""
webapp.py - Flask Web Application for EduCopilot
Professional dashboard with server-side rendering.
"""

import os
import markdown
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
)
from slides_converter import markdown_to_slide_html, generate_slides_pdf, replace_latex_symbols
from database import (
    init_database, get_all_courses, get_course, delete_course,
    get_course_outcomes, get_lesson_plan, get_class_logs,
    get_planned_topic, update_lesson_plan_topic,
    get_evaluations, get_all_students,
    get_generated_content, get_generated_content_by_id,
    update_generated_content, delete_generated_content,
    log_class_progress, get_exam_papers, get_nba_reports,
)
from agents import (
    PlannerAgent, TrackingAgent, AnalyticsAgent,
    NBAAgent, ContentAgent, EvalAgent,
)
from llm_service import check_connection
from config import SERVER_PORT

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())

# Initialize agents
planner = PlannerAgent()
tracker = TrackingAgent()
analytics = AnalyticsAgent()
nba_agent = NBAAgent()
content_agent = ContentAgent()
eval_agent = EvalAgent()


def md_to_html(text: str) -> str:
    """Convert markdown to HTML, replacing LaTeX symbols with Unicode."""
    if not text:
        return ""
    text = replace_latex_symbols(text)
    return markdown.markdown(text, extensions=["tables", "fenced_code"])


# ── Startup ────────────────────────────────────────────────────────

init_database()
_ollama_status = None  # cached

def _check_ollama():
    global _ollama_status
    if _ollama_status is None:
        _ollama_status = check_connection()
    return _ollama_status


# ── Dashboard ──────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    courses = get_all_courses()
    ollama_ok = _check_ollama()
    return render_template("dashboard.html", courses=courses, ollama_ok=ollama_ok)


# ── Add Course ─────────────────────────────────────────────────────

@app.route("/add", methods=["GET", "POST"])
def add_course():
    if request.method == "POST":
        syllabus = request.form.get("syllabus", "").strip()
        num_classes = int(request.form.get("num_classes", 30))
        instructions = request.form.get("instructions", "").strip()

        if not syllabus:
            flash("Please paste syllabus / course materials.", "warning")
            return render_template("add_course.html")

        try:
            summary_md, json_raw = planner.process_syllabus(
                syllabus, num_classes, instructions
            )
            flash("Course created successfully!", "success")
            return render_template(
                "add_course_result.html",
                summary_html=md_to_html(summary_md),
                json_raw=json_raw,
            )
        except Exception as e:
            flash(f"Error creating course: {e}", "danger")
            return render_template("add_course.html")

    return render_template("add_course.html")


# ── Course Detail ──────────────────────────────────────────────────

@app.route("/course/<course_id>")
def course_detail(course_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    outcomes = get_course_outcomes(course_id)
    plan = get_lesson_plan(course_id)
    logs = get_class_logs(course_id)
    last_lec = 0
    if logs:
        last_lec = max(l["lecture_num"] for l in logs)

    total = len(plan)
    completed = len(logs)
    pct = (completed / total * 100) if total > 0 else 0
    on_track = sum(1 for l in logs if l.get("completed_on_schedule"))

    # Build log lookup for template
    log_map = {l["lecture_num"]: l for l in logs}

    return render_template(
        "course_detail.html",
        course=course,
        outcomes=outcomes,
        plan=plan,
        logs=logs,
        log_map=log_map,
        last_lec=last_lec,
        total=total,
        completed=completed,
        pct=round(pct, 1),
        on_track=on_track,
    )


# ── Delete Course ──────────────────────────────────────────────────

@app.route("/course/<course_id>/delete", methods=["POST"])
def delete_course_route(course_id):
    delete_course(course_id)
    flash("Course deleted.", "info")
    return redirect(url_for("dashboard"))


# ── Log Class ──────────────────────────────────────────────────────

@app.route("/course/<course_id>/log", methods=["GET", "POST"])
def log_class(course_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    plan = get_lesson_plan(course_id)
    logs = get_class_logs(course_id)
    last_lec = max((l["lecture_num"] for l in logs), default=0)

    if request.method == "POST":
        lecture_num = int(request.form.get("lecture_num", last_lec + 1))
        topics = request.form.get("topics", "").strip()
        comments = request.form.get("comments", "").strip()
        questions = request.form.get("questions", "").strip()
        pace = request.form.get("pace", "").strip()

        if not topics:
            flash("Please enter the topics covered.", "warning")
            return redirect(url_for("log_class", course_id=course_id))

        try:
            result = tracker.log_progress(
                course_id, lecture_num, topics,
                teacher_comments=comments,
                student_questions=questions,
                pace_notes=pace,
            )
            flash(result.get("message", "Class logged."), "success")
            if result.get("catch_up_plan"):
                flash(f"Catch-up plan generated — view in Progress tab.", "warning")
        except Exception as e:
            flash(f"Error logging class: {e}", "danger")

        return redirect(url_for("course_detail", course_id=course_id))

    return render_template(
        "log_class.html", course=course, plan=plan,
        last_lec=last_lec, next_lec=last_lec + 1,
    )


# ── Generate Content ───────────────────────────────────────────────

@app.route("/course/<course_id>/content", methods=["GET", "POST"])
def generate_content(course_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    plan = get_lesson_plan(course_id)
    logs = get_class_logs(course_id)
    log_map = {l["lecture_num"]: l for l in logs}
    generated = None
    viewing = None
    editing = False

    # Current class number for navigation
    class_num = request.args.get("class_num", type=int)
    view_id = request.args.get("view_id", type=int)

    if view_id:
        saved = get_generated_content_by_id(view_id)
        if saved and saved.get("course_id") == course_id:
            viewing = saved
            class_num = saved.get("lecture_num", 1)

    if class_num is None:
        class_num = 1

    # Check if editing mode
    if request.args.get("edit") == "1" and viewing:
        editing = True

    # Handle POST: generate new content
    if request.method == "POST" and not editing:
        lecture_num = int(request.form.get("lecture_num", class_num))
        content_type = request.form.get("content_type", "slides")

        try:
            if content_type == "slides":
                generated = content_agent.generate_slides(course_id, lecture_num)
            elif content_type == "handout":
                generated = content_agent.generate_handout(course_id, lecture_num)
            elif content_type == "teacher_notes":
                generated = content_agent.generate_teacher_notes(course_id, lecture_num)
            class_num = lecture_num
        except Exception as e:
            flash(f"Error generating content: {e}", "danger")

    history = get_generated_content(course_id)
    total_classes = len(plan)

    return render_template(
        "content.html", course=course, plan=plan,
        generated=generated, history=history, viewing=viewing,
        class_num=class_num, total_classes=total_classes,
        log_map=log_map, editing=editing,
    )


# ── Save Edited Content ───────────────────────────────────────────

@app.route("/course/<course_id>/content/<int:content_id>/edit", methods=["POST"])
def save_edited_content(course_id, content_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    saved = get_generated_content_by_id(content_id)
    if not saved or saved.get("course_id") != course_id:
        flash("Content not found.", "danger")
        return redirect(url_for("generate_content", course_id=course_id))

    new_content = request.form.get("edited_content", "").strip()
    if new_content:
        update_generated_content(content_id, new_content)
        flash("Content updated!", "success")
    else:
        flash("Content cannot be empty.", "warning")

    return redirect(url_for("generate_content", course_id=course_id, view_id=content_id))


# ── Reprompt AI ────────────────────────────────────────────────────

@app.route("/course/<course_id>/content/<int:content_id>/reprompt", methods=["POST"])
def reprompt_content(course_id, content_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    saved = get_generated_content_by_id(content_id)
    if not saved or saved.get("course_id") != course_id:
        flash("Content not found.", "danger")
        return redirect(url_for("generate_content", course_id=course_id))

    instruction = request.form.get("instruction", "").strip()
    if not instruction:
        flash("Please enter revision instructions.", "warning")
        return redirect(url_for("generate_content", course_id=course_id, view_id=content_id))

    try:
        revised = content_agent.reprompt_content(
            saved["markdown_content"], instruction, course_id, saved.get("lecture_num", 0)
        )
        update_generated_content(content_id, revised)
        flash("Content revised by AI!", "success")
    except Exception as e:
        flash(f"Error revising content: {e}", "danger")

    return redirect(url_for("generate_content", course_id=course_id, view_id=content_id))


# ── Delete Content ─────────────────────────────────────────────────

@app.route("/course/<course_id>/content/<int:content_id>/delete", methods=["POST"])
def delete_content(course_id, content_id):
    delete_generated_content(content_id)
    flash("Content deleted.", "info")
    return redirect(url_for("generate_content", course_id=course_id))


# ── Toggle Class Taken ─────────────────────────────────────────────

@app.route("/course/<course_id>/class/<int:lecture_num>/toggle", methods=["POST"])
def toggle_class_taken(course_id, lecture_num):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    planned = get_planned_topic(course_id, lecture_num)
    topic = planned["topic_description"] if planned else f"Class {lecture_num}"

    # Check if already logged
    existing_logs = get_class_logs(course_id)
    existing = [l for l in existing_logs if l["lecture_num"] == lecture_num]

    if existing:
        flash(f"Class #{lecture_num} is already logged.", "info")
    else:
        try:
            log_class_progress(
                course_id, lecture_num, topic,
                completed_on_schedule=True,
                teacher_comments="Marked as taken from content page.",
            )
            flash(f"Class #{lecture_num} marked as taken!", "success")
        except Exception as e:
            flash(f"Error: {e}", "danger")

    return redirect(url_for("generate_content", course_id=course_id, class_num=lecture_num))


# ── Edit Topic ─────────────────────────────────────────────────────

@app.route("/course/<course_id>/class/<int:lecture_num>/edit-topic", methods=["POST"])
def edit_topic(course_id, lecture_num):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    topic = request.form.get("topic_description", "").strip()
    module = request.form.get("module_name", "").strip()

    if not topic:
        flash("Topic cannot be empty.", "warning")
        return redirect(url_for("generate_content", course_id=course_id, class_num=lecture_num))

    try:
        update_lesson_plan_topic(
            course_id, lecture_num, topic,
            module_name=module if module else None,
        )
        flash(f"Topic for Class #{lecture_num} updated!", "success")
    except Exception as e:
        flash(f"Error updating topic: {e}", "danger")

    return redirect(url_for("generate_content", course_id=course_id, class_num=lecture_num))


# ── Slides PDF Download ───────────────────────────────────────────

@app.route("/course/<course_id>/slides/<int:content_id>/pdf")
def download_slides_pdf(course_id, content_id):
    """Generate and download a PDF for saved slides content."""
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    saved = get_generated_content_by_id(content_id)
    if not saved or saved.get("course_id") != course_id:
        flash("Content not found.", "danger")
        return redirect(url_for("generate_content", course_id=course_id))

    try:
        pdf_path = generate_slides_pdf(
            md_content=saved["markdown_content"],
            course_code=course.get("course_code", ""),
            course_title=course.get("course_title", ""),
            lecture_num=saved.get("lecture_num", 0),
            topic=saved.get("title", ""),
        )
        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=os.path.basename(pdf_path),
        )
    except Exception as e:
        flash(f"Error generating PDF: {e}", "danger")
        return redirect(url_for("generate_content", course_id=course_id, view_id=content_id))


# ── Evaluate ───────────────────────────────────────────────────────

@app.route("/course/<course_id>/evaluate", methods=["GET", "POST"])
def evaluate(course_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    plan = get_lesson_plan(course_id)
    evaluations = get_evaluations(course_id)
    result = None

    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        student_name = request.form.get("student_name", "").strip()
        assessment_type = request.form.get("assessment_type", "assignment")
        max_marks = float(request.form.get("max_marks", 100))
        answers = request.form.get("answers", "").strip()
        lecture_num = request.form.get("lecture_num", "").strip()
        ln = int(lecture_num) if lecture_num else None

        if not answers:
            flash("Please paste the student's answers.", "warning")
            return redirect(url_for("evaluate", course_id=course_id))

        try:
            result = eval_agent.evaluate_text_answers(
                course_id, student_id or "unknown", student_name or "unknown",
                assessment_type, answers, max_marks, ln,
            )
            flash("Evaluation complete!", "success")
        except Exception as e:
            flash(f"Error evaluating: {e}", "danger")

    return render_template(
        "evaluate.html", course=course, plan=plan,
        evaluations=evaluations, result=result,
    )


# ── Student Profiling ──────────────────────────────────────────────

@app.route("/course/<course_id>/profiling", methods=["GET", "POST"])
def profiling(course_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    students = get_all_students(course_id)
    cohort_html = None
    insight_html = None

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "upload_csv":
            csv_file = request.files.get("csv_file")
            if csv_file and csv_file.filename:
                try:
                    csv_content = csv_file.read().decode("utf-8")
                    analytics.process_student_scores(course_id, csv_content)
                    students = get_all_students(course_id)
                    flash("Student scores imported!", "success")
                except Exception as e:
                    flash(f"Error importing CSV: {e}", "danger")

        elif action == "cohort_summary":
            try:
                summary_md = analytics.get_cohort_summary(course_id)
                cohort_html = md_to_html(summary_md)
            except Exception as e:
                flash(f"Error: {e}", "danger")

        elif action == "class_insight":
            try:
                insight_md = analytics.generate_class_insight(course_id)
                insight_html = md_to_html(insight_md)
            except Exception as e:
                flash(f"Error: {e}", "danger")

    return render_template(
        "profiling.html", course=course,
        students=students, cohort_html=cohort_html, insight_html=insight_html,
    )


# ── Exam Generator ─────────────────────────────────────────────────

@app.route("/course/<course_id>/exams", methods=["GET", "POST"])
def exams(course_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    outcomes = get_course_outcomes(course_id)
    papers = get_exam_papers(course_id)
    exam_html = None

    if request.method == "POST":
        cohort = request.form.get("cohort", "Remedial")
        target_co = request.form.get("target_co", "CO1")
        num_questions = int(request.form.get("num_questions", 5))

        try:
            paper = analytics.generate_adaptive_exam(
                course_id, cohort, target_co, num_questions
            )
            exam_md = analytics.format_exam_output(paper)
            exam_html = md_to_html(exam_md)
            flash("Exam generated!", "success")
        except Exception as e:
            flash(f"Error generating exam: {e}", "danger")

    return render_template(
        "exams.html", course=course, outcomes=outcomes,
        papers=papers, exam_html=exam_html,
    )


# ── Accreditation ──────────────────────────────────────────────────

@app.route("/course/<course_id>/accreditation", methods=["GET", "POST"])
def accreditation(course_id):
    course = get_course(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    report_html = None

    if request.method == "POST":
        try:
            report_md = nba_agent.compile_course_file(course_id)
            report_html = md_to_html(report_md)
            flash("Accreditation report compiled!", "success")
        except Exception as e:
            flash(f"Error: {e}", "danger")

    reports = get_nba_reports(course_id)

    return render_template(
        "accreditation.html", course=course,
        report_html=report_html, reports=reports,
    )


# ── Run ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_database()
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=os.getenv("FLASK_DEBUG", "0") == "1")
