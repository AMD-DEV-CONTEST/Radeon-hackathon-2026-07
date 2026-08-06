import os
import json
import secrets
import smtplib
import hmac
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import threading
import time
from datetime import datetime, timedelta
import urllib.parse
import requests
from fastapi import FastAPI, BackgroundTasks, HTTPException, Body, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import List, Optional

import sqlite3
import db
import generator
import sender
import telegram_agent
from google.genai import types

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="HR Cold Email Outreach Automator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://www.pitchdock.xyz", "https://pitchdock.xyz"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# User-scoped task states
user_task_states = {}

def get_user_task_state(user_id: int):
    if user_id not in user_task_states:
        user_task_states[user_id] = {
            "type": None,          # "generate" or "send"
            "status": "idle",      # "idle", "running", "completed", "failed"
            "total": 0,
            "current": 0,
            "success": 0,
            "failed": 0,
            "logs": [],
            "start_time": None
        }
    return user_task_states[user_id]

def log_user_task_message(user_id: int, msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    state = get_user_task_state(user_id)
    state["logs"].append(f"[{timestamp}] {msg}")
    print(f"Task Log User {user_id}: {msg}")

def validate_safe_resume_path(path_str: str) -> bool:
    if not path_str:
        return True
    
    # Block path traversal attempts
    normalized = os.path.normpath(path_str)
    if ".." in normalized:
        return False
        
    # Enforce PDF extension
    if not path_str.lower().endswith(".pdf"):
        return False
        
    # Block access to system configurations, database files, and sensitive directories
    blocked_patterns = [
        ".env",
        "outreach.db",
        "server.py",
        "db.py",
        "test_",
        "/etc/",
        "/proc/",
        "/sys/",
        "id_rsa",
        "authorized_keys"
    ]
    for pattern in blocked_patterns:
        if pattern in normalized:
            return False
            
    return True

# Pydantic Schemas for API requests
class GenerateRequest(BaseModel):
    limit: Optional[int] = None
    category: Optional[str] = None
    auto_approve: bool = False

class SendRequest(BaseModel):
    limit: Optional[int] = None
    delay: int = 30

class ProfileData(BaseModel):
    full_name: str
    phone_number: str
    linkedin_profile: str
    current_designation: str
    experience_years: str
    industry_domain: str
    target_role: str
    achievements: List[str]
    resume_pdf_path: str

class EnvData(BaseModel):
    gemini_api_key: str
    sender_email: str
    sender_password: str
    smtp_server: str = "smtp.gmail.com"
    smtp_port: str = "587"
    sending_channel: Optional[str] = "smtp"

class ResetRequest(BaseModel):
    from_status: str
    to_status: str = "pending"

class BulkActionRequest(BaseModel):
    ids: Optional[List[int]] = None # if empty/null, applies to all
    action: str # "approve", "reject", "delete"

class ContactInput(BaseModel):
    email: str
    name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    category: Optional[str] = None

class AddContactsRequest(BaseModel):
    contacts: List[ContactInput]
    mode: str  # "ai", "template", or "scratch"
    template_subject: Optional[str] = None
    template_body: Optional[str] = None
    auto_approve: bool = False

class FreeOutreachRequest(BaseModel):
    full_name: str
    phone_number: str
    linkedin_profile: str
    current_designation: str
    experience_years: str
    industry_domain: str
    target_role: str
    achievements: List[str]
    resume_pdf_path: str = ""
    category: str
    strategy: str  # "ai" | "template" | "scratch"
    template_subject: str = ""
    template_body: str = ""

class ChatCustomizeRequest(BaseModel):
    message: str
    template_subject: str
    template_body: str
    achievements: List[str]
    target_role: str
    recruiter_id: Optional[int] = None
    job_description: Optional[str] = None

class ChatCustomizedOutput(BaseModel):
    updated_subject: str
    updated_body: str
    updated_achievements: List[str]
    chat_response: str
    updated_recruiter_name: Optional[str] = None
    updated_company: Optional[str] = None
    updated_target_role: Optional[str] = None

class TelegramWebhookUpdate(BaseModel):
    model_config = {"extra": "allow"}

# Background Worker Functions
def run_background_generation(req: GenerateRequest, user_id: int):
    state = get_user_task_state(user_id)
    
    try:
        profile = db.get_user_profile(user_id)
        if not profile:
            profile = generator.load_candidate_profile()
        client = generator.get_gemini_client()
    except Exception as e:
        state["status"] = "failed"
        state["logs"].append(f"Initialization error: {str(e)}")
        return

    # Get contacts
    contacts = db.get_contacts_by_status("pending", user_id=user_id, limit=req.limit, category=req.category)
    if not contacts:
        state["status"] = "completed"
        log_user_task_message(user_id, "No pending contacts found to generate drafts for.")
        return
        
    state["total"] = len(contacts)
    state["current"] = 0
    state["success"] = 0
    state["failed"] = 0
    
    log_user_task_message(user_id, f"Starting email draft generation for {len(contacts)} contacts...")
    
    for contact in contacts:
        if state["status"] != "running":
            log_user_task_message(user_id, "Generation task stopped by user.")
            break
            
        state["current"] += 1
        log_user_task_message(user_id, f"[{state['current']}/{state['total']}] Generating draft for {contact['name']} ({contact['company']})...")
        
        try:
            subject, body = generator.generate_email_draft(contact, profile, client)
            target_status = "approved" if req.auto_approve else "drafted"
            db.update_contact_draft(contact["id"], subject, body, status=target_status, user_id=user_id)
            
            state["success"] += 1
            log_user_task_message(user_id, f"  ✓ Successfully drafted for {contact['name']}. Status: {target_status}")
            
            # API rate limit spacing
            time.sleep(1.5)
        except Exception as e:
            state["failed"] += 1
            db.update_contact_status(contact["id"], "failed", error_message=str(e), user_id=user_id)
            log_user_task_message(user_id, f"  ✗ Failed for {contact['name']}: {str(e)}")
            
    state["status"] = "completed"
    log_user_task_message(user_id, f"Draft generation completed. Success: {state['success']}, Failed: {state['failed']}")

def run_background_sending(req: SendRequest, user_id: int):
    state = get_user_task_state(user_id)
    
    try:
        profile = db.get_user_profile(user_id) or {}
        default_prof = generator.load_candidate_profile() if os.path.exists("candidate_profile.json") else {}
        
        # Merge missing profile fields with candidate profile defaults
        for k, v in default_prof.items():
            if not profile.get(k):
                profile[k] = v

        if not profile.get("full_name"):
            profile["full_name"] = "Shubranshu Shekhar"
        if not profile.get("experience_years"):
            profile["experience_years"] = "3"
        if not profile.get("current_designation"):
            profile["current_designation"] = "Software Engineer"
        if not profile.get("industry_domain"):
            profile["industry_domain"] = "Backend Systems & Cloud Infrastructure"
        if not profile.get("target_role"):
            profile["target_role"] = "Senior Software Engineer"
            
        billing = db.get_billing_info(user_id)
    except Exception as e:
        state["status"] = "failed"
        state["logs"].append(f"Initialization error: {str(e)}")
        return

    resume_path = profile.get("resume_pdf_path")
    if not resume_path or not os.path.exists(resume_path):
        if os.path.exists("resume.pdf"):
            resume_path = "resume.pdf"
        elif os.path.exists("/home/ubuntu/emailAutomater/resume.pdf"):
            resume_path = "/home/ubuntu/emailAutomater/resume.pdf"
        else:
            log_user_task_message(user_id, f"WARNING: Resume PDF not found at '{resume_path}'. Email will go without attachment.")
            resume_path = None

    if resume_path and os.path.exists(resume_path):
        log_user_task_message(user_id, f"✓ Resume attachment verified: {os.path.basename(resume_path)}")

    # Get approved contacts
    contacts = db.get_contacts_by_status("approved", user_id=user_id, limit=req.limit)
    if not contacts:
        state["status"] = "completed"
        log_user_task_message(user_id, "No approved email drafts found to send.")
        return
        
    state["total"] = len(contacts)
    state["current"] = 0
    state["success"] = 0
    state["failed"] = 0
    
    log_user_task_message(user_id, f"Starting secure SMTP sending to {len(contacts)} contacts...")
    
    for idx, contact in enumerate(contacts):
        if state["status"] != "running":
            log_user_task_message(user_id, "Sending task stopped by user.")
            break
            
        state["current"] += 1
        log_user_task_message(user_id, f"[{state['current']}/{state['total']}] Sending to {contact['name']} ({contact['email']})...")
        
        try:
            subject = contact.get("personalized_subject")
            body = contact.get("personalized_body")

            # Check if subject/body is missing or contains old fallback template markers
            if not subject or not body or "hundreds" in body.lower() or "spearheaded" in body.lower() or "{" in body:
                log_user_task_message(user_id, f"  [AI GENERATE] Generating fresh cold email for {contact['name']} ({contact['company']})...")
                try:
                    client = generator.get_gemini_client()
                    subject, body = generator.generate_email_draft(contact, profile, client)
                    db.update_contact_draft(contact["id"], subject, body, status="approved", user_id=user_id)
                except Exception as gen_err:
                    log_user_task_message(user_id, f"  ⚠️ AI draft generation warning: {gen_err}")

            target_email = contact["email"].strip()
            log_user_task_message(user_id, f"  Outreach dispatch to recruiter: {contact['name']} <{target_email}>")
            
            success, err = sender.send_single_email(
                to_email=target_email,
                subject=subject,
                body=body,
                user_id=user_id,
                attachment_path=resume_path
            )
            
            sent_time = datetime.now().isoformat()
            if success:
                db.update_contact_status(contact["id"], "sent", sent_at=sent_time, user_id=user_id)
                db.increment_emails_sent(1, user_id=user_id)
                state["success"] += 1
                log_user_task_message(user_id, f"  ✓ Email successfully sent to {target_email}")
            else:
                db.update_contact_status(contact["id"], "failed", error_message=err, user_id=user_id)
                state["failed"] += 1
                log_user_task_message(user_id, f"  ✗ Failed sending to {contact['email']}: {err}")
                
            # Rate limit throttle spacing between emails
            if idx < len(contacts) - 1 and req.delay > 0:
                log_user_task_message(user_id, f"  Waiting {req.delay}s to avoid SMTP rate-limits...")
                time.sleep(req.delay)
                
        except Exception as e:
            state["failed"] += 1
            db.update_contact_status(contact["id"], "failed", error_message=str(e), user_id=user_id)
            log_user_task_message(user_id, f"  ✗ Unexpected SMTP error for {contact['email']}: {str(e)}")
            
    state["status"] = "completed"
    log_user_task_message(user_id, f"Sending run completed. Success: {state['success']}, Failed: {state['failed']}")


from fastapi import Depends, Header, Cookie, Response

# Feedback and Support Schemas
class FeedbackRequest(BaseModel):
    name: str
    rating: int
    comment: str

class SupportQueryRequest(BaseModel):
    name: str
    email: str
    subject: str
    message: str

# Auth Schemas
class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

# Current User Dependency
def get_current_user(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None)
):
    token = None
    if session_token:
        token = session_token
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    user = db.get_user_by_session_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session token")
    return user

def send_verification_email(to_email: str, token: str, request_host: str):
    resend_api_key = os.environ.get("RESEND_API_KEY")
    sender_email = os.environ.get("SENDER_EMAIL", "pitchdock.xyz@gmail.com")
    sender_password = os.environ.get("SENDER_PASSWORD")
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = os.environ.get("SMTP_PORT", "587")
    
    # Determine base URL protocol
    protocol = "https" if "pitchdock.xyz" in request_host or "13.63.174.222" in request_host else "http"
    
    # Map API port 8000 to Frontend port 3000 for local development
    frontend_host = request_host
    if "localhost:8000" in request_host:
        frontend_host = "localhost:3000"
    elif "127.0.0.1:8000" in request_host:
        frontend_host = "127.0.0.1:3000"
        
    verify_url = f"{protocol}://{frontend_host}/verify?token={token}"
    
    subject = "Verify your email for PitchDock"
    html_content = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 550px; margin: 0 auto; padding: 40px 30px; background-color: #F4F5F1; border-radius: 16px; border: 1px solid rgba(24, 24, 27, 0.08);">
      <div style="text-align: center; margin-bottom: 30px;">
        <h2 style="font-weight: 700; font-size: 26px; color: #18181b; margin-top: 0; margin-bottom: 8px;">Welcome to PitchDock!</h2>
        <p style="font-size: 15px; color: #71717a; margin-top: 0;">Skip the ATS filters and land in the recruiter's inbox.</p>
      </div>
      
      <div style="background-color: #ffffff; padding: 35px 30px; border-radius: 12px; border: 1px solid rgba(24, 24, 27, 0.06); box-shadow: 0 4px 12px rgba(24, 24, 27, 0.01);">
        <p style="font-size: 15px; line-height: 1.6; color: #27272a; margin-top: 0;">Hi there,</p>
        <p style="font-size: 15px; line-height: 1.6; color: #27272a;">Thank you for registering on PitchDock. Please verify your email address to complete your account setup and activate your AI recruiter outreach console.</p>
        
        <div style="text-align: center; margin: 30px 0;">
          <a href="{verify_url}" style="background-color: #18181b; color: #ffffff; padding: 14px 28px; font-weight: 600; font-size: 14.5px; border-radius: 8px; text-decoration: none; display: inline-block; box-shadow: 0 4px 10px rgba(24,24,27,0.15);">Verify Email Address</a>
        </div>
        
        <p style="font-size: 13px; color: #71717a; line-height: 1.5; margin-bottom: 0;">If the button above does not work, copy and paste this link into your browser:<br/>
        <a href="{verify_url}" style="color: #10B981; text-decoration: underline;">{verify_url}</a></p>
      </div>
      
      <div style="text-align: center; margin-top: 25px;">
        <p style="font-size: 12px; color: #a1a1aa; margin: 0;">PitchDock — reach the recruiter, not the filter.</p>
      </div>
    </div>
    """
    
    # Log to server console (helpful for local testing)
    print(f"\n==================================================\n[EMAIL DISPATCH] Verification Link generated:\n{verify_url}\n==================================================\n")
    
    # 1. Try sending via Resend API first (Primary)
    if resend_api_key:
        print("[EMAIL DISPATCH] Attempting primary Resend API dispatch...")
        headers = {
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json"
        }
        
        # Once domain is verified in Resend, sending from verify@pitchdock.xyz is active.
        from_email = "PitchDock <verify@pitchdock.xyz>"
        
        payload = {
            "from": from_email,
            "to": to_email,
            "subject": subject,
            "html": html_content
        }
        try:
            res = requests.post("https://api.resend.com/emails", json=payload, headers=headers)
            if res.status_code in [200, 201]:
                print("[EMAIL DISPATCH] Primary Resend API dispatch succeeded!")
                return True, None
            else:
                print(f"[EMAIL DISPATCH] Resend API error (Status {res.status_code}): {res.text}. Falling back to SMTP...")
        except Exception as e:
            print(f"[EMAIL DISPATCH] Resend request failed: {str(e)}. Falling back to SMTP...")
            
    # 2. Try sending via Gmail SMTP (Secondary Fallback)
    if sender_email and sender_password:
        print("[EMAIL DISPATCH] Attempting fallback SMTP dispatch...")
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = f'"PitchDock" <{sender_email}>'
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(html_content, "html"))
            
            port = int(smtp_port)
            if port == 465:
                server = smtplib.SMTP_SSL(smtp_server, port)
            else:
                server = smtplib.SMTP(smtp_server, port)
                server.ehlo()
                server.starttls()
                server.ehlo()
                
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
            server.quit()
            print("[EMAIL DISPATCH] Fallback SMTP dispatch succeeded!")
            return True, None
        except Exception as e:
            print(f"[EMAIL DISPATCH ERROR] Fallback SMTP failed: {str(e)}")
            return False, str(e)
            
    return False, "No active email dispatch channel configured."

# Auth REST Routes
@app.post("/api/auth/signup")
def signup_endpoint(req: SignupRequest, request: Request):
    try:
        # Generate token
        token = secrets.token_urlsafe(32)
        res = db.create_user(req.email, req.password, verification_token=token)
        
        # Dispatch verification email
        host = request.headers.get("host", "pitchdock.xyz")
        send_verification_email(req.email, token, host)
        
        return {
            "status": "success", 
            "message": "Verification link sent! Please check your inbox.",
            "requires_verification": True
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth/login")
def login_endpoint(req: LoginRequest, response: Response):
    user = db.verify_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or password")
        
    # Check if verified (default to True/1 for older records where is_verified is null/empty/not '0')
    is_verified = user.get("is_verified")
    if is_verified == '0' or is_verified == 0:
        raise HTTPException(
            status_code=403, 
            detail="Your email is not verified yet. Please check your inbox for the verification email."
        )
        
    token, expires_at = db.create_session(user["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=30 * 86400
    )
    return {"status": "success", "token": token, "expires_at": expires_at, "user": user}

@app.get("/api/auth/verify")
def verify_endpoint(token: str, response: Response):
    if not token:
        raise HTTPException(status_code=400, detail="Token parameter is required")
        
    user = db.verify_user_token(token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
        
    # Create an active login session automatically upon successful verification
    session_token, expires_at = db.create_session(user["id"])
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=30 * 86400
    )
    return {
        "status": "success", 
        "message": "Account verified successfully!", 
        "token": session_token,
        "user": user
    }

@app.post("/api/auth/logout")
def logout_endpoint(response: Response, authorization: Optional[str] = Header(None), session_token: Optional[str] = Cookie(None)):
    token = None
    if session_token:
        token = session_token
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    if token:
        db.delete_session(token)
        
    response.delete_cookie(key="session_token")
    return {"status": "success", "message": "Successfully logged out"}

@app.get("/api/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user

@app.post("/api/telegram/link-code")
def create_telegram_link_code(current_user: dict = Depends(get_current_user)):
    try:
        link_data = telegram_agent.create_link_code(current_user["id"])
        bot_username = os.environ.get("TELEGRAM_BOT_USERNAME", "")
        return {
            "status": "success",
            "token": link_data["token"],
            "expires_at": link_data["expires_at"],
            "bot_username": bot_username,
            "instructions": (
                f"Open Telegram and send /link {link_data['token']} "
                f"to @{bot_username}" if bot_username else f"Send /link {link_data['token']} to your PitchDock Telegram bot."
            )
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/webhook")
def telegram_webhook(
    payload: dict = Body(...),
    x_telegram_bot_api_secret_token: Optional[str] = Header(None)
):
    expected_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret.")
    try:
        return telegram_agent.handle_telegram_update(payload)
    except Exception as e:
        print(f"[TELEGRAM WEBHOOK ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Dashboard REST Routes

@app.get("/api/stats")
def get_stats(current_user: dict = Depends(get_current_user)):
    try:
        db.init_db()
        return db.get_stats(user_id=current_user["id"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/contacts")
def get_contacts(
    status: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    try:
        conn = db.get_connection()
        conn.row_factory = sqlite3_row_factory
        cursor = conn.cursor()
        
        # Auto-migration of template contacts to active user
        cursor.execute("SELECT COUNT(*) FROM contacts WHERE user_id = ?", (current_user["id"],))
        user_contacts_count = cursor.fetchone()["COUNT(*)"]
        if user_contacts_count == 0 and current_user["id"] != 1:
            # Secure copy of templates from user 1 instead of stealing them via UPDATE
            cursor.execute("SELECT name, email, company, title, category, status, personalized_subject, personalized_body, error_message, sent_at FROM contacts WHERE user_id = 1")
            template_contacts = cursor.fetchall()
            for contact in template_contacts:
                try:
                    cursor.execute("""
                    INSERT INTO contacts (name, email, company, title, category, status, personalized_subject, personalized_body, error_message, sent_at, user_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        contact["name"], 
                        contact["email"], 
                        contact["company"], 
                        contact["title"], 
                        contact["category"], 
                        contact["status"], 
                        contact["personalized_subject"], 
                        contact["personalized_body"], 
                        contact["error_message"], 
                        contact["sent_at"], 
                        current_user["id"]
                    ))
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
            
        query = "SELECT * FROM contacts WHERE user_id = ?"
        params = [current_user["id"]]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        if category:
            query += " AND category = ?"
            params.append(category)
        if search:
            query += " AND (name LIKE ? OR company LIKE ? OR email LIKE ? OR title LIKE ?)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param, search_param])
            
        # Count query
        count_query = query.replace("SELECT *", "SELECT COUNT(*)")
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()["COUNT(*)"]
        
        # Paginated query
        query += " ORDER BY id ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "total": total_count,
            "contacts": [dict(r) for r in rows]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def sqlite3_row_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

@app.post("/api/import")
def import_contacts(excel_path: str = "kaamkibaatein_HR_Contact_Database.xlsx", pdf_path: str = "HR_Contact_List.pdf", current_user: dict = Depends(get_current_user)):
    try:
        results = {}
        if os.path.exists(pdf_path):
            results["pdf"] = db.import_from_pdf(pdf_path, user_id=current_user["id"])
        if os.path.exists(excel_path):
            results["excel"] = db.import_from_excel(excel_path, user_id=current_user["id"])
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/contacts/add")
def add_manual_contacts_endpoint(req: AddContactsRequest, current_user: dict = Depends(get_current_user)):
    try:
        contacts_dict_list = [c.model_dump() for c in req.contacts]
        res = db.add_manual_contacts(
            contacts_dict_list,
            mode=req.mode,
            template_subject=req.template_subject,
            template_body=req.template_body,
            auto_approve=req.auto_approve,
            user_id=current_user["id"]
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profile")
def get_profile(current_user: dict = Depends(get_current_user)):
    # Map from database fields
    return {
        "full_name": current_user.get("full_name", ""),
        "phone_number": current_user.get("phone_number", ""),
        "linkedin_profile": current_user.get("linkedin_profile", ""),
        "current_designation": current_user.get("current_designation", ""),
        "experience_years": current_user.get("experience_years", ""),
        "industry_domain": current_user.get("industry_domain", ""),
        "target_role": current_user.get("target_role", ""),
        "achievements": current_user.get("achievements", []),
        "resume_pdf_path": current_user.get("resume_pdf_path", "")
    }

@app.post("/api/profile")
def update_profile(data: ProfileData, current_user: dict = Depends(get_current_user)):
    try:
        if not validate_safe_resume_path(data.resume_pdf_path):
            raise HTTPException(
                status_code=400, 
                detail="Invalid or unsafe resume path. Only PDF files are allowed, and access to system configuration files is blocked."
            )
        db.update_user_profile(current_user["id"], data.model_dump())
        return {"status": "success", "message": "Profile updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/env")
def get_env(current_user: dict = Depends(get_current_user)):
    google_tokens = db.get_oauth_tokens("google", user_id=current_user["id"])
    
    # Check user-specific configuration only (Never fallback to global server email/password to prevent security leaks)
    gemini_key = current_user.get("gemini_api_key") or ""
    sender_email = current_user.get("sender_email") or ""
    smtp_server = current_user.get("smtp_server") or ""
    smtp_port = current_user.get("smtp_port") or ""
    sender_password = current_user.get("sender_password") or ""
    sending_channel = current_user.get("sending_channel") or "smtp"

    return {
        "gemini_api_key_set": bool(gemini_key),
        "sender_email": sender_email,
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "sender_password_set": bool(sender_password),
        "sending_channel": sending_channel,
        "google_connected": google_tokens is not None,
        "google_email": google_tokens["email"] if google_tokens else None,
        "google_client_id_set": bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
    }

@app.post("/api/env")
def update_env(data: EnvData, current_user: dict = Depends(get_current_user)):
    try:
        # Preserve credentials if empty or masked (placeholder values)
        api_key = data.gemini_api_key
        if not api_key or api_key.startswith("••") or api_key == "STAY_SAME":
            api_key = current_user.get("gemini_api_key", "")
            
        password = data.sender_password
        if not password or password.startswith("••"):
            password = current_user.get("sender_password", "")
            
        sending_channel = data.sending_channel if data.sending_channel else current_user.get("sending_channel", "smtp")
            
        db.update_user_env(current_user["id"], {
            "gemini_api_key": api_key,
            "sender_email": data.sender_email,
            "sender_password": password,
            "smtp_server": data.smtp_server,
            "smtp_port": data.smtp_port,
            "sending_channel": sending_channel
        })
        
        return {"status": "success", "message": "Environment configuration updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/oauth/google/auth-url")
def get_google_auth_url(current_user: dict = Depends(get_current_user)):
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/oauth/google/callback")
    if not client_id:
        raise HTTPException(status_code=400, detail="GOOGLE_CLIENT_ID is not configured in .env")
        
    scopes = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email"
    
    # Pass user_id in the state parameter so callback maps it back to this user
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": str(current_user["id"])
    }
    
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return {"url": auth_url}

@app.get("/api/oauth/google/callback")
def google_oauth_callback(
    request: Request,
    code: str, 
    state: Optional[str] = None, 
    session_token: Optional[str] = Cookie(None)
):
    if not session_token:
        raise HTTPException(status_code=401, detail="Authentication session cookie missing.")
        
    user = db.get_user_by_session_token(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session token.")
        
    user_id = user["id"]
    
    # CSRF check: verify that state parameter matches user_id
    if state and int(state) != user_id:
        raise HTTPException(status_code=400, detail="OAuth state mismatch (potential CSRF).")
        
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/oauth/google/callback")
    
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Google client credentials not set.")
        
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    frontend_url = os.environ.get("FRONTEND_URL")
    if not frontend_url:
        host = request.headers.get("host", "")
        if "pitchdock.xyz" in host:
            frontend_url = "https://www.pitchdock.xyz"
        else:
            frontend_url = "http://localhost:3000"

    
    try:
        response = requests.post(token_url, data=payload)
        if response.status_code != 200:
            error_msg = urllib.parse.quote(f"Failed to retrieve tokens: {response.text}")
            return RedirectResponse(url=f"{frontend_url}/dashboard?error={error_msg}")
            
        res_data = response.json()
        access_token = res_data["access_token"]
        refresh_token = res_data.get("refresh_token")
        expires_in = res_data.get("expires_in", 3600)
        
        expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
        
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        userinfo_resp = requests.get(userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
        if userinfo_resp.status_code != 200:
            error_msg = urllib.parse.quote(f"Failed to fetch user profile: {userinfo_resp.text}")
            return RedirectResponse(url=f"{frontend_url}/dashboard?error={error_msg}")
            
        email = userinfo_resp.json().get("email")
        if not email:
            return RedirectResponse(url=f"{frontend_url}/dashboard?error=No+email+returned+from+Google")
            
        existing = db.get_oauth_tokens("google", user_id=user_id)
        final_refresh_token = refresh_token if refresh_token else (existing["refresh_token"] if existing else None)
        
        if not final_refresh_token:
            return RedirectResponse(url=f"{frontend_url}/dashboard?error=Please+disconnect+and+reconnect+to+allow+offline+access")
            
        db.save_oauth_tokens("google", email, access_token, final_refresh_token, expires_at, user_id=user_id)
        
        # Update user configuration channel to google
        user_profile = db.get_user_profile(user_id)
        db.update_user_env(user_id, {
            "gemini_api_key": user_profile.get("gemini_api_key", ""),
            "sender_email": user_profile.get("sender_email", ""),
            "sender_password": user_profile.get("sender_password", ""),
            "smtp_server": user_profile.get("smtp_server", ""),
            "smtp_port": user_profile.get("smtp_port", ""),
            "sending_channel": "google"
        })
            
        return RedirectResponse(url=f"{frontend_url}/dashboard?google_connected=true")
    except Exception as e:
        error_msg = urllib.parse.quote(f"Callback error: {str(e)}")
        return RedirectResponse(url=f"{frontend_url}/dashboard?error={error_msg}")

@app.post("/api/oauth/disconnect/{provider}")
def disconnect_oauth(provider: str, current_user: dict = Depends(get_current_user)):
    provider = provider.lower().strip()
    if provider != "google":
        raise HTTPException(status_code=400, detail="Invalid provider")
        
    db.delete_oauth_tokens("google", user_id=current_user["id"])
    
    db.update_user_env(current_user["id"], {
        "gemini_api_key": current_user.get("gemini_api_key", ""),
        "sender_email": current_user.get("sender_email", ""),
        "sender_password": current_user.get("sender_password", ""),
        "smtp_server": current_user.get("smtp_server", ""),
        "smtp_port": current_user.get("smtp_port", ""),
        "sending_channel": "smtp"
    })
        
    return {"status": "success", "message": "Successfully disconnected Google account."}

@app.get("/api/status")
def get_task_status(current_user: dict = Depends(get_current_user)):
    return get_user_task_state(current_user["id"])

@app.post("/api/status/stop")
def stop_task(current_user: dict = Depends(get_current_user)):
    state = get_user_task_state(current_user["id"])
    if state["status"] == "running":
        state["status"] = "idle"
        log_user_task_message(current_user["id"], "Task cancel request received.")
        return {"status": "success", "message": "Stopping background task..."}
    return {"status": "error", "message": "No active task running."}

@app.post("/api/generate")
def trigger_generation(req: GenerateRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    state = get_user_task_state(current_user["id"])
    if state["status"] == "running":
        raise HTTPException(status_code=400, detail=f"A background task '{state['type']}' is already running.")
        
    state.clear()
    state.update({
        "type": "generate",
        "status": "running",
        "total": 0,
        "current": 0,
        "success": 0,
        "failed": 0,
        "logs": [],
        "start_time": datetime.now().isoformat()
    })
    
    background_tasks.add_task(run_background_generation, req, current_user["id"])
    return {"status": "success", "message": "Email draft generation started in background"}

@app.post("/api/send")
def trigger_sending(req: SendRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    state = get_user_task_state(current_user["id"])
    if state["status"] == "running":
        raise HTTPException(status_code=400, detail=f"A background task '{state['type']}' is already running.")
        
    if req.delay < 5:
        req.delay = 5
        
    billing = db.get_billing_info(current_user["id"])
    tier = billing.get("plan_tier", "free")
    sent_today = billing.get("emails_sent_today", 0)
    
    limit_map = {
        "free": 5,
        "basic": 50,
        "standard": 200,
        "premium": 200
    }
    max_limit = limit_map.get(tier, 5)
    
    approved_contacts = db.get_contacts_by_status("approved", user_id=current_user["id"], limit=req.limit)
    if not approved_contacts:
        raise HTTPException(status_code=400, detail="No approved email drafts found to send.")
        
    to_send_count = len(approved_contacts)
    if sent_today + to_send_count > max_limit:
        raise HTTPException(
            status_code=400,
            detail=f"Daily email limit exceeded. The {tier.capitalize()} plan allows {max_limit} emails/day. You have already sent {sent_today} today and are trying to send {to_send_count} more. Please upgrade your plan."
        )
        
    state.clear()
    state.update({
        "type": "send",
        "status": "running",
        "total": 0,
        "current": 0,
        "success": 0,
        "failed": 0,
        "logs": [],
        "start_time": datetime.now().isoformat()
    })
    
    background_tasks.add_task(run_background_sending, req, current_user["id"])
    return {"status": "success", "message": "Email sending started in background"}

@app.post("/api/reset")
def reset_status(req: ResetRequest, current_user: dict = Depends(get_current_user)):
    try:
        count = db.reset_status(req.from_status, req.to_status, user_id=current_user["id"])
        return {"status": "success", "message": f"Successfully reset {count} contacts."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bulk-action")
def bulk_action(req: BulkActionRequest, current_user: dict = Depends(get_current_user)):
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        if req.action == "approve":
            target_status = "approved"
        elif req.action == "reject":
            target_status = "pending"
        elif req.action == "delete":
            target_status = None
        else:
            raise HTTPException(status_code=400, detail="Invalid action. Must be 'approve', 'reject', or 'delete'.")
            
        if req.ids:
            placeholders = ",".join(["?"] * len(req.ids))
            if target_status:
                cursor.execute(f"UPDATE contacts SET status = ? WHERE id IN ({placeholders}) AND user_id = ?", [target_status] + req.ids + [current_user["id"]])
            else:
                cursor.execute(f"DELETE FROM contacts WHERE id IN ({placeholders}) AND user_id = ?", req.ids + [current_user["id"]])
            affected = cursor.rowcount
        else:
            if req.action == "approve":
                cursor.execute("UPDATE contacts SET status = 'approved' WHERE status = 'drafted' AND user_id = ?", (current_user["id"],))
            elif req.action == "reject":
                cursor.execute("UPDATE contacts SET status = 'pending' WHERE status = 'drafted' AND user_id = ?", (current_user["id"],))
            elif req.action == "delete":
                cursor.execute("DELETE FROM contacts WHERE user_id = ?", (current_user["id"],))
            affected = cursor.rowcount
            
        conn.commit()
        conn.close()
        return {"status": "success", "affected_rows": affected}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/contact/{contact_id}")
def get_contact_detail(contact_id: int, current_user: dict = Depends(get_current_user)):
    try:
        conn = db.get_connection()
        conn.row_factory = sqlite3_row_factory
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contacts WHERE id = ? AND user_id = ?", (contact_id, current_user["id"]))
        row = cursor.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Contact not found.")
        return dict(row)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/contact/{contact_id}/edit")
def edit_contact_draft(contact_id: int, payload: dict = Body(...), current_user: dict = Depends(get_current_user)):
    try:
        subject = payload.get("subject")
        body = payload.get("body")
        status = payload.get("status", "approved")
        
        db.update_contact_draft(contact_id, subject, body, status=status, user_id=current_user["id"])
        return {"status": "success", "message": "Contact draft updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class BillingPlanRequest(BaseModel):
    plan_tier: str

class CreateOrderRequest(BaseModel):
    plan_tier: str
    billing_cycle: Optional[str] = "monthly"

class VerifyPaymentRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str
    plan_tier: str
    billing_cycle: Optional[str] = "monthly"

class ResumeRewriteRequest(BaseModel):
    company_name: str
    target_role: str

ADMIN_EMAILS = ["shubranshumishra22@gmail.com", "pitchdock.xyz@gmail.com"]

@app.get("/api/billing")
def get_billing(current_user: dict = Depends(get_current_user)):
    try:
        user_email = (current_user.get("email") or "").strip().lower()
        return db.get_billing_info(current_user["id"], email=user_email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/billing")
def update_billing(req: BillingPlanRequest, current_user: dict = Depends(get_current_user)):
    try:
        plan = req.plan_tier.lower()
        if plan not in ["free", "basic", "standard", "premium"]:
            raise HTTPException(status_code=400, detail="Invalid plan tier. Must be 'free', 'basic', 'standard', or 'premium'.")
        
        # Block direct upgrade to paid tiers
        if plan in ["basic", "standard", "premium"]:
            current_billing = db.get_billing_info(current_user["id"])
            if current_billing.get("plan_tier") != plan:
                raise HTTPException(
                    status_code=403, 
                    detail="Upgrading to paid tiers requires payment verification."
                )
        return db.update_billing_plan(req.plan_tier, user_id=current_user["id"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/payments/create-order")
def create_razorpay_order(req: CreateOrderRequest, current_user: dict = Depends(get_current_user)):
    try:
        plan = req.plan_tier.lower()
        cycle = (req.billing_cycle or "monthly").lower()
        if plan not in ["basic", "standard", "premium"]:
            raise HTTPException(status_code=400, detail="Invalid plan tier for payment.")
        if cycle not in ["monthly", "annual"]:
            raise HTTPException(status_code=400, detail="Invalid billing cycle. Must be 'monthly' or 'annual'.")
            
        price_map = {
            "monthly": {
                "basic": 49900,
                "standard": 49900
            },
            "annual": {
                "basic": 478800,   # ₹399 * 12 = ₹4788
                "standard": 478800
            }
        }
        amount = price_map[cycle][plan]
        
        key_id = os.environ.get("RAZORPAY_KEY_ID")
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
        
        if not key_id or not key_secret:
            raise HTTPException(
                status_code=500, 
                detail="Razorpay credentials not configured in backend environment (.env)"
            )
        
        from requests.auth import HTTPBasicAuth
        url = "https://api.razorpay.com/v1/orders"
        receipt_id = f"receipt_order_{current_user['id']}_{int(time.time())}"
        payload = {
            "amount": amount,
            "currency": "INR",
            "receipt": receipt_id
        }
        
        response = requests.post(url, json=payload, auth=HTTPBasicAuth(key_id, key_secret))
        if response.status_code != 200:
            raise HTTPException(
                status_code=400, 
                detail=f"Razorpay order creation failed: {response.text}"
            )
            
        order_data = response.json()
        return {
            "key": key_id,
            "amount": amount,
            "currency": "INR",
            "order_id": order_data["id"],
            "name": "PitchDock",
            "description": f"{req.plan_tier.capitalize()} AI Outreach Plan ({cycle.capitalize()})",
            "prefill": {
                "name": current_user.get("full_name", ""),
                "email": current_user.get("email", ""),
                "contact": current_user.get("phone_number", "")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/payments/verify")
def verify_razorpay_payment(req: VerifyPaymentRequest, current_user: dict = Depends(get_current_user)):
    try:
        cycle = (req.billing_cycle or "monthly").lower()
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
        if not key_secret:
            raise HTTPException(status_code=500, detail="Razorpay secret key not configured.")
            
        msg = f"{req.razorpay_order_id}|{req.razorpay_payment_id}"
        generated_sig = hmac.new(
            key_secret.encode('utf-8'),
            msg.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        price_map = {
            "monthly": {
                "basic": 49900,
                "standard": 49900
            },
            "annual": {
                "basic": 478800,
                "standard": 478800
            }
        }
        amount = price_map.get(cycle, price_map["monthly"]).get(req.plan_tier.lower(), 0)
        
        if not hmac.compare_digest(generated_sig, req.razorpay_signature):
            try:
                db.create_payment_record(
                    user_id=current_user["id"],
                    payment_id=req.razorpay_payment_id,
                    order_id=req.razorpay_order_id,
                    signature=req.razorpay_signature,
                    amount=amount,
                    plan_tier=req.plan_tier,
                    status="failed_signature_mismatch"
                )
            except Exception as db_err:
                print(f"Warning: Failed to write failed payment log to database: {db_err}")
            raise HTTPException(status_code=400, detail="Payment verification failed: invalid signature.")
            
        db.create_payment_record(
            user_id=current_user["id"],
            payment_id=req.razorpay_payment_id,
            order_id=req.razorpay_order_id,
            signature=req.razorpay_signature,
            amount=amount,
            plan_tier=req.plan_tier,
            status="success"
        )
        
        expires_in_days = 365 if cycle == "annual" else 30
        db.update_billing_plan(req.plan_tier, user_id=current_user["id"], expires_in_days=expires_in_days)
        
        return {"status": "success", "message": "Payment verified and subscription active."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/resume/rewrite")
def rewrite_resume_endpoint(req: ResumeRewriteRequest, current_user: dict = Depends(get_current_user)):
    try:
        billing = db.get_billing_info(current_user["id"])
        if billing.get("plan_tier") not in ["standard", "premium", "pro", "basic"]:
            raise HTTPException(
                status_code=403, 
                detail="Resume customization is exclusive to the Standard Pro plan (₹499/mo). Please upgrade."
            )
            
        rewrites_count = billing.get("resume_rewrites_count", 0)
        if rewrites_count >= 15:
            cached = db.get_cached_resume(req.company_name, user_id=current_user["id"])
            if cached:
                return {
                    "company": req.company_name,
                    "rewritten_content": cached,
                    "from_cache": True,
                    "count": rewrites_count
                }
            raise HTTPException(
                status_code=403, 
                detail="Monthly AI Resume rewrite limit (15/month) reached. Please contact support to purchase more credits."
            )
            
        cached = db.get_cached_resume(req.company_name, user_id=current_user["id"])
        if cached:
            return {
                "company": req.company_name,
                "rewritten_content": cached,
                "from_cache": True,
                "count": rewrites_count
            }
            
        # Call Gemini rewrite using user-specific api key
        profile = db.get_user_profile(current_user["id"])
        if not profile:
            profile = generator.load_candidate_profile()
        rewritten = generator.generate_resume_rewrite(req.company_name, req.target_role, profile)
        
        db.save_cached_resume(req.company_name, rewritten, user_id=current_user["id"])
        db.increment_resume_rewrites(user_id=current_user["id"])
        
        return {
            "company": req.company_name,
            "rewritten_content": rewritten,
            "from_cache": False,
            "count": rewrites_count + 1
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat-customize")
def chat_customize_endpoint(req: ChatCustomizeRequest, current_user: dict = Depends(get_current_user)):
    try:
        client = generator.get_gemini_client()
        
        contact_context = ""
        if req.recruiter_id:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name, company, title, email, personalized_subject, personalized_body FROM contacts WHERE id = ? AND user_id = ?", (req.recruiter_id, current_user["id"]))
            row = cursor.fetchone()
            conn.close()
            if row:
                contact = {
                    "name": row[0],
                    "company": row[1],
                    "title": row[2],
                    "email": row[3],
                    "subject": row[4] or req.template_subject,
                    "body": row[5] or req.template_body
                }
                contact_context = f"\nThe user is customizing a draft for a specific recruiter:\n- Recruiter Name: {contact['name']}\n- Company: {contact['company']}\n- Title: {contact['title']}\n- Email: {contact['email']}\n\nActive Draft Subject: \"{contact['subject']}\"\nActive Draft Body: \"{contact['body']}\"\n"

        jd_context = ""
        if req.job_description and req.job_description.strip():
            jd_context = f"\nTarget Job Description (JD) to match:\n\"\"\"{req.job_description.strip()}\"\"\"\n"

        system_instruction = """
You are an expert technical resume writer and cold outreach consultant.
Your job is to rewrite or adjust the user's outreach email subject, email body, and achievements based on their request message.
If a Job Description (JD) is provided, align the candidate's achievements and cold email messaging to sound highly relevant to that specific JD.
You must return a valid JSON object matching the ChatCustomizedOutput schema.
If a specific recruiter's draft context is provided, you should adjust the personalized draft directly, resolving placeholder variables (like {recruiter_name}, {company}, etc.) using the recruiter's name and details. Otherwise, ensure your response keeps template variables (like {recruiter_name}) intact.
If the user specifies parameters like the recruiter's name, company, or target role in their request message, parse them and populate:
- `updated_recruiter_name`: The recruiter's name (e.g. "Rohit") if specified.
- `updated_company`: The company name (e.g. "Google") if specified.
- `updated_target_role`: The job target role (e.g. "Senior Python Engineer") if specified.
The achievements list MUST have exactly 3 bullet points, customized to match the user's skills or target focus request.
"""
        prompt = f"""
User Request Message: "{req.message}"
Current Subject Template: "{req.template_subject}"
Current Body Template: "{req.template_body}"
Current Achievements list: {json.dumps(req.achievements)}
Target Role: "{req.target_role}"
{jd_context}
{contact_context}
 
Please adjust the templates and achievements lists, and return a response message explaining your changes.
"""
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ChatCustomizedOutput,
                system_instruction=system_instruction,
                temperature=0.7
            )
        )
        result_json = json.loads(response.text)
        
        # Check and update recruiter/contact in DB if parameters were parsed
        rec_name = result_json.get("updated_recruiter_name")
        rec_comp = result_json.get("updated_company")
        rec_id = req.recruiter_id
        
        if rec_id and (rec_name or rec_comp):
            conn = db.get_connection()
            cursor = conn.cursor()
            try:
                if rec_name and rec_comp:
                    cursor.execute("UPDATE contacts SET name = ?, company = ? WHERE id = ? AND user_id = ?", (rec_name, rec_comp, rec_id, current_user["id"]))
                elif rec_name:
                    cursor.execute("UPDATE contacts SET name = ? WHERE id = ? AND user_id = ?", (rec_name, rec_id, current_user["id"]))
                elif rec_comp:
                    cursor.execute("UPDATE contacts SET company = ? WHERE id = ? AND user_id = ?", (rec_comp, rec_id, current_user["id"]))
                conn.commit()
            finally:
                conn.close()
                
        # If recruiter_id is provided, save the customized subject and body drafts directly in the database
        if rec_id:
            db.update_contact_draft(rec_id, result_json["updated_subject"], result_json["updated_body"], status="approved", user_id=current_user["id"])

        # Check and update profile target role in DB if target role parameter was parsed
        target_role = result_json.get("updated_target_role")
        if target_role:
            db.update_user_profile(current_user["id"], {
                "target_role": target_role
            })
            
        return result_json
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/free-outreach")
def trigger_free_outreach(req: FreeOutreachRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    state = get_user_task_state(current_user["id"])
    if state["status"] == "running":
        raise HTTPException(status_code=400, detail=f"A background task '{state['type']}' is already running.")

    sender_email = current_user.get("sender_email") or os.environ.get("SENDER_EMAIL")
    sender_password = current_user.get("sender_password") or os.environ.get("SENDER_PASSWORD")
    sending_channel = current_user.get("sending_channel") or os.environ.get("SENDING_CHANNEL", "smtp")

    if sending_channel == "smtp" and not (sender_email and sender_password):
        raise HTTPException(status_code=400, detail="SMTP credentials are not configured. Please enter them in the settings page first.")
    elif sending_channel == "google" and not db.get_oauth_tokens("google", user_id=current_user["id"]):
        raise HTTPException(status_code=400, detail="Google Account is not connected. Please connect it in the settings page first.")

    if not validate_safe_resume_path(req.resume_pdf_path):
        raise HTTPException(
            status_code=400, 
            detail="Invalid or unsafe resume path. Only PDF files are allowed, and access to system configuration files is blocked."
        )

    # 1. Update candidate profile
    profile_data = {
        "full_name": req.full_name,
        "phone_number": req.phone_number,
        "linkedin_profile": req.linkedin_profile,
        "current_designation": req.current_designation,
        "experience_years": req.experience_years,
        "industry_domain": req.industry_domain,
        "target_role": req.target_role,
        "achievements": req.achievements,
        "resume_pdf_path": req.resume_pdf_path
    }
    try:
        db.update_user_profile(current_user["id"], profile_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update candidate profile: {str(e)}")

    # 2. Get up to 5 recruiters matching req.category
    category_filter = req.category if (req.category and req.category != "All") else None
    contacts = db.get_contacts(limit=50, offset=0, category=category_filter, status="pending", user_id=current_user["id"])
    
    if category_filter:
        if not contacts:
            raise HTTPException(
                status_code=400,
                detail=f"No pending contacts found in the selected target domain '{req.category}'."
            )
    else:
        if len(contacts) < 5:
            all_pending = db.get_contacts(limit=50, offset=0, status="pending", user_id=current_user["id"])
            for c in all_pending:
                if c not in contacts and len(contacts) < 5:
                    contacts.append(c)

        while len(contacts) < 5:
            idx = len(contacts) + 1
            mock_name = f"Recruiter {idx}"
            mock_email = f"recruiter{idx}@example.com"
            mock_company = f"Company {idx}"
            mock_title = "Talent Acquisition"
            try:
                cid = db.insert_contact(mock_name, mock_email, mock_company, mock_title, req.category, user_id=current_user["id"])
                mock_contact = {
                    "id": cid,
                    "name": mock_name,
                    "email": mock_email,
                    "company": mock_company,
                    "title": mock_title,
                    "category": req.category,
                    "status": "pending"
                }
            except sqlite3.IntegrityError:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, email, company, title, category, status FROM contacts WHERE email = ? AND user_id = ?", (mock_email, current_user["id"]))
                row = cursor.fetchone()
                conn.close()
                if row:
                    mock_contact = {
                        "id": row[0],
                        "name": row[1],
                        "email": row[2],
                        "company": row[3],
                        "title": row[4],
                        "category": row[5],
                        "status": row[6]
                    }
                else:
                    mock_contact = {
                        "id": idx * 10000,
                        "name": mock_name,
                        "email": f"recruiter{idx}_{int(time.time())}@example.com",
                        "company": mock_company,
                        "title": mock_title,
                        "category": req.category,
                        "status": "pending"
                    }
            contacts.append(mock_contact)

    target_contacts = contacts[:5]

    state.clear()
    state.update({
        "type": "generate",
        "status": "running",
        "total": len(target_contacts),
        "current": 0,
        "success": 0,
        "failed": 0,
        "logs": ["Starting automated 5-recruiter draft generation..."],
        "start_time": datetime.now().isoformat()
    })

    # 3. Generate drafts & set to approved using user client/profile
    for contact in target_contacts:
        subject = ""
        body = ""
        try:
            if req.strategy == "ai":
                client = generator.get_gemini_client()
                subject, body = generator.generate_email_draft(contact, profile_data, client)
            elif req.strategy == "template":
                exp_val = str(req.experience_years) if req.experience_years is not None else "some"
                ach1 = req.achievements[0] if len(req.achievements) > 0 else "built scalable software systems"
                ach2 = req.achievements[1] if len(req.achievements) > 1 else "optimized database queries"
                
                subject = req.template_subject.replace("{name}", contact["name"] or "Recruiter").replace("{recruiter_name}", contact["name"] or "Recruiter").replace("{Recruiter Name}", contact["name"] or "Recruiter").replace("{company}", contact["company"] or "your company").replace("{company_name}", contact["company"] or "your company").replace("{role}", req.target_role or "Software Engineer").replace("{my_name}", req.full_name or "Applicant")
                
                body = req.template_body.replace("{name}", contact["name"] or "Recruiter").replace("{recruiter_name}", contact["name"] or "Recruiter").replace("{Recruiter Name}", contact["name"] or "Recruiter").replace("{company}", contact["company"] or "your company").replace("{company_name}", contact["company"] or "your company").replace("{role}", req.target_role or "Software Engineer").replace("{experience}", exp_val).replace("{achievement_1}", ach1).replace("{achievement_2}", ach2).replace("{my_name}", req.full_name or "Applicant")
            else:  # scratch
                subject = req.template_subject
                body = req.template_body
            
            db.update_contact_draft(contact["id"], subject, body, user_id=current_user["id"])
            db.update_contact_status(contact["id"], "approved", user_id=current_user["id"])
            state["success"] += 1
            state["logs"].append(f"✓ Generated draft for {contact['name']} ({contact['email']})")
        except Exception as e:
            state["failed"] += 1
            state["logs"].append(f"✗ Failed draft for {contact['name']}: {str(e)}")
            db.update_contact_status(contact["id"], "failed", error_message=str(e), user_id=current_user["id"])
        
        state["current"] += 1

    approved_count = db.get_contacts_by_status("approved", limit=5, user_id=current_user["id"])
    if not approved_count:
        state["status"] = "failed"
        state["logs"].append("No drafts were successfully generated/approved. Aborting outreach sending.")
        raise HTTPException(status_code=500, detail="Failed to generate draft messages.")

    # 4. Trigger secure background SMTP sending
    state.clear()
    state.update({
        "type": "send",
        "status": "running",
        "total": len(approved_count),
        "current": 0,
        "success": 0,
        "failed": 0,
        "logs": ["AI Drafts generated. Queueing background SMTP transmitter..."],
        "start_time": datetime.now().isoformat()
    })
    
    background_tasks.add_task(run_background_sending, SendRequest(limit=5, delay=5), current_user["id"])

    return {
        "status": "success",
        "message": f"Orchestrated campaign initialized: generated {len(approved_count)} drafts and started delivery queue in the background.",
        "recipients": [{"name": r["name"], "email": r["email"], "company": r["company"]} for r in target_contacts]
    }

ACTIVE_ADMIN_TOKENS = set()

class AdminLoginRequest(BaseModel):
    email: str
    password: str

class AdminRecruiterAddRequest(BaseModel):
    contacts: List[ContactInput]
    seed_all_users: bool = True

@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest):
    if req.email == "pitchdock.xyz@gmail.com" and req.password == "@Hariom12345":
        token = secrets.token_hex(32)
        ACTIVE_ADMIN_TOKENS.add(token)
        return {"admin_token": token, "status": "success"}
    raise HTTPException(status_code=401, detail="Invalid admin credentials.")

@app.get("/api/admin/analytics")
def get_admin_analytics(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ")[1]
    if token not in ACTIVE_ADMIN_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid admin token.")
        
    try:
        metrics = db.get_admin_system_metrics()
        users = db.get_admin_users_list()
        payments = db.get_admin_payments_list()
        trends = db.get_admin_trends()
        return {
            "status": "success",
            "metrics": metrics,
            "users": users,
            "payments": payments,
            "trends": trends
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/recruiters/add")
def admin_add_recruiters(req: AdminRecruiterAddRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ")[1]
    if token not in ACTIVE_ADMIN_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid admin token.")

    if not req.contacts:
        raise HTTPException(status_code=400, detail="At least one recruiter contact is required.")

    try:
        contacts = [contact.model_dump() for contact in req.contacts]
        result = db.admin_add_recruiter_contacts(contacts, seed_all_users=req.seed_all_users)
        return {
            "status": "success",
            "message": "Recruiter contacts processed successfully.",
            "result": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/recruiters")
def admin_get_recruiters(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ")[1]
    if token not in ACTIVE_ADMIN_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid admin token.")

    try:
        recruiters = db.get_admin_recruiters_list(limit=500)
        return {
            "status": "success",
            "recruiters": recruiters
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def send_support_query_email(name: str, email: str, subject: str, message: str):
    sender_email = os.environ.get("SENDER_EMAIL", "pitchdock.xyz@gmail.com")
    sender_password = os.environ.get("SENDER_PASSWORD")
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = os.environ.get("SMTP_PORT", "587")
    
    mail_subject = f"[PITCHDOCK SUPPORT] {subject} (From: {name})"
    
    html_content = f"""
    <div style="font-family: sans-serif; max-width: 600px; padding: 20px; border: 1px solid #eaeaea; border-radius: 10px;">
      <h2 style="color: #10b981; border-bottom: 2px solid #eaeaea; padding-bottom: 10px; margin-top: 0;">New Support / Refund Query</h2>
      <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
        <tr>
          <td style="padding: 6px 0; font-weight: bold; width: 120px;">User Name:</td>
          <td>{name}</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; font-weight: bold;">User Email:</td>
          <td><a href="mailto:{email}">{email}</a></td>
        </tr>
        <tr>
          <td style="padding: 6px 0; font-weight: bold;">Subject:</td>
          <td>{subject}</td>
        </tr>
      </table>
      <div style="margin-top: 20px; padding: 15px; background-color: #f9f9f9; border-radius: 8px; border-left: 4px solid #10b981;">
        <p style="margin: 0; font-weight: bold; margin-bottom: 8px;">User Message:</p>
        <p style="margin: 0; white-space: pre-wrap; line-height: 1.5; color: #333333;">{message}</p>
      </div>
      <p style="margin-top: 25px; font-size: 12px; color: #888888;">This query was submitted via the PitchDock Contact Form.</p>
    </div>
    """
    
    if sender_email and sender_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = f'"PitchDock Support" <{sender_email}>'
            msg["To"] = "pitchdock.xyz@gmail.com"
            msg["Subject"] = mail_subject
            msg.attach(MIMEText(html_content, "html"))
            
            port = int(smtp_port)
            if port == 465:
                server = smtplib.SMTP_SSL(smtp_server, port)
            else:
                server = smtplib.SMTP(smtp_server, port)
                server.ehlo()
                server.starttls()
                server.ehlo()
                
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, "pitchdock.xyz@gmail.com", msg.as_string())
            server.quit()
            print("[SUPPORT EMAIL] Dispatch succeeded!")
            return True, None
        except Exception as e:
            print(f"[SUPPORT EMAIL ERROR] Dispatch failed: {str(e)}")
            return False, str(e)
    return False, "Support SMTP email server is not configured."

@app.post("/api/feedback")
def post_feedback(req: FeedbackRequest):
    if req.rating < 1 or req.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5.")
    try:
        db.save_feedback(req.name, req.rating, req.comment)
        return {"status": "success", "message": "Feedback saved successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/feedback")
def get_feedback_list():
    try:
        feedbacks = db.get_feedbacks()
        return {"status": "success", "feedbacks": feedbacks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/support-query")
def submit_support_query(req: SupportQueryRequest):
    try:
        success, err = send_support_query_email(req.name, req.email, req.subject, req.message)
        if not success:
            raise Exception(err or "Failed to send email via SMTP.")
        return {"status": "success", "message": "Your query has been submitted successfully. We will get back to you shortly!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process query: {str(e)}")

class AdminConfigUpdateRequest(BaseModel):
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    frontend_url: str

@app.get("/api/admin/config")
def get_admin_config(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ")[1]
    if token not in ACTIVE_ADMIN_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid admin token.")
        
    return {
        "status": "success",
        "google_client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "google_client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "google_redirect_uri": os.environ.get("GOOGLE_REDIRECT_URI", "https://www.pitchdock.xyz/api/oauth/google/callback"),
        "frontend_url": os.environ.get("FRONTEND_URL", "https://www.pitchdock.xyz")
    }

@app.post("/api/admin/config")
def update_admin_config(req: AdminConfigUpdateRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ")[1]
    if token not in ACTIVE_ADMIN_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid admin token.")
        
    try:
        # Load current environment lines
        env_lines = []
        if os.path.exists(".env"):
            with open(".env", "r") as f:
                env_lines = f.readlines()
                
        # Parse variables
        env_vars = {}
        for line in env_lines:
            line_str = line.strip()
            if line_str and not line_str.startswith("#") and "=" in line_str:
                k, v = line_str.split("=", 1)
                env_vars[k.strip()] = v.strip()
                
        # Update values
        env_vars["GOOGLE_CLIENT_ID"] = req.google_client_id.strip()
        env_vars["GOOGLE_CLIENT_SECRET"] = req.google_client_secret.strip()
        env_vars["GOOGLE_REDIRECT_URI"] = req.google_redirect_uri.strip()
        env_vars["FRONTEND_URL"] = req.frontend_url.strip()
        
        # Write back to .env
        with open(".env", "w") as f:
            f.write("# PitchDock Server Configuration\n")
            for k, v in env_vars.items():
                f.write(f"{k}={v}\n")
                
        # Reload environment variables in current process memory
        os.environ["GOOGLE_CLIENT_ID"] = req.google_client_id.strip()
        os.environ["GOOGLE_CLIENT_SECRET"] = req.google_client_secret.strip()
        os.environ["GOOGLE_REDIRECT_URI"] = req.google_redirect_uri.strip()
        os.environ["FRONTEND_URL"] = req.frontend_url.strip()
        
        return {"status": "success", "message": "Google OAuth configuration updated in environment memory successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update server configuration: {str(e)}")

@app.get("/")
def read_root():
    return {"message": "PitchDock API Backend is running successfully."}

if __name__ == "__main__":
    import uvicorn
    db.init_db()
    print("Starting server at http://127.0.0.1:8000")
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
