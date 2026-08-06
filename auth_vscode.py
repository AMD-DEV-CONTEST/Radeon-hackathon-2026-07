import bcrypt
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from database_vscode import (
    create_user,
    get_active_password_reset_codes,
    get_active_email_verification_codes,
    get_user_by_identifier,
    get_user_by_username,
    mark_email_verification_used,
    mark_password_reset_used,
    record_login,
    save_email_verification_code,
    save_password_reset_code,
    set_user_email_verified,
    set_user_admin,
    update_user_password,
)

current_session = {"user_id": None, "username": None}


def _load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def _send_email(email: str, subject: str, body: str):
    smtp_host = os.getenv("GENAI_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("GENAI_SMTP_PORT", "587"))
    smtp_user = os.getenv("GENAI_SMTP_USER")
    smtp_password = os.getenv("GENAI_SMTP_PASSWORD")
    smtp_from = os.getenv("GENAI_SMTP_FROM", smtp_user or "")

    if not all([smtp_user, smtp_password, smtp_from]):
        return (
            False,
            "Email is not configured. Add GENAI_SMTP_USER and GENAI_SMTP_PASSWORD "
            "to the .env file before running the app. For Gmail, use an App Password.",
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from
    message["To"] = email
    message.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)

    return True, "OTP sent to the registered email."


def _send_reset_email(email: str, username: str, code: str):
    return _send_email(
        email,
        "GenAI Studio Password Reset OTP",
        (
            f"Hello {username},\n\n"
            f"Your GenAI Studio password reset OTP is: {code}\n\n"
            "This OTP expires in 15 minutes. If you did not request this, ignore this email.\n"
        ),
    )


def _send_verification_email(email: str, username: str, code: str):
    return _send_email(
        email,
        "GenAI Studio Email Verification OTP",
        (
            f"Hello {username},\n\n"
            f"Your GenAI Studio email verification OTP is: {code}\n\n"
            "This OTP expires in 15 minutes. Enter it in the Verify Email tab to activate your account.\n"
        ),
    )


def register(username: str, email: str, password: str, confirm_password: str):
    username = (username or "").strip()
    email = (email or "").strip()

    if not all([username, email, password, confirm_password]):
        return False, "All fields are required."
    if "@" not in email or "." not in email:
        return False, "Enter a valid email address."
    if password != confirm_password:
        return False, "Passwords do not match."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    if len(username) < 3:
        return False, "Username must be at least 3 characters."

    success, message = create_user(username, email, hash_password(password))
    if not success:
        return success, message

    user = get_user_by_username(username)
    if not user:
        return True, "Account created. Please log in."

    code = f"{secrets.randbelow(1000000):06d}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    save_email_verification_code(user[0], hash_password(code), expires_at, "register")
    try:
        sent, email_message = _send_verification_email(user[2], user[1], code)
        if sent:
            return True, "Account created. Verification OTP sent to your registered email."
        return True, f"Account created, but OTP email was not sent: {email_message}"
    except Exception as e:
        return True, f"Account created, but OTP email failed: {str(e)}"


def verify_email(identifier: str, code: str):
    identifier = (identifier or "").strip()
    code = (code or "").strip()
    if not identifier or not code:
        return "Enter your username/email and OTP."

    user = get_user_by_identifier(identifier)
    if not user:
        return "No account found with that username or email."

    now = datetime.now(timezone.utc)
    for verification_id, code_hash, expires_at in get_active_email_verification_codes(user[0], "register"):
        expires = datetime.fromisoformat(expires_at)
        if now > expires:
            continue
        if verify_password(code, code_hash):
            set_user_email_verified(user[0], True)
            mark_email_verification_used(verification_id)
            return "Email verified successfully. You can sign in now."

    return "Invalid or expired verification OTP."


def resend_verification_otp(identifier: str):
    identifier = (identifier or "").strip()
    if not identifier:
        return "Enter your username or registered email."
    user = get_user_by_identifier(identifier)
    if not user:
        return "No account found with that username or email."
    if len(user) > 5 and user[5]:
        return "This email is already verified."

    code = f"{secrets.randbelow(1000000):06d}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    save_email_verification_code(user[0], hash_password(code), expires_at, "register")
    try:
        sent, message = _send_verification_email(user[2], user[1], code)
        return "Verification OTP sent to your registered email." if sent else message
    except Exception as e:
        return f"Could not send verification OTP: {str(e)}"


def login(username: str, password: str):
    username = (username or "").strip()
    if not username or not password:
        return False, "Username and password are required."

    user = get_user_by_username(username)
    if not user or not verify_password(password, user[3]):
        return False, "Invalid username or password."
    if not bool(user[4]) and len(user) > 5 and not bool(user[5]):
        return False, "Please verify your registered email before signing in."

    current_session["user_id"] = user[0]
    current_session["username"] = user[1]
    record_login(user[0], user[1])
    return True, f"Welcome back, {user[1]}."


def authenticate_user(username: str, password: str):
    username = (username or "").strip()
    if not username or not password:
        return False, "Username and password are required.", None

    user = get_user_by_username(username)
    if not user or not verify_password(password, user[3]):
        return False, "Invalid username or password.", None
    if not bool(user[4]) and len(user) > 5 and not bool(user[5]):
        return False, "Please verify your registered email before signing in.", None

    record_login(user[0], user[1])
    session = {
        "user_id": user[0],
        "username": user[1],
        "is_admin": bool(user[4]) if len(user) > 4 else False,
    }
    return True, f"Welcome back, {user[1]}.", session


def ensure_admin_account(username="admin", email="admin@example.com", password="Gnk2005/09-07"):
    user = get_user_by_username(username)
    password_hash = hash_password(password)
    if user:
        update_user_password(user[0], password_hash)
        set_user_admin(user[0], True)
        set_user_email_verified(user[0], True)
        return
    create_user(username, email, password_hash, is_admin=True, email_verified=True)


def request_password_reset(identifier: str):
    identifier = (identifier or "").strip()
    if not identifier:
        return "Enter your username or registered email."

    user = get_user_by_identifier(identifier)
    if not user:
        return "No account found with that username or email."

    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = hash_password(code)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    save_password_reset_code(user[0], code_hash, expires_at)

    try:
        success, message = _send_reset_email(user[2], user[1], code)
        return message if success else message
    except Exception as e:
        return f"Could not send reset email: {str(e)}"


def reset_password(identifier: str, code: str, new_password: str, confirm_password: str):
    identifier = (identifier or "").strip()
    code = (code or "").strip()

    if not all([identifier, code, new_password, confirm_password]):
        return "All OTP reset fields are required."
    if new_password != confirm_password:
        return "Passwords do not match."
    if len(new_password) < 6:
        return "Password must be at least 6 characters."

    user = get_user_by_identifier(identifier)
    if not user:
        return "No account found with that username or email."

    now = datetime.now(timezone.utc)
    for reset_id, code_hash, expires_at in get_active_password_reset_codes(user[0]):
        expires = datetime.fromisoformat(expires_at)
        if now > expires:
            continue
        if verify_password(code, code_hash):
            update_user_password(user[0], hash_password(new_password))
            mark_password_reset_used(reset_id)
            return "Password reset successfully. You can sign in with the new password."

    return "Invalid or expired OTP."


def logout():
    current_session["user_id"] = None
    current_session["username"] = None
    return "Logged out successfully."


def is_logged_in():
    return current_session["user_id"] is not None


def get_current_user():
    return current_session
