import sqlite3
import os

DB_PATH = os.getenv('DATABASE_PATH') or os.path.join(os.path.dirname(__file__), 'studytrack.db')


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = get_db()
    conn.execute('PRAGMA journal_mode=DELETE')
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS academic_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            topic TEXT NOT NULL,
            total_questions INTEGER DEFAULT 0,
            score REAL DEFAULT 0.0,
            mcq_score REAL DEFAULT 0.0,
            theory_score REAL DEFAULT 0.0,
            short_score REAL DEFAULT 0.0,
            weak_areas TEXT DEFAULT '[]',
            ai_analysis TEXT DEFAULT '',
            recommendations TEXT DEFAULT '',
            questions_data TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS career_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            career_goal TEXT NOT NULL,
            required_skills TEXT DEFAULT '[]',
            skill_scores TEXT DEFAULT '{}',
            overall_readiness REAL DEFAULT 0.0,
            gap_analysis TEXT DEFAULT '{}',
            roadmap TEXT DEFAULT '[]',
            recommendations TEXT DEFAULT '',
            theory_score REAL DEFAULT 0.0,
            coding_score REAL DEFAULT 0.0,
            questions_data TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def update_user_password_hash(user_id, password_hash):
    conn = get_db()
    conn.execute(
        'UPDATE users SET password_hash = ? WHERE id = ?',
        (password_hash, user_id)
    )
    conn.commit()
    conn.close()


def create_user(username, email, password_hash):
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
            (username, email, password_hash)
        )
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        return dict(user)
    except sqlite3.IntegrityError as e:
        conn.close()
        raise e


def save_academic_session(user_id, subject, topic, total_questions, score,
                          mcq_score, theory_score, short_score,
                          weak_areas, ai_analysis, recommendations, questions_data):
    import json
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO academic_sessions
        (user_id, subject, topic, total_questions, score, mcq_score, theory_score,
         short_score, weak_areas, ai_analysis, recommendations, questions_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, subject, topic, total_questions, score,
        mcq_score, theory_score, short_score,
        json.dumps(weak_areas), ai_analysis, recommendations,
        json.dumps(questions_data)
    ))
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return session_id


def get_academic_sessions(user_id):
    import json
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM academic_sessions WHERE user_id = ? ORDER BY created_at DESC',
        (user_id,)
    ).fetchall()
    conn.close()
    sessions = []
    for row in rows:
        s = dict(row)
        s['weak_areas'] = json.loads(s['weak_areas'] or '[]')
        s['questions_data'] = json.loads(s['questions_data'] or '[]')
        sessions.append(s)
    return sessions


def save_career_session(user_id, career_goal, required_skills, skill_scores,
                        overall_readiness, gap_analysis, roadmap,
                        recommendations, theory_score, coding_score, questions_data):
    import json
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO career_sessions
        (user_id, career_goal, required_skills, skill_scores, overall_readiness,
         gap_analysis, roadmap, recommendations, theory_score, coding_score, questions_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, career_goal,
        json.dumps(required_skills),
        json.dumps(skill_scores),
        overall_readiness,
        json.dumps(gap_analysis),
        json.dumps(roadmap),
        recommendations,
        theory_score, coding_score,
        json.dumps(questions_data)
    ))
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return session_id


def get_career_sessions(user_id):
    import json
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM career_sessions WHERE user_id = ? ORDER BY created_at DESC',
        (user_id,)
    ).fetchall()
    conn.close()
    sessions = []
    for row in rows:
        s = dict(row)
        s['required_skills'] = json.loads(s['required_skills'] or '[]')
        s['skill_scores'] = json.loads(s['skill_scores'] or '{}')
        s['gap_analysis'] = json.loads(s['gap_analysis'] or '{}')
        s['roadmap'] = json.loads(s['roadmap'] or '[]')
        s['questions_data'] = json.loads(s['questions_data'] or '[]')
        sessions.append(s)
    return sessions
