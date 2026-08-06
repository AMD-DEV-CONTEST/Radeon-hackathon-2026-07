import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _running_in_colab():
    try:
        import google.colab  # noqa: F401

        return True
    except Exception:
        return False


def _storage_root():
    if os.getenv("GENAI_STORAGE_DIR"):
        return Path(os.getenv("GENAI_STORAGE_DIR")).expanduser()
    if _running_in_colab():
        try:
            from google.colab import drive

            drive.mount("/content/drive", force_remount=False)
            return Path("/content/drive/MyDrive/done_project")
        except Exception:
            return Path("/content/done_project")
    return BASE_DIR


def get_db_path():
    data_dir = _storage_root() / "data"
    output_dir = _storage_root() / "outputs"
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "app.db")


def get_connection():
    conn = sqlite3.connect(get_db_path(), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_output_dir():
    output_dir = _storage_root() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


OUTPUT_DIR = get_output_dir()


def init_db():
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            email_verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cursor.fetchall()}
    if "is_admin" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    if "email_verified" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            negative_prompt TEXT,
            image_path TEXT,
            seed INTEGER,
            steps INTEGER,
            guidance_scale REAL,
            scheduler TEXT,
            width INTEGER,
            height INTEGER,
            generation_time REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'register',
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            login_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at: {path}")


def save_generation(user_id, metadata, image_path):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO generations
        (user_id, prompt, negative_prompt, image_path, seed, steps,
         guidance_scale, scheduler, width, height, generation_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        metadata["prompt"],
        metadata.get("negative_prompt", ""),
        image_path,
        metadata["seed"],
        metadata["steps"],
        metadata["guidance_scale"],
        metadata["scheduler"],
        metadata["width"],
        metadata["height"],
        metadata["generation_time"],
    ))
    conn.commit()
    conn.close()


def get_user_history(user_id, limit=24):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT prompt, image_path, seed, created_at
        FROM generations
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_user_by_username(username):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, password_hash, is_admin, email_verified, created_at FROM users WHERE username = ?",
        (username,),
    )
    user = cursor.fetchone()
    conn.close()
    return user


def get_user_by_identifier(identifier):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, password_hash, is_admin, email_verified, created_at FROM users WHERE username = ? OR email = ?",
        (identifier, identifier),
    )
    user = cursor.fetchone()
    conn.close()
    return user


def save_password_reset_code(user_id, code_hash, expires_at):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE password_resets SET used = 1 WHERE user_id = ? AND used = 0",
        (user_id,),
    )
    cursor.execute(
        "INSERT INTO password_resets (user_id, code_hash, expires_at) VALUES (?, ?, ?)",
        (user_id, code_hash, expires_at),
    )
    conn.commit()
    conn.close()


def get_active_password_reset_codes(user_id):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, code_hash, expires_at
        FROM password_resets
        WHERE user_id = ? AND used = 0
        ORDER BY created_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def mark_password_reset_used(reset_id):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE password_resets SET used = 1 WHERE id = ?", (reset_id,))
    conn.commit()
    conn.close()


def update_user_password(user_id, password_hash):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, user_id),
    )
    conn.commit()
    conn.close()


def set_user_email_verified(user_id, verified=True):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET email_verified = ? WHERE id = ?",
        (1 if verified else 0, user_id),
    )
    conn.commit()
    conn.close()


def save_email_verification_code(user_id, code_hash, expires_at, purpose="register"):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE email_verifications SET used = 1 WHERE user_id = ? AND purpose = ? AND used = 0",
        (user_id, purpose),
    )
    cursor.execute(
        "INSERT INTO email_verifications (user_id, code_hash, purpose, expires_at) VALUES (?, ?, ?, ?)",
        (user_id, code_hash, purpose, expires_at),
    )
    conn.commit()
    conn.close()


def get_active_email_verification_codes(user_id, purpose="register"):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, code_hash, expires_at
        FROM email_verifications
        WHERE user_id = ? AND purpose = ? AND used = 0
        ORDER BY created_at DESC
    """, (user_id, purpose))
    rows = cursor.fetchall()
    conn.close()
    return rows


def mark_email_verification_used(verification_id):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE email_verifications SET used = 1 WHERE id = ?", (verification_id,))
    conn.commit()
    conn.close()


def set_user_admin(user_id, is_admin=True):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET is_admin = ? WHERE id = ?",
        (1 if is_admin else 0, user_id),
    )
    conn.commit()
    conn.close()


def is_user_admin(user_id):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row and row[0])


def get_registered_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            u.id,
            u.username,
            u.email,
            u.created_at,
            CASE WHEN COALESCE(u.is_admin, 0) = 1 THEN 'Admin' ELSE 'User' END AS role,
            CASE WHEN COALESCE(u.email_verified, 0) = 1 THEN 'Verified' ELSE 'Not verified' END AS email_status,
            (SELECT COUNT(*) FROM generations g WHERE g.user_id = u.id) AS image_generations,
            (SELECT MAX(le.login_at) FROM login_events le WHERE le.user_id = u.id) AS last_login,
            (SELECT COUNT(*) FROM login_events le2 WHERE le2.user_id = u.id) AS login_count
        FROM users u
        ORDER BY u.created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows


def record_login(user_id, username):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO login_events (user_id, username) VALUES (?, ?)",
        (user_id, username),
    )
    conn.commit()
    conn.close()


def get_recent_logins(limit=30):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, login_at
        FROM login_events
        ORDER BY login_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def create_user(username, email, password_hash, is_admin=False, email_verified=False):
    path = get_db_path()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, is_admin, email_verified) VALUES (?, ?, ?, ?, ?)",
            (username, email, password_hash, 1 if is_admin else 0, 1 if email_verified else 0),
        )
        conn.commit()
        return True, "Account created successfully. Check your email for the verification OTP."
    except sqlite3.IntegrityError as e:
        if "username" in str(e):
            return False, "Username already exists."
        if "email" in str(e):
            return False, "Email already registered."
        return False, str(e)
    finally:
        conn.close()
