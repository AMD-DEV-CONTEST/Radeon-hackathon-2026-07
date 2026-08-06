"""
app.py - Gradio Dashboard Application for EduCopilot
Main entry point for the Virtual TA & Accreditation Engine.
"""

import gradio as gr
from agents import PlannerAgent, TrackingAgent, AnalyticsAgent, NBAAgent, ContentAgent, EvalAgent
from database import init_database, get_all_courses, get_course, delete_course
from llm_service import check_connection
from config import GRADIO_SERVER_PORT

# Initialize agents
planner = PlannerAgent()
tracker = TrackingAgent()
analytics = AnalyticsAgent()
nba_agent = NBAAgent()
content_agent = ContentAgent()
eval_agent = EvalAgent()


# ═══════════════════════════════════════════════════════════════════
#  Helper: Course Cards HTML
# ═══════════════════════════════════════════════════════════════════

def _course_cards_html() -> str:
    """Render all courses as HTML cards for the dashboard."""
    courses = get_all_courses()
    if not courses:
        return (
            "<div style='text-align:center;padding:40px;color:#888;'>"
            "<h3>No courses yet</h3>"
            "<p>Click <b>+ Add New Course</b> to get started.</p></div>"
        )

    html = "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;padding:8px;'>"
    for c in courses:
        cid = c["course_id"]
        code = c.get("course_code", "N/A")
        title = c.get("course_title", "Untitled")
        num = c.get("num_classes", 30)
        created = c.get("created_at", "")[:10]
        html += f"""
        <div style="border:1px solid #ddd;border-radius:12px;padding:20px;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.06);cursor:pointer;">
            <div style="font-size:13px;color:#888;margin-bottom:4px;">{code}</div>
            <div style="font-size:18px;font-weight:600;margin-bottom:8px;">{title}</div>
            <div style="font-size:13px;color:#555;">📅 {num} classes &nbsp;|&nbsp; 🕐 Created {created}</div>
            <div style="margin-top:12px;font-size:12px;color:#aaa;">ID: {cid}</div>
        </div>"""
    html += "</div>"
    return html


# ═══════════════════════════════════════════════════════════════════
#  Callbacks
# ═══════════════════════════════════════════════════════════════════

def on_app_load() -> str:
    init_database()
    if check_connection():
        return "✅ System Ready — Connected to Ollama"
    return "⚠️ Cannot connect to Ollama at http://localhost:11434. LLM features will not work."


def refresh_dashboard() -> str:
    return _course_cards_html()


def add_course(
    syllabus_text: str,
    num_classes: float,
    teacher_instructions: str,
) -> tuple[str, str]:
    """Process the add-course form."""
    if not syllabus_text or not syllabus_text.strip():
        return "⚠️ Please paste syllabus/COs/materials.", _course_cards_html()
    nc = int(num_classes) if num_classes else 30
    summary, json_raw = planner.process_syllabus(syllabus_text, nc, teacher_instructions)
    return summary, _course_cards_html()


def load_course_detail(course_id: str) -> tuple:
    """Load all data for a selected course."""
    if not course_id or not course_id.strip():
        return ("⚠️ Enter a Course ID", "", "", "", "", "", "", "")
    cid = course_id.strip()
    course = get_course(cid)
    if not course:
        return (f"⚠️ Course '{cid}' not found", "", "", "", "", "", "", "")

    header = f"## {course.get('course_code', '')} — {course.get('course_title', '')}\n"
    header += f"*{course.get('num_classes', 30)} classes | ID: `{cid}`*"
    progress = tracker.get_progress_summary(cid)
    return (header, progress, "", "", "", "", "", "")


def log_class(
    course_id: str, lecture_num: float, topics: str,
    comments: str, questions: str, pace: str,
) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    result = tracker.log_progress(
        course_id.strip(), int(lecture_num) or 1, topics.strip(),
        teacher_comments=comments.strip(), student_questions=questions.strip(),
        pace_notes=pace.strip(),
    )
    md = result["message"] + "\n\n"
    if result.get("planned_topic"):
        md += f"**Planned:** {result['planned_topic']}\n"
    if result.get("catch_up_plan"):
        md += f"\n---\n### Catch-Up Plan\n{result['catch_up_plan']}\n"
    return md


def gen_slides(course_id: str, lecture_num: float) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    try:
        return content_agent.generate_slides(course_id.strip(), int(lecture_num) or 1)
    except Exception as e:
        return f"❌ Error: {e}"


def gen_handout(course_id: str, lecture_num: float) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    try:
        return content_agent.generate_handout(course_id.strip(), int(lecture_num) or 1)
    except Exception as e:
        return f"❌ Error: {e}"


def gen_teacher_notes(course_id: str, lecture_num: float) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    try:
        return content_agent.generate_teacher_notes(course_id.strip(), int(lecture_num) or 1)
    except Exception as e:
        return f"❌ Error: {e}"


def eval_text(
    course_id: str, student_id: str, student_name: str,
    assessment_type: str, answers: str, max_marks: float,
    lecture_num: float,
) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    if not answers.strip():
        return "⚠️ Paste the student's answers"
    try:
        result = eval_agent.evaluate_text_answers(
            course_id.strip(), student_id.strip() or "unknown",
            student_name.strip() or "unknown", assessment_type.strip(),
            answers.strip(), max_marks or 100, int(lecture_num) if lecture_num else None,
        )
        md = f"## Evaluation Result\n\n"
        md += f"**Student:** {result.get('student_name', 'Unknown')} ({result.get('student_id', '')})\n"
        md += f"**Score:** {result['total_marks_awarded']}/{result['total_marks_possible']} "
        md += f"({result['percentage']:.1f}%)\n"
        md += f"**Recommended Cohort:** {result['recommended_cohort']}\n\n"
        md += f"### Feedback\n{result['overall_feedback']}\n"
        if result.get("questions"):
            md += "\n### Per-Question Breakdown\n"
            md += "| Q# | Marks | CO | Feedback |\n|---|---|---|---|\n"
            for q in result["questions"]:
                md += f"| {q['question_num']} | {q['marks_awarded']}/{q['marks_possible']} | {q.get('co_id', '')} | {q['feedback'][:50]} |\n"
        return md
    except Exception as e:
        return f"❌ Error: {e}"


def view_cohort(course_id: str) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    return analytics.get_cohort_summary(course_id.strip())


def gen_class_insight(course_id: str) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    try:
        return analytics.generate_class_insight(course_id.strip())
    except Exception as e:
        return f"❌ Error: {e}"


def gen_exam(course_id: str, cohort: str, target_co: str, num_q: float) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    try:
        label = cohort.split("(")[0].strip() if "(" in cohort else cohort.strip()
        paper = analytics.generate_adaptive_exam(
            course_id.strip(), label, target_co.strip(), int(num_q) or 3
        )
        return analytics.format_exam_output(paper)
    except Exception as e:
        return f"❌ Error: {e}"


def gen_nba(course_id: str) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    try:
        return nba_agent.compile_course_file(course_id.strip())
    except Exception as e:
        return f"❌ Error: {e}"


def do_delete_course(course_id: str) -> str:
    if not course_id.strip():
        return "⚠️ Enter a Course ID"
    delete_course(course_id.strip())
    return _course_cards_html()


# ═══════════════════════════════════════════════════════════════════
#  UI Layout
# ═══════════════════════════════════════════════════════════════════

def create_ui() -> gr.Blocks:

    with gr.Blocks(title="EduCopilot Dashboard") as demo:

        # ── Header ─────────────────────────────────────────────────
        gr.Markdown("# 🎓 EduCopilot — Autonomous Virtual TA")
        status_bar = gr.Markdown(on_app_load())

        # ── Page Router State ──────────────────────────────────────
        current_course = gr.State("")

        # ── Dashboard View ─────────────────────────────────────────
        with gr.Column(visible=True) as dashboard_view:
            with gr.Row():
                gr.Markdown("## 📚 My Courses")
                btn_add_new = gr.Button("+ Add New Course", variant="primary", scale=0)

            course_cards = gr.HTML(_course_cards_html())

            with gr.Row():
                course_id_input = gr.Textbox(
                    label="Course ID", placeholder="Paste a Course ID to open it...",
                    scale=3,
                )
                btn_open = gr.Button("📂 Open Course", scale=0)

        # ── Add Course View ────────────────────────────────────────
        with gr.Column(visible=False) as add_course_view:
            gr.Markdown("## ➕ Add New Course")
            btn_back_add = gr.Button("← Back to Dashboard")

            syllabus_input = gr.Textbox(
                lines=14, label="Syllabus / COs / Course Materials",
                placeholder="Paste everything here: syllabus text, course outcomes, topics, "
                            "reference materials, textbook chapters...\n\n"
                            "Example:\nCourse Code: CS301\nCourse Title: Data Structures\n"
                            "CO1: Students will be able to analyze time complexity of sorting algorithms.\n"
                            "Unit 1: Arrays and Linked Lists (8 classes)\nUnit 2: Trees (10 classes)\n...",
            )
            with gr.Row():
                num_classes = gr.Number(label="Total Number of Classes", value=30, minimum=1, precision=0)
            teacher_instructions = gr.Textbox(
                lines=4, label="Instructions / Notes",
                placeholder="E.g., 3 continuous assessments, medium difficulty, "
                            "mostly first-year students with basic programming knowledge, "
                            "focus more on practical labs than theory...",
            )
            btn_create = gr.Button("🚀 Create Course Plan", variant="primary")
            create_result = gr.Markdown()
            create_json = gr.Code(language="json", label="Raw JSON", visible=False)

            btn_create.click(
                fn=add_course,
                inputs=[syllabus_input, num_classes, teacher_instructions],
                outputs=[create_result, course_cards],
            )

        # ── Course Detail View ─────────────────────────────────────
        with gr.Column(visible=False) as course_detail_view:
            btn_back_detail = gr.Button("← Back to Dashboard")
            course_header = gr.Markdown()
            course_id_display = gr.Textbox(label="Course ID", interactive=False)

            with gr.Tabs():
                # Tab: Progress & Log
                with gr.Tab("📊 Progress & Log Class"):
                    progress_md = gr.Markdown()

                    gr.Markdown("### 📝 Log a Class")
                    with gr.Row():
                        lec_num = gr.Number(label="Class #", value=1, minimum=1, precision=0)
                        topics = gr.Textbox(label="Topics Covered", placeholder="What was taught today?")
                    with gr.Row():
                        comments = gr.Textbox(label="Teacher Comments", placeholder="What went well? What didn't?")
                        questions = gr.Textbox(label="Student Questions", placeholder="Notable questions from students?")
                    pace = gr.Dropdown(
                        choices=["Just right", "Too fast — need to slow down", "Too slow — can go faster",
                                 "Students struggled — need revision", "Smooth — students engaged"],
                        label="Pace Notes", allow_custom_value=True,
                    )
                    btn_log = gr.Button("✅ Log Class", variant="primary")
                    log_result = gr.Markdown()
                    btn_log.click(
                        fn=log_class,
                        inputs=[course_id_display, lec_num, topics, comments, questions, pace],
                        outputs=[log_result],
                    )

                # Tab: Generate Content
                with gr.Tab("📝 Generate Content"):
                    gr.Markdown("### Auto-Generate Teaching Materials")
                    gr.Markdown("*Uses feedback from previous classes to improve content.*")
                    gen_lec = gr.Number(label="Class #", value=1, minimum=1, precision=0)

                    with gr.Row():
                        btn_slides = gr.Button("📊 Generate Slides", variant="primary")
                        btn_handout = gr.Button("📄 Generate Handout")
                        btn_notes = gr.Button("📋 Generate Teacher Notes")

                    content_output = gr.Markdown()
                    btn_slides.click(fn=gen_slides, inputs=[course_id_display, gen_lec], outputs=[content_output])
                    btn_handout.click(fn=gen_handout, inputs=[course_id_display, gen_lec], outputs=[content_output])
                    btn_notes.click(fn=gen_teacher_notes, inputs=[course_id_display, gen_lec], outputs=[content_output])

                # Tab: Evaluate
                with gr.Tab("✍️ Evaluate Assignments"):
                    gr.Markdown("### Evaluate Student Work")
                    gr.Markdown("*Paste student answers below. The AI will evaluate against COs and assign marks.*")
                    with gr.Row():
                        eval_sid = gr.Textbox(label="Student ID", placeholder="e.g., STU001")
                        eval_sname = gr.Textbox(label="Student Name", placeholder="e.g., John Doe")
                    with gr.Row():
                        eval_type = gr.Dropdown(
                            choices=["quiz", "assignment", "midterm", "final", "lab"],
                            label="Assessment Type", value="assignment", allow_custom_value=True,
                        )
                        eval_marks = gr.Number(label="Max Marks", value=100, minimum=1)
                        eval_lec = gr.Number(label="Class # (optional)", value=None, precision=0)
                    eval_answers = gr.Textbox(
                        lines=10, label="Student's Answers",
                        placeholder="Paste the student's answers here...\n\n"
                                    "Q1: [answer]\nQ2: [answer]\n...",
                    )
                    btn_eval = gr.Button("🔍 Evaluate", variant="primary")
                    eval_output = gr.Markdown()
                    btn_eval.click(
                        fn=eval_text,
                        inputs=[course_id_display, eval_sid, eval_sname,
                                eval_type, eval_answers, eval_marks, eval_lec],
                        outputs=[eval_output],
                    )

                # Tab: Student Profiling
                with gr.Tab("👥 Student Profiling"):
                    gr.Markdown("### Student Cohort Analysis")
                    btn_cohort = gr.Button("📈 View Cohort Summary")
                    cohort_output = gr.Markdown()
                    btn_cohort.click(fn=view_cohort, inputs=[course_id_display], outputs=[cohort_output])

                    gr.Markdown("---")
                    gr.Markdown("### 🧠 AI Class Intelligence")
                    gr.Markdown("*Analyzes all data — scores, evaluations, class feedback — to give actionable insights.*")
                    btn_insight = gr.Button("🔮 Generate Class Insight", variant="primary")
                    insight_output = gr.Markdown()
                    btn_insight.click(fn=gen_class_insight, inputs=[course_id_display], outputs=[insight_output])

                # Tab: Exams
                with gr.Tab("📝 Exam Generator"):
                    gr.Markdown("### Generate Adaptive Exam Papers")
                    with gr.Row():
                        exam_cohort = gr.Dropdown(
                            choices=["Remedial (Foundation)", "Average (Standard)", "Advanced (Higher Order)"],
                            label="Target Cohort", value="Remedial (Foundation)",
                        )
                        exam_co = gr.Textbox(label="Target CO", value="CO1")
                    exam_q = gr.Slider(1, 15, 5, step=1, label="Number of Questions")
                    btn_exam = gr.Button("📝 Generate Exam", variant="primary")
                    exam_output = gr.Markdown()
                    btn_exam.click(
                        fn=gen_exam,
                        inputs=[course_id_display, exam_cohort, exam_co, exam_q],
                        outputs=[exam_output],
                    )

                # Tab: Accreditation
                with gr.Tab("📋 Accreditation"):
                    gr.Markdown("### NBA/ABET Course File")
                    btn_nba = gr.Button("📋 Compile Report", variant="primary")
                    nba_output = gr.Markdown()
                    btn_nba.click(fn=gen_nba, inputs=[course_id_display], outputs=[nba_output])

            # Delete course button
            gr.Markdown("---")
            btn_delete = gr.Button("🗑️ Delete This Course", variant="stop")
            delete_result = gr.HTML(visible=False)

        # ═══════════════════════════════════════════════════════════
        #  Navigation
        # ═══════════════════════════════════════════════════════════

        def show_dashboard():
            return (
                gr.update(visible=True),   # dashboard_view
                gr.update(visible=False),  # add_course_view
                gr.update(visible=False),  # course_detail_view
                _course_cards_html(),      # course_cards
            )

        def show_add_course():
            return (
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(visible=False),
            )

        def show_course_detail(cid):
            if not cid or not cid.strip():
                return (gr.update(),) * 8
            cid = cid.strip()
            course = get_course(cid)
            if not course:
                return (f"⚠️ Course '{cid}' not found",) + ("",) * 7
            header = f"## {course.get('course_code', '')} — {course.get('course_title', '')}"
            progress = tracker.get_progress_summary(cid)
            return (
                gr.update(visible=False),  # dashboard_view
                gr.update(visible=False),  # add_course_view
                gr.update(visible=True),   # course_detail_view
                header,
                cid,
                progress,
            )

        def navigate_to_course(cid):
            return (
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=True),
                cid,
            )

        # Wire navigation
        btn_add_new.click(
            fn=show_add_course,
            outputs=[dashboard_view, add_course_view, course_detail_view],
        )

        btn_back_add.click(
            fn=show_dashboard,
            outputs=[dashboard_view, add_course_view, course_detail_view, course_cards],
        )

        btn_open.click(
            fn=lambda cid: (
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=True),
            ) + (lambda c: (
                f"## {c.get('course_code', '')} — {c.get('course_title', '')}" if c else "⚠️ Not found",
                cid,
                tracker.get_progress_summary(cid.strip()) if c else "",
            ))(get_course(cid.strip()) if cid.strip() else None),
            inputs=[course_id_input],
            outputs=[dashboard_view, add_course_view, course_detail_view,
                     course_header, course_id_display, progress_md],
        )

        btn_back_detail.click(
            fn=show_dashboard,
            outputs=[dashboard_view, add_course_view, course_detail_view, course_cards],
        )

        btn_delete.click(
            fn=do_delete_course,
            inputs=[course_id_display],
            outputs=[course_cards],
        ).then(
            fn=show_dashboard,
            outputs=[dashboard_view, add_course_view, course_detail_view, course_cards],
        )

    return demo


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    demo = create_ui()
    demo.launch(server_port=GRADIO_SERVER_PORT, theme=gr.themes.Soft())
