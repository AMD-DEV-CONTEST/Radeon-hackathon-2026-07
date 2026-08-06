"""
database.py - SQLite database setup and queries
Handles all persistent storage for EduCopilot.
"""

import sqlite3
import json
from typing import List, Optional, Dict, Any
from config import SQLITE_DB_PATH


def get_connection() -> sqlite3.Connection:
    """Get a new SQLite connection with row factory enabled."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    """Initialize all database tables. Call this once at startup."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            course_id TEXT PRIMARY KEY,
            course_code TEXT,
            course_title TEXT,
            num_classes INTEGER DEFAULT 30,
            teacher_instructions TEXT,
            course_materials TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS course_outcomes (
            co_id TEXT,
            course_id TEXT,
            statement TEXT,
            blooms_level TEXT,
            is_valid BOOLEAN,
            feedback TEXT,
            PRIMARY KEY (co_id, course_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lesson_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            lecture_num INTEGER,
            module_name TEXT,
            topic_description TEXT,
            target_co TEXT,
            pedagogy TEXT,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS class_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            lecture_num INTEGER,
            topics_covered TEXT,
            completed_on_schedule BOOLEAN,
            delay_reason TEXT,
            teacher_comments TEXT,
            student_questions TEXT,
            pace_notes TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT,
            course_id TEXT,
            student_name TEXT,
            average_score REAL DEFAULT 0,
            cohort TEXT DEFAULT 'Average',
            weak_cos TEXT DEFAULT '[]',
            strength_cos TEXT DEFAULT '[]',
            teacher_notes TEXT,
            PRIMARY KEY (student_id, course_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            course_id TEXT,
            co_id TEXT,
            score REAL,
            max_score REAL,
            assessment_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exam_papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            title TEXT,
            cohort_target TEXT,
            total_marks INTEGER,
            questions_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            student_id TEXT,
            student_name TEXT,
            assessment_type TEXT,
            image_path TEXT,
            total_marks_awarded REAL,
            total_marks_possible REAL,
            percentage REAL,
            questions_json TEXT,
            overall_feedback TEXT,
            recommended_cohort TEXT,
            evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            content_type TEXT,
            title TEXT,
            lecture_num INTEGER,
            markdown_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nba_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            co_id TEXT,
            target_score_pct REAL,
            actual_score_pct REAL,
            attainment_status TEXT,
            continuous_improvement_action TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    """)

    conn.commit()
    conn.close()


# ── Course Operations ──────────────────────────────────────────────

def save_course(course_id: str, course_code: str, course_title: str,
                num_classes: int = 30, teacher_instructions: str = "",
                course_materials: str = "") -> None:
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO courses
           (course_id, course_code, course_title, num_classes, teacher_instructions, course_materials)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (course_id, course_code, course_title, num_classes, teacher_instructions, course_materials)
    )
    conn.commit()
    conn.close()


def get_course(course_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM courses WHERE course_id = ?", (course_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_courses() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM courses ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_course(course_id: str) -> None:
    conn = get_connection()
    for table in ["courses", "course_outcomes", "lesson_plan", "class_logs",
                   "students", "student_scores", "exam_papers", "evaluations",
                   "generated_content", "nba_reports"]:
        conn.execute(f"DELETE FROM {table} WHERE course_id = ?", (course_id,))
    conn.commit()
    conn.close()


# ── Course Outcome Operations ──────────────────────────────────────

def save_course_outcomes(course_id: str, outcomes: list) -> None:
    conn = get_connection()
    for co in outcomes:
        conn.execute(
            """INSERT OR REPLACE INTO course_outcomes
               (co_id, course_id, statement, blooms_level, is_valid, feedback)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (co.co_id, course_id, co.statement, co.blooms_level, co.is_valid, co.feedback)
        )
    conn.commit()
    conn.close()


def get_course_outcomes(course_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM course_outcomes WHERE course_id = ?", (course_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Lesson Plan Operations ─────────────────────────────────────────

def save_lesson_plan(course_id: str, schedule: list) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM lesson_plan WHERE course_id = ?", (course_id,))
    for item in schedule:
        conn.execute(
            """INSERT INTO lesson_plan
               (course_id, lecture_num, module_name, topic_description, target_co, pedagogy)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (course_id, item.lecture_num, item.module_name,
             item.topic_description, item.target_co, item.pedagogy)
        )
    conn.commit()
    conn.close()


def get_lesson_plan(course_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lesson_plan WHERE course_id = ? ORDER BY lecture_num ASC",
        (course_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_planned_topic(course_id: str, lecture_num: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM lesson_plan WHERE course_id = ? AND lecture_num = ?",
        (course_id, lecture_num)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_lesson_plan_topic(course_id: str, lecture_num: int,
                             topic_description: str, module_name: str = None) -> None:
    """Update the topic (and optionally module) for a specific class."""
    conn = get_connection()
    if module_name is not None:
        conn.execute(
            "UPDATE lesson_plan SET topic_description = ?, module_name = ? WHERE course_id = ? AND lecture_num = ?",
            (topic_description, module_name, course_id, lecture_num)
        )
    else:
        conn.execute(
            "UPDATE lesson_plan SET topic_description = ? WHERE course_id = ? AND lecture_num = ?",
            (topic_description, course_id, lecture_num)
        )
    conn.commit()
    conn.close()


# ── Class Log Operations ───────────────────────────────────────────

def log_class_progress(
    course_id: str,
    lecture_num: int,
    topics_covered: str,
    completed_on_schedule: bool,
    delay_reason: Optional[str] = None,
    teacher_comments: Optional[str] = None,
    student_questions: Optional[str] = None,
    pace_notes: Optional[str] = None,
) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO class_logs
           (course_id, lecture_num, topics_covered, completed_on_schedule,
            delay_reason, teacher_comments, student_questions, pace_notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (course_id, lecture_num, topics_covered, completed_on_schedule,
         delay_reason, teacher_comments, student_questions, pace_notes)
    )
    conn.commit()
    conn.close()


def get_class_logs(course_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM class_logs WHERE course_id = ? ORDER BY lecture_num ASC",
        (course_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_last_completed_lecture(course_id: str) -> Optional[int]:
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(lecture_num) as max_lec FROM class_logs WHERE course_id = ?",
        (course_id,)
    ).fetchone()
    conn.close()
    if row and row["max_lec"] is not None:
        return row["max_lec"]
    return None


# ── Student Operations ─────────────────────────────────────────────

def save_student_profile(profile: dict, course_id: str) -> None:
    weak_cos_json = json.dumps(profile.get("weak_cos", []))
    strength_cos_json = json.dumps(profile.get("strength_cos", []))
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO students
           (student_id, course_id, student_name, average_score, cohort,
            weak_cos, strength_cos, teacher_notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (profile["student_id"], course_id, profile["student_name"],
         profile["average_score"], profile["cohort"],
         weak_cos_json, strength_cos_json, profile.get("teacher_notes"))
    )
    conn.commit()
    conn.close()


def get_students_by_cohort(course_id: str, cohort: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM students WHERE course_id = ? AND cohort = ?",
        (course_id, cohort)
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["weak_cos"] = json.loads(d.get("weak_cos", "[]"))
        d["strength_cos"] = json.loads(d.get("strength_cos", "[]"))
        results.append(d)
    return results


def get_all_students(course_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM students WHERE course_id = ?", (course_id,)
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["weak_cos"] = json.loads(d.get("weak_cos", "[]"))
        d["strength_cos"] = json.loads(d.get("strength_cos", "[]"))
        results.append(d)
    return results


# ── Student Score Operations ───────────────────────────────────────

def save_student_scores(student_id: str, course_id: str, scores: list) -> None:
    conn = get_connection()
    for s in scores:
        conn.execute(
            """INSERT INTO student_scores
               (student_id, course_id, co_id, score, max_score, assessment_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (student_id, course_id, s["co_id"],
             s["score"], s["max_score"], s["assessment_type"])
        )
    conn.commit()
    conn.close()


def get_scores_by_co(course_id: str, co_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM student_scores WHERE course_id = ? AND co_id = ?",
        (course_id, co_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_student_scores(course_id: str, student_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM student_scores WHERE course_id = ? AND student_id = ?",
        (course_id, student_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def compute_co_attainment(course_id: str) -> Dict[str, float]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT co_id,
                  (SUM(score) / SUM(max_score)) * 100 AS attainment_pct
           FROM student_scores WHERE course_id = ? GROUP BY co_id""",
        (course_id,)
    ).fetchall()
    conn.close()
    return {row["co_id"]: round(row["attainment_pct"], 2) for row in rows}


# ── Exam Paper Operations ──────────────────────────────────────────

def save_exam_paper(course_id: str, paper: dict) -> None:
    questions_json = json.dumps(paper.get("questions", []))
    conn = get_connection()
    conn.execute(
        """INSERT INTO exam_papers
           (course_id, title, cohort_target, total_marks, questions_json)
           VALUES (?, ?, ?, ?, ?)""",
        (course_id, paper["title"], paper["cohort_target"],
         paper["total_marks"], questions_json)
    )
    conn.commit()
    conn.close()


def get_exam_papers(course_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM exam_papers WHERE course_id = ? ORDER BY created_at DESC",
        (course_id,)
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["questions"] = json.loads(d.get("questions_json", "[]"))
        results.append(d)
    return results


# ── Evaluation Operations ──────────────────────────────────────────

def save_evaluation(course_id: str, eval_data: dict) -> int:
    questions_json = json.dumps(eval_data.get("questions", []))
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO evaluations
           (course_id, student_id, student_name, assessment_type, image_path,
            total_marks_awarded, total_marks_possible, percentage,
            questions_json, overall_feedback, recommended_cohort)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (course_id, eval_data.get("student_id"), eval_data.get("student_name"),
         eval_data.get("assessment_type", "assignment"), eval_data.get("image_path"),
         eval_data["total_marks_awarded"], eval_data["total_marks_possible"],
         eval_data["percentage"], questions_json,
         eval_data["overall_feedback"], eval_data["recommended_cohort"])
    )
    eval_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return eval_id


def get_evaluations(course_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM evaluations WHERE course_id = ? ORDER BY evaluated_at DESC",
        (course_id,)
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["questions"] = json.loads(d.get("questions_json", "[]"))
        results.append(d)
    return results


# ── Generated Content Operations ───────────────────────────────────

def save_generated_content(course_id: str, content_type: str, title: str,
                           markdown_content: str, lecture_num: int = None) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO generated_content
           (course_id, content_type, title, lecture_num, markdown_content)
           VALUES (?, ?, ?, ?, ?)""",
        (course_id, content_type, title, lecture_num, markdown_content)
    )
    cid = cursor.lastrowid
    conn.commit()
    conn.close()
    return cid


def get_generated_content(course_id: str, content_type: str = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    if content_type:
        rows = conn.execute(
            "SELECT * FROM generated_content WHERE course_id = ? AND content_type = ? ORDER BY created_at DESC",
            (course_id, content_type)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM generated_content WHERE course_id = ? ORDER BY created_at DESC",
            (course_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_generated_content_by_id(content_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM generated_content WHERE id = ?", (content_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_generated_content(content_id: int, markdown_content: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE generated_content SET markdown_content = ? WHERE id = ?",
        (markdown_content, content_id)
    )
    conn.commit()
    conn.close()


def delete_generated_content(content_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM generated_content WHERE id = ?", (content_id,))
    conn.commit()
    conn.close()


# ── NBA Report Operations ──────────────────────────────────────────

def save_nba_report(course_id: str, reports: list) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM nba_reports WHERE course_id = ?", (course_id,))
    for rpt in reports:
        conn.execute(
            """INSERT INTO nba_reports
               (course_id, co_id, target_score_pct, actual_score_pct,
                attainment_status, continuous_improvement_action)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (course_id, rpt.co_id, rpt.target_score_pct,
             rpt.actual_score_pct, rpt.attainment_status,
             rpt.continuous_improvement_action)
        )
    conn.commit()
    conn.close()


def get_nba_reports(course_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM nba_reports WHERE course_id = ?", (course_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
