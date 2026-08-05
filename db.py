import sqlite3
import pandas as pd
import re
import os
import hashlib
import secrets
import json
from datetime import datetime, timedelta

DEFAULT_DB_PATH = "outreach.db"

def get_connection(db_path=DEFAULT_DB_PATH):
    return sqlite3.connect(db_path, timeout=30.0)

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}:{pw_hash.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        salt, pw_hash = hashed.split(":")
        test_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return secrets.compare_digest(pw_hash, test_hash.hex())
    except Exception:
        return False

_initialized_dbs = set()

def init_db(db_path=DEFAULT_DB_PATH):
    """Initializes the database and creates the tables if they don't exist."""
    global _initialized_dbs
    abs_path = os.path.abspath(db_path)
    if abs_path in _initialized_dbs and os.path.exists(db_path):
        return
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        
        # 1. Users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            full_name TEXT DEFAULT '',
            phone_number TEXT DEFAULT '',
            linkedin_profile TEXT DEFAULT '',
            current_designation TEXT DEFAULT '',
            experience_years TEXT DEFAULT '',
            industry_domain TEXT DEFAULT '',
            target_role TEXT DEFAULT '',
            achievements TEXT DEFAULT '[]',
            resume_pdf_path TEXT DEFAULT ''
        )
        """)

        for col in ["gemini_api_key", "sender_email", "sender_password", "smtp_server", "smtp_port", "sending_channel", "is_verified", "verification_token"]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

        # 2. Sessions table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL
        )
        """)
        
        # 3. Contacts table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            title TEXT,
            company TEXT,
            category TEXT,
            email TEXT,
            status TEXT DEFAULT 'pending', -- pending, drafted, approved, sent, failed
            personalized_subject TEXT,
            personalized_body TEXT,
            error_message TEXT,
            sent_at TEXT,
            user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(email, user_id)
        )
        """)
        
        # Try adding user_id to contacts if it doesn't exist
        try:
            cursor.execute("ALTER TABLE contacts ADD COLUMN user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE")
        except sqlite3.OperationalError:
            pass
        
        # 4. User billing table
        try:
            cursor.execute("PRAGMA table_info(user_billing)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "user_id" not in columns:
                cursor.execute("DROP TABLE user_billing")
        except sqlite3.OperationalError:
            pass

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_billing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            plan_tier TEXT DEFAULT 'free',
            resume_rewrites_count INTEGER DEFAULT 0,
            emails_sent_today INTEGER DEFAULT 0,
            last_usage_reset_date TEXT,
            subscription_expires_at TEXT
        )
        """)

        try:
            cursor.execute("ALTER TABLE user_billing ADD COLUMN subscription_expires_at TEXT")
        except sqlite3.OperationalError:
            pass

        # 5. User resume rewrites
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_resume_rewrites (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            company TEXT NOT NULL,
            rewritten_content TEXT,
            created_at TEXT,
            PRIMARY KEY (user_id, company)
        )
        """)

        # 6. User OAuth tokens
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_oauth_tokens (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            email TEXT,
            access_token TEXT,
            refresh_token TEXT,
            expires_at TEXT,
            PRIMARY KEY (user_id, provider)
        )
        """)

        # 7. User payments
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            payment_id TEXT UNIQUE,
            order_id TEXT,
            signature TEXT,
            amount INTEGER,
            plan_tier TEXT,
            status TEXT,
            created_at TEXT
        )
        """)

        # 8. Telegram account linking
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS telegram_links (
            telegram_user_id TEXT PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            telegram_username TEXT,
            telegram_first_name TEXT,
            linked_at TEXT NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS telegram_link_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )
        """)

        # Check if default user (ID = 1) exists, otherwise seed it
        cursor.execute("SELECT id FROM users WHERE id = 1")
        default_user = cursor.fetchone()
        if not default_user:
            dummy_hash = hash_password(secrets.token_hex(32))
            now_str = datetime.now().isoformat()
            cursor.execute("""
            INSERT INTO users (id, email, password_hash, created_at, full_name, target_role)
            VALUES (1, 'default@example.com', ?, ?, 'Default User', 'Software Engineer')
            """, (dummy_hash, now_str))
            
            # Load candidate profile json if exists and populate default user
            if os.path.exists("candidate_profile.json"):
                try:
                    with open("candidate_profile.json", "r") as f:
                        profile = json.load(f)
                    cursor.execute("""
                    UPDATE users SET
                        full_name = ?,
                        phone_number = ?,
                        linkedin_profile = ?,
                        current_designation = ?,
                        experience_years = ?,
                        industry_domain = ?,
                        target_role = ?,
                        achievements = ?,
                        resume_pdf_path = ?
                    WHERE id = 1
                    """, (
                        profile.get("full_name", "Default User"),
                        profile.get("phone_number", ""),
                        profile.get("linkedin_profile", ""),
                        profile.get("current_designation", ""),
                        str(profile.get("experience_years", "")),
                        profile.get("industry_domain", ""),
                        profile.get("target_role", ""),
                        json.dumps(profile.get("achievements", [])),
                        profile.get("resume_pdf_path", "")
                    ))
                except Exception:
                    pass

        # Ensure all contacts that have user_id NULL are set to user_id = 1
        cursor.execute("UPDATE contacts SET user_id = 1 WHERE user_id IS NULL")
        
        # Ensure default user has a billing record
        cursor.execute("SELECT COUNT(*) FROM user_billing WHERE user_id = 1")
        if cursor.fetchone()[0] == 0:
            today_str = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
            INSERT INTO user_billing (user_id, plan_tier, resume_rewrites_count, emails_sent_today, last_usage_reset_date)
            VALUES (1, 'free', 0, 0, ?)
            """, (today_str,))
            
        # 9. Feedbacks table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedbacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        
        cursor.execute("SELECT COUNT(*) FROM feedbacks")
        if cursor.fetchone()[0] == 0:
            initial_feedbacks = [
                ("Aravind Sharma", 5, "PitchDock completely changed my job search strategy. Landed 3 interviews in a week directly in my recruiter outbox!", "2026-07-18T10:00:00"),
                ("Sneha Reddy", 5, "The AI customizer parsed my resume and tailored my message so well. The standard tier is worth every rupee.", "2026-07-19T14:30:00"),
                ("Rahul Verma", 4, "Extremely useful tool for cold outreach. Setup was simple and the SMTP configuration works flawlessly.", "2026-07-19T18:15:00")
            ]
            cursor.executemany("""
                INSERT INTO feedbacks (name, rating, comment, created_at)
                VALUES (?, ?, ?, ?)
            """, initial_feedbacks)
            
        conn.commit()
        _initialized_dbs.add(abs_path)
    finally:
        conn.close()


def is_valid_email(email):
    if not isinstance(email, str):
        return False
    email = email.strip()
    # Simple regex for email validation
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return bool(re.match(pattern, email))

def import_from_excel(excel_path, user_id=1, db_path=DEFAULT_DB_PATH):
    """Parses the Excel file and imports new contacts into the database for a user."""
    init_db(db_path)
    
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found at: {excel_path}")
        
    xl = pd.ExcelFile(excel_path)
    if "HR Contacts" not in xl.sheet_names:
        raise ValueError("Sheet 'HR Contacts' not found in the Excel file.")
        
    df = xl.parse("HR Contacts")
    
    # Standardize column names (strip spaces, title case)
    df.columns = [str(c).strip() for c in df.columns]
    
    required_cols = ["Name", "Title", "Company", "Category", "Email"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}. Columns found: {df.columns.tolist()}")
            
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    added_count = 0
    ignored_count = 0
    invalid_count = 0
    
    for _, row in df.iterrows():
        email = row.get("Email")
        if pd.isna(email) or not is_valid_email(str(email).strip()):
            invalid_count += 1
            continue
            
        name = str(row.get("Name", "")).strip()
        title = str(row.get("Title", "")).strip() if not pd.isna(row.get("Title")) else ""
        company = str(row.get("Company", "")).strip() if not pd.isna(row.get("Company")) else ""
        category = str(row.get("Category", "")).strip() if not pd.isna(row.get("Category")) else ""
        email = str(email).strip().lower()
        
        # Clean up fallback empty names
        if not name or name.lower() == "nan":
            name = "HR Manager"
            
        try:
            cursor.execute("""
            INSERT INTO contacts (name, title, company, category, email, status, user_id)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """, (name, title, company, category, email, user_id))
            added_count += 1
        except sqlite3.IntegrityError:
            # Email already exists
            ignored_count += 1
            
    conn.commit()
    conn.close()
    
    return {
        "added": added_count,
        "ignored_duplicates": ignored_count,
        "invalid_or_empty": invalid_count
    }

def import_from_pdf(pdf_path="HR_Contact_List.pdf", user_id=1, seed_all_users=False, db_path=DEFAULT_DB_PATH):
    """Parses the PDF file and imports recruiter contacts into the database without duplicates."""
    init_db(db_path)
    
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found at: {pdf_path}")
        
    try:
        import PyPDF2
    except ImportError:
        raise RuntimeError("PyPDF2 is required for PDF parsing.")

    # Optional Excel lookup for enriched details if available
    excel_dict = {}
    excel_path = "kaamkibaatein_HR_Contact_Database.xlsx"
    if os.path.exists(excel_path):
        try:
            excel_df = pd.read_excel(excel_path, sheet_name="HR Contacts")
            for _, row in excel_df.iterrows():
                e = str(row.get("Email", "")).strip().lower()
                if "@" in e:
                    excel_dict[e] = {
                        "title": str(row.get("Title", "")).strip() if not pd.isna(row.get("Title")) else "",
                        "company": str(row.get("Company", "")).strip() if not pd.isna(row.get("Company")) else "",
                        "category": str(row.get("Category", "")).strip() if not pd.isna(row.get("Category")) else ""
                    }
        except Exception:
            pass

    reader = PyPDF2.PdfReader(pdf_path)
    contacts = []
    seen_emails = set()
    invalid_count = 0
    
    for page in reader.pages:
        text = page.extract_text()
        if not text:
            continue
        for line in text.split("\n"):
            line_str = line.strip()
            if not line_str or line_str.startswith("SNo") or "Name Email Title Company" in line_str:
                continue
            
            m = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', line_str)
            if not m:
                invalid_count += 1
                continue
                
            email = m.group(1).lower().strip()
            if not is_valid_email(email):
                invalid_count += 1
                continue
                
            if email in seen_emails:
                continue
            seen_emails.add(email)
            
            before = line_str[:m.start()].strip()
            after = line_str[m.end():].strip()
            name = re.sub(r'^\d+\s*', '', before).strip()
            if not name or name.lower() == 'nan':
                name = 'HR Manager'
                
            if email in excel_dict:
                title = excel_dict[email]["title"] or after
                company = excel_dict[email]["company"] or ""
                category = excel_dict[email]["category"] or "Recruiter"
            else:
                words = after.split()
                if len(words) > 1:
                    company = words[-1]
                    title = " ".join(words[:-1])
                else:
                    title = after
                    company = ""
                category = "Recruiter"
                
            contacts.append({
                "name": name,
                "email": email,
                "title": title,
                "company": company,
                "category": category
            })
            
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    if seed_all_users:
        cursor.execute("SELECT id FROM users ORDER BY id ASC")
        target_user_ids = [row[0] for row in cursor.fetchall()]
        if not target_user_ids:
            target_user_ids = [user_id]
    else:
        target_user_ids = [user_id]
        
    added_count = 0
    ignored_count = 0
    
    for uid in target_user_ids:
        for c in contacts:
            try:
                cursor.execute("""
                INSERT INTO contacts (name, title, company, category, email, status, user_id)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """, (c["name"], c["title"], c["company"], c["category"], c["email"], uid))
                added_count += 1
            except sqlite3.IntegrityError:
                ignored_count += 1
                
    conn.commit()
    conn.close()
    
    return {
        "added": added_count,
        "ignored_duplicates": ignored_count,
        "invalid_or_empty": invalid_count,
        "total_contacts_parsed": len(contacts),
        "users_updated": len(target_user_ids)
    }


def get_stats(user_id=1, db_path=DEFAULT_DB_PATH):
    """Gives statistics of contacts in the database for a user."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Status breakdown
    cursor.execute("SELECT status, COUNT(*) FROM contacts WHERE user_id = ? GROUP BY status", (user_id,))
    status_counts = dict(cursor.fetchall())
    
    # Category breakdown
    cursor.execute("SELECT category, COUNT(*) FROM contacts WHERE user_id = ? GROUP BY category", (user_id,))
    category_counts = dict(cursor.fetchall())
    
    cursor.execute("SELECT COUNT(*) FROM contacts WHERE user_id = ?", (user_id,))
    total = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total": total,
        "status_breakdown": status_counts,
        "category_breakdown": category_counts
    }

def get_contacts_by_status(status, limit=None, category=None, user_id=1, db_path=DEFAULT_DB_PATH):
    """Retrieves contacts by status and user_id with optional limit and category filters."""
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM contacts WHERE status = ? AND user_id = ?"
    params = [status, user_id]
    
    if category:
        query += " AND category = ?"
        params.append(category)
        
    query += " ORDER BY id ASC"
    
    if limit:
        query += " LIMIT ?"
        params.append(limit)
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_contacts(limit=50, offset=0, status=None, category=None, user_id=1, db_path=DEFAULT_DB_PATH):
    """Fetches contacts from the database with pagination, status, and category filters for a user."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM contacts WHERE user_id = ?"
    params = [user_id]
    
    if status:
        query += " AND status = ?"
        params.append(status)
    if category:
        query += " AND category = ?"
        params.append(category)
        
    query += " ORDER BY id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def insert_contact(name, email, company, title, category, status="pending", user_id=1, db_path=DEFAULT_DB_PATH):
    """Inserts a single contact and returns its ID."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO contacts (name, email, company, title, category, status, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, email, company, title, category, status, user_id))
        cid = cursor.lastrowid
        conn.commit()
        return cid
    finally:
        conn.close()

def copy_master_contacts_to_user(user_id, db_path=DEFAULT_DB_PATH):
    """Copies default/master contacts from user 1 into another user's recruiter queue."""
    if int(user_id) == 1:
        return {"added": 0, "ignored_duplicates": 0}

    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT name, title, company, category, email, status, personalized_subject, personalized_body, error_message, sent_at
        FROM contacts
        WHERE user_id = 1
        ORDER BY id ASC
        """)
        master_contacts = cursor.fetchall()

        added = 0
        ignored = 0
        for contact in master_contacts:
            try:
                cursor.execute("""
                INSERT INTO contacts (
                    name, title, company, category, email, status,
                    personalized_subject, personalized_body, error_message, sent_at, user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    contact["name"],
                    contact["title"],
                    contact["company"],
                    contact["category"],
                    contact["email"],
                    "pending" if contact["status"] == "sent" else contact["status"],
                    contact["personalized_subject"],
                    contact["personalized_body"],
                    contact["error_message"],
                    None,
                    user_id
                ))
                added += 1
            except sqlite3.IntegrityError:
                ignored += 1

        conn.commit()
        return {"added": added, "ignored_duplicates": ignored}
    finally:
        conn.close()

def admin_add_recruiter_contacts(contacts_list, seed_all_users=True, db_path=DEFAULT_DB_PATH):
    """Adds recruiter contacts to the master pool and optionally every existing user's queue."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        if seed_all_users:
            cursor.execute("SELECT id FROM users ORDER BY id ASC")
            target_user_ids = [row[0] for row in cursor.fetchall()]
        else:
            target_user_ids = [1]

        if 1 not in target_user_ids:
            target_user_ids.insert(0, 1)

        valid_contacts = []
        invalid_contacts = []
        for raw in contacts_list:
            email = str(raw.get("email") or "").strip().lower()
            if not is_valid_email(email):
                invalid_contacts.append(raw)
                continue

            name = str(raw.get("name") or "").strip()
            if not name:
                name = "HR Manager"

            valid_contacts.append({
                "name": name,
                "title": str(raw.get("title") or "").strip(),
                "company": str(raw.get("company") or "").strip(),
                "category": str(raw.get("category") or "").strip(),
                "email": email,
            })

        inserted_rows = 0
        duplicate_rows = 0
        for user_id in target_user_ids:
            for contact in valid_contacts:
                try:
                    cursor.execute("""
                    INSERT INTO contacts (name, title, company, category, email, status, user_id)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?)
                    """, (
                        contact["name"],
                        contact["title"],
                        contact["company"],
                        contact["category"],
                        contact["email"],
                        user_id
                    ))
                    inserted_rows += 1
                except sqlite3.IntegrityError:
                    duplicate_rows += 1

        conn.commit()
        return {
            "contacts_received": len(contacts_list),
            "valid_contacts": len(valid_contacts),
            "invalid_contacts": len(invalid_contacts),
            "target_users": len(target_user_ids),
            "inserted_rows": inserted_rows,
            "duplicate_rows": duplicate_rows,
        }
    finally:
        conn.close()

def update_contact_draft(contact_id, subject, body, status="drafted", user_id=1, db_path=DEFAULT_DB_PATH):
    """Updates the generated subject and body for a contact."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE contacts 
    SET personalized_subject = ?, personalized_body = ?, status = ?, error_message = NULL
    WHERE id = ? AND user_id = ?
    """, (subject, body, status, contact_id, user_id))
    conn.commit()
    conn.close()

def update_contact_status(contact_id, status, error_message=None, sent_at=None, user_id=1, db_path=DEFAULT_DB_PATH):
    """Updates a contact's outreach status."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE contacts 
    SET status = ?, error_message = ?, sent_at = ?
    WHERE id = ? AND user_id = ?
    """, (status, error_message, sent_at, contact_id, user_id))
    conn.commit()
    conn.close()

def reset_status(from_status, to_status="pending", user_id=1, db_path=DEFAULT_DB_PATH):
    """Resets contacts from one status to another for a user."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE contacts SET status = ? WHERE status = ? AND user_id = ?", (to_status, from_status, user_id))
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count

def add_manual_contacts(contacts_list, mode, template_subject=None, template_body=None, auto_approve=False, user_id=1, db_path=DEFAULT_DB_PATH):
    """
    Inserts a list of manually entered contacts for a user.
    If mode is 'template', personalizes the template and sets status to 'approved' or 'drafted'.
    If mode is 'scratch', sets status to 'drafted' with empty or template-based draft.
    If mode is 'ai', sets status to 'pending'.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Load candidate profile for template replacements
    profile = {}
    if mode == "template":
        try:
            profile = get_user_profile(user_id, db_path)
            if not profile:
                import generator
                profile = generator.load_candidate_profile()
        except Exception:
            pass
            
    added_count = 0
    ignored_count = 0
    invalid_count = 0
    
    for contact in contacts_list:
        email = contact.get("email")
        if not email or not is_valid_email(str(email).strip()):
            invalid_count += 1
            continue
            
        email = str(email).strip().lower()
        name = contact.get("name") or ""
        name = str(name).strip()
        if not name:
            name = "HR Manager"
            
        title = str(contact.get("title") or "").strip()
        company = str(contact.get("company") or "").strip()
        category = str(contact.get("category") or "").strip()
        
        status = "pending"
        subject = None
        body = None
        
        if mode == "template":
            # Simple template replacement
            first_name = name.split()[0] if name and name.lower() != "hr manager" else "Hiring Team"
            if first_name.lower() in ["mr.", "ms.", "dr.", "mrs."]:
                parts = name.split()
                first_name = parts[1] if len(parts) > 1 else "Hiring Team"
                
            subj_tpl = template_subject or ""
            body_tpl = template_body or ""
            
            # Placeholders lookup
            replacements = {
                "{name}": name,
                "{Name}": name,
                "{recruiter_name}": name,
                "{Recruiter Name}": name,
                "{first_name}": first_name,
                "{First Name}": first_name,
                "{company}": company if company else "your company",
                "{Company}": company if company else "your company",
                "{title}": title if title else "Hiring Manager",
                "{Title}": title if title else "Hiring Manager",
                "{role}": profile.get("target_role", "opportunities"),
                "{Role}": profile.get("target_role", "opportunities"),
                "{my_name}": profile.get("full_name", ""),
                "{My Name}": profile.get("full_name", ""),
                "{my_phone}": profile.get("phone_number", ""),
                "{My Phone}": profile.get("phone_number", ""),
                "{my_linkedin}": profile.get("linkedin_profile", ""),
                "{My LinkedIn}": profile.get("linkedin_profile", ""),
            }
            
            subject = subj_tpl
            body = body_tpl
            for k, v in replacements.items():
                subject = subject.replace(k, v)
                body = body.replace(k, v)
                
            status = "approved" if auto_approve else "drafted"
            
        elif mode == "scratch":
            # If scratch, we create an empty draft so they can edit it
            subject = ""
            body = ""
            status = "drafted"
            
        elif mode == "ai":
            status = "pending"
            
        try:
            cursor.execute("""
            INSERT INTO contacts (name, title, company, category, email, status, personalized_subject, personalized_body, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, title, company, category, email, status, subject, body, user_id))
            added_count += 1
        except sqlite3.IntegrityError:
            ignored_count += 1
            
    conn.commit()
    conn.close()
    
    return {
        "added": added_count,
        "ignored_duplicates": ignored_count,
        "invalid_or_empty": invalid_count
    }

ADMIN_EMAILS = ["shubranshumishra22@gmail.com", "pitchdock.xyz@gmail.com"]

def get_billing_info(user_id=1, email=None, db_path=DEFAULT_DB_PATH):
    """Retrieves current user billing info. Admin emails get standard paid tier; all other users default to free tier unless paid."""
    init_db(db_path)
    
    # Check if user email is an admin email
    if email:
        email_clean = email.strip().lower()
        if email_clean in ADMIN_EMAILS:
            return {
                "user_id": user_id,
                "plan_tier": "standard",
                "resume_rewrites_count": 0,
                "emails_sent_today": 0,
                "last_usage_reset_date": datetime.now().strftime("%Y-%m-%d"),
                "subscription_expires_at": None
            }
            
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM user_billing WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    # Check user email from users table
    cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
    u_row = cursor.fetchone()
    conn.close()
    
    u_email = (u_row["email"] if u_row and "email" in u_row.keys() else (u_row[0] if u_row else "")).strip().lower()
    
    if u_email in ADMIN_EMAILS:
        return {
            "user_id": user_id,
            "plan_tier": "standard",
            "resume_rewrites_count": 0,
            "emails_sent_today": 0,
            "last_usage_reset_date": datetime.now().strftime("%Y-%m-%d"),
            "subscription_expires_at": None
        }
    
    if row:
        billing = dict(row)
        
        # Ensure non-admin users do not have unearned premium/paid tier
        # Check user_payments table for active paid transaction
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_payments WHERE user_id = ? AND status IN ('captured', 'success')", (user_id,))
        has_paid = cursor.fetchone()[0] > 0
        conn.close()
        
        # Check subscription expiration
        expires_at_str = billing.get("subscription_expires_at")
        is_active_subscription = False
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.now() <= expires_at:
                    is_active_subscription = True
                else:
                    update_billing_plan("free", user_id=user_id, db_path=db_path)
                    billing["plan_tier"] = "free"
            except Exception as exp_err:
                print(f"Error checking subscription expiration: {exp_err}")
                
        if not has_paid and not is_active_subscription and billing.get("plan_tier") != "free":
            billing["plan_tier"] = "free"
            update_billing_plan("free", user_id=user_id, db_path=db_path)
                
        return billing
    else:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute("""
        INSERT INTO user_billing (user_id, plan_tier, resume_rewrites_count, emails_sent_today, last_usage_reset_date)
        VALUES (?, 'free', 0, 0, ?)
        """, (user_id, today_str))
        conn.commit()
        conn.close()
        return {"plan_tier": "free", "resume_rewrites_count": 0, "emails_sent_today": 0, "user_id": user_id}

def update_billing_plan(plan_tier, user_id=1, expires_in_days=None, db_path=DEFAULT_DB_PATH):
    """Simulates updating the subscription tier for a user."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    expires_at = None
    if expires_in_days is None and plan_tier.lower() != "free":
        expires_in_days = 30
    if expires_in_days:
        expires_at = (datetime.now() + timedelta(days=expires_in_days)).isoformat()
        
    cursor.execute("""
    INSERT OR REPLACE INTO user_billing (user_id, plan_tier, resume_rewrites_count, emails_sent_today, last_usage_reset_date, subscription_expires_at)
    VALUES (?, ?, 0, 0, ?, ?)
    """, (user_id, plan_tier.lower(), today_str, expires_at))
    conn.commit()
    conn.close()
    return {"status": "success", "plan_tier": plan_tier.lower(), "subscription_expires_at": expires_at}

def create_payment_record(user_id, payment_id, order_id, signature, amount, plan_tier, status, db_path=DEFAULT_DB_PATH):
    """Creates a payment record in user_payments table."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO user_payments (user_id, payment_id, order_id, signature, amount, plan_tier, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, payment_id, order_id, signature, amount, plan_tier.lower(), status, created_at))
    conn.commit()
    conn.close()
    return True

def increment_resume_rewrites(user_id=1, db_path=DEFAULT_DB_PATH):
    """Increments the count of distinct resume rewrites."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE user_billing SET resume_rewrites_count = resume_rewrites_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def increment_emails_sent(count=1, user_id=1, db_path=DEFAULT_DB_PATH):
    """Increments the daily emails sent count."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE user_billing SET emails_sent_today = emails_sent_today + ? WHERE user_id = ?", (count, user_id))
    conn.commit()
    conn.close()

def get_cached_resume(company, user_id=1, db_path=DEFAULT_DB_PATH):
    """Returns the cached customized resume content for a company and user if exists."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT rewritten_content FROM user_resume_rewrites WHERE company = ? AND user_id = ?", (company.strip().lower(), user_id))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_cached_resume(company, content, user_id=1, db_path=DEFAULT_DB_PATH):
    """Caches the tailored resume content for a company and user."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
    INSERT OR REPLACE INTO user_resume_rewrites (user_id, company, rewritten_content, created_at)
    VALUES (?, ?, ?, ?)
    """, (user_id, company.strip().lower(), content, today_str))
    conn.commit()
    conn.close()

def save_oauth_tokens(provider, email, access_token, refresh_token, expires_at, user_id=1, db_path=DEFAULT_DB_PATH):
    """Saves or updates OAuth tokens for a provider and user."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO user_oauth_tokens (user_id, provider, email, access_token, refresh_token, expires_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, provider, email, access_token, refresh_token, expires_at))
    conn.commit()
    conn.close()

def get_oauth_tokens(provider, user_id=1, db_path=DEFAULT_DB_PATH):
    """Retrieves OAuth tokens for a provider and user."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_oauth_tokens WHERE provider = ? AND user_id = ?", (provider, user_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_oauth_tokens(provider, user_id=1, db_path=DEFAULT_DB_PATH):
    """Deletes OAuth credentials for a provider and user."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_oauth_tokens WHERE provider = ? AND user_id = ?", (provider, user_id))
    conn.commit()
    conn.close()

def create_user(email, password, verification_token=None, db_path=DEFAULT_DB_PATH):
    """Creates a new user with hashed password."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    password_hash = hash_password(password)
    created_at = datetime.now().isoformat()
    try:
        cursor.execute("""
        INSERT INTO users (email, password_hash, created_at, is_verified, verification_token)
        VALUES (?, ?, ?, ?, ?)
        """, (email.strip().lower(), password_hash, created_at, '0', verification_token))
        user_id = cursor.lastrowid
        conn.commit()
        
        # Initialize default billing tier
        cursor.execute("""
        INSERT INTO user_billing (user_id, plan_tier, resume_rewrites_count, emails_sent_today, last_usage_reset_date)
        VALUES (?, 'free', 0, 0, ?)
        """, (user_id, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
        
        # Auto-import real recruiter contacts from Excel or PDF if exists
        excel_path = "kaamkibaatein_HR_Contact_Database.xlsx"
        pdf_path = "HR_Contact_List.pdf"
        imported_any = False
        if os.path.exists(excel_path):
            try:
                import_from_excel(excel_path, user_id=user_id, db_path=db_path)
                imported_any = True
            except Exception as import_err:
                print(f"[SIGNUP SEED EXCEL ERROR]: {str(import_err)}")
        if os.path.exists(pdf_path):
            try:
                import_from_pdf(pdf_path, user_id=user_id, seed_all_users=False, db_path=db_path)
                imported_any = True
            except Exception as import_err:
                print(f"[SIGNUP SEED PDF ERROR]: {str(import_err)}")
        if not imported_any:
            # Fallback to 10 default mock recruiters if neither file is found
            conn = get_connection(db_path)
            cursor = conn.cursor()
            default_contacts = [
                ("Sarah Jenkins", "s.jenkins@apple.com", "Apple Inc.", "Lead Technical Recruiter", "FAANG", "pending"),
                ("David Miller", "d.miller@google.com", "Google", "Tech Sourcing Manager", "FAANG", "pending"),
                ("Jessica Taylor", "j.taylor@meta.com", "Meta", "Recruiting Coordinator", "FAANG", "pending"),
                ("Michael Brown", "m.brown@amazon.com", "Amazon", "Software Sourcing Specialist", "FAANG", "pending"),
                ("Emily Davis", "e.davis@netflix.com", "Netflix", "Talent Acquisition Lead", "FAANG", "pending"),
                ("Alex Rivera", "a.rivera@microsoft.com", "Microsoft", "Senior Talent Partner", "FAANG", "locked"),
                ("Sophia Chen", "s.chen@stripe.com", "Stripe", "Technical Recruiter", "Fintech", "locked"),
                ("Marcus Aurelius", "m.aurelius@openai.com", "OpenAI", "Staff Recruiting Lead", "AI", "locked"),
                ("Emma Watson", "e.watson@airbnb.com", "Airbnb", "University Recruiter", "Travel", "locked"),
                ("John Wick", "j.wick@nvidia.com", "NVIDIA", "Strategic Sourcing Partner", "Hardware", "locked")
            ]
            for name, email_addr, company, title, category, status in default_contacts:
                cursor.execute("""
                INSERT INTO contacts (name, email, company, title, category, status, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (name, email_addr, company, title, category, status, user_id))
            conn.commit()
            conn.close()

        try:
            copy_master_contacts_to_user(user_id, db_path=db_path)
        except Exception as copy_err:
            print(f"[SIGNUP MASTER CONTACT COPY ERROR]: {str(copy_err)}")

        return {"status": "success", "user_id": user_id, "email": email}
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError("Email already registered")
    except Exception as e:
        conn.close()
        raise e

def verify_user(email, password, db_path=DEFAULT_DB_PATH):
    """Verifies user credentials and returns user details."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password_hash, is_verified FROM users WHERE email = ?", (email.strip().lower(),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    
    user_id, user_email, password_hash, is_verified = row
    if verify_password(password, password_hash):
        return {"id": user_id, "email": user_email, "is_verified": is_verified}
    return None

def verify_user_token(token, db_path=DEFAULT_DB_PATH):
    """Verifies user's token, updates is_verified = '1' and clears the token."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, email FROM users WHERE verification_token = ?", (token,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        
        user_id, email = row
        cursor.execute("""
        UPDATE users 
        SET is_verified = '1', verification_token = NULL 
        WHERE id = ?
        """, (user_id,))
        conn.commit()
        conn.close()
        return {"id": user_id, "email": email}
    except Exception as e:
        conn.close()
        raise e

def create_session(user_id, db_path=DEFAULT_DB_PATH):
    """Creates a session token for a user that expires in 7 days."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    token = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(days=7)).isoformat()
    cursor.execute("""
    INSERT INTO sessions (token, user_id, expires_at)
    VALUES (?, ?, ?)
    """, (token, user_id, expires_at))
    conn.commit()
    conn.close()
    return token, expires_at

def get_user_by_session_token(token, db_path=DEFAULT_DB_PATH):
    """Validates and returns the user associated with the session token."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
    SELECT users.* FROM sessions
    JOIN users ON sessions.user_id = users.id
    WHERE sessions.token = ? AND sessions.expires_at > ?
    """, (token, datetime.now().isoformat()))
    row = cursor.fetchone()
    conn.close()
    if row:
        user = dict(row)
        user.pop("password_hash", None)
        try:
            user["achievements"] = json.loads(user["achievements"])
        except Exception:
            user["achievements"] = []
        return user
    return None

def delete_session(token, db_path=DEFAULT_DB_PATH):
    """Deletes a session token (logout)."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()

def create_telegram_link_token(user_id, expires_minutes=15, db_path=DEFAULT_DB_PATH):
    """Creates a short-lived one-time code for linking a Telegram account."""
    init_db(db_path)
    token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
    expires_at = (datetime.now() + timedelta(minutes=expires_minutes)).isoformat()
    
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM telegram_link_tokens WHERE user_id = ? OR expires_at <= ?", (user_id, datetime.now().isoformat()))
        cursor.execute("""
        INSERT INTO telegram_link_tokens (token, user_id, expires_at, used_at)
        VALUES (?, ?, ?, NULL)
        """, (token, user_id, expires_at))
        conn.commit()
        return {"token": token, "expires_at": expires_at}
    finally:
        conn.close()

def link_telegram_user(token, telegram_user_id, telegram_username="", telegram_first_name="", db_path=DEFAULT_DB_PATH):
    """Consumes a one-time code and links a Telegram user to an existing PitchDock user."""
    init_db(db_path)
    normalized_token = (token or "").strip().upper()
    now_str = datetime.now().isoformat()
    
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT token, user_id, expires_at, used_at
        FROM telegram_link_tokens
        WHERE token = ?
        """, (normalized_token,))
        row = cursor.fetchone()
        if not row:
            return None, "Invalid link code. Generate a fresh code from the PitchDock dashboard."
        if row["used_at"]:
            return None, "That link code has already been used. Generate a fresh code from the PitchDock dashboard."
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return None, "That link code has expired. Generate a fresh code from the PitchDock dashboard."
            
        cursor.execute("SELECT id, email, is_verified FROM users WHERE id = ?", (row["user_id"],))
        user = cursor.fetchone()
        if not user:
            return None, "The PitchDock account for this code no longer exists."
        if user["is_verified"] == "0" or user["is_verified"] == 0:
            return None, "Please verify your PitchDock email before linking Telegram."
            
        cursor.execute("""
        INSERT OR REPLACE INTO telegram_links (
            telegram_user_id, user_id, telegram_username, telegram_first_name, linked_at
        )
        VALUES (?, ?, ?, ?, ?)
        """, (str(telegram_user_id), row["user_id"], telegram_username or "", telegram_first_name or "", now_str))
        cursor.execute("UPDATE telegram_link_tokens SET used_at = ? WHERE token = ?", (now_str, normalized_token))
        conn.commit()
        return {"user_id": row["user_id"], "email": user["email"]}, None
    finally:
        conn.close()

def get_user_by_telegram_id(telegram_user_id, db_path=DEFAULT_DB_PATH):
    """Returns a PitchDock user linked to a Telegram user id."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT users.* FROM telegram_links
        JOIN users ON telegram_links.user_id = users.id
        WHERE telegram_links.telegram_user_id = ?
        """, (str(telegram_user_id),))
        row = cursor.fetchone()
        if not row:
            return None
        user = dict(row)
        user.pop("password_hash", None)
        try:
            user["achievements"] = json.loads(user["achievements"])
        except Exception:
            user["achievements"] = []
        return user
    finally:
        conn.close()

def unlink_telegram_user(telegram_user_id, db_path=DEFAULT_DB_PATH):
    """Unlinks a Telegram account from PitchDock."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM telegram_links WHERE telegram_user_id = ?", (str(telegram_user_id),))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

def get_user_profile(user_id, db_path=DEFAULT_DB_PATH):
    """Retrieves user details without session validation."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        user = dict(row)
        user.pop("password_hash", None)
        try:
            user["achievements"] = json.loads(user["achievements"])
        except Exception:
            user["achievements"] = []
        return user
    return None

def update_user_profile(user_id, profile_data, db_path=DEFAULT_DB_PATH):
    """Updates candidate profile fields for a user."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE users SET
        full_name = ?,
        phone_number = ?,
        linkedin_profile = ?,
        current_designation = ?,
        experience_years = ?,
        industry_domain = ?,
        target_role = ?,
        achievements = ?,
        resume_pdf_path = ?
    WHERE id = ?
    """, (
        profile_data.get("full_name", ""),
        profile_data.get("phone_number", ""),
        profile_data.get("linkedin_profile", ""),
        profile_data.get("current_designation", ""),
        str(profile_data.get("experience_years", "")),
        profile_data.get("industry_domain", ""),
        profile_data.get("target_role", ""),
        json.dumps(profile_data.get("achievements", [])),
        profile_data.get("resume_pdf_path", ""),
        user_id
    ))
    conn.commit()
    conn.close()

def update_user_env(user_id, env_data, db_path=DEFAULT_DB_PATH):
    """Updates SMTP and Gemini API credentials for a user."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE users SET
        gemini_api_key = ?,
        sender_email = ?,
        sender_password = ?,
        smtp_server = ?,
        smtp_port = ?,
        sending_channel = ?
    WHERE id = ?
    """, (
        env_data.get("gemini_api_key", ""),
        env_data.get("sender_email", ""),
        env_data.get("sender_password", ""),
        env_data.get("smtp_server", "smtp.gmail.com"),
        str(env_data.get("smtp_port", "587")),
        env_data.get("sending_channel", "smtp"),
        user_id
    ))
    conn.commit()
    conn.close()

def get_admin_users_list(db_path=DEFAULT_DB_PATH):
    """Retrieves all registered users and their billing status for admin analytics."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.email, u.full_name, u.created_at, b.plan_tier, b.subscription_expires_at, b.emails_sent_today
        FROM users u
        LEFT JOIN user_billing b ON u.id = b.user_id
        ORDER BY u.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_admin_payments_list(db_path=DEFAULT_DB_PATH):
    """Retrieves all transaction logs from user_payments for admin audit."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.payment_id, p.order_id, p.amount, p.plan_tier, p.status, p.created_at, u.email as user_email
        FROM user_payments p
        LEFT JOIN users u ON p.user_id = u.id
        ORDER BY p.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_admin_system_metrics(db_path=DEFAULT_DB_PATH):
    """Aggregates platform performance, revenue, and active subscriber stats."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # 1. Total users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # 2. Total successful payments & revenue
    cursor.execute("SELECT COUNT(*), SUM(amount) FROM user_payments WHERE status = 'success'")
    pay_count, revenue_paise = cursor.fetchone()
    revenue = (revenue_paise or 0) / 100.0  # Convert paise to INR
    
    # 3. System-wide emails sent today
    cursor.execute("SELECT SUM(emails_sent_today) FROM user_billing")
    total_emails_today = cursor.fetchone()[0] or 0
    
    # 4. Count of active paid subscriptions
    cursor.execute("""
        SELECT COUNT(*) FROM user_billing 
        WHERE plan_tier IN ('basic', 'standard', 'premium')
    """)
    active_subscriptions = cursor.fetchone()[0]

    # 5. Total recruiters in master pool (user_id = 1)
    cursor.execute("SELECT COUNT(*) FROM contacts WHERE user_id = 1")
    total_recruiters = cursor.fetchone()[0] or 0
    
    conn.close()
    return {
        "total_users": total_users,
        "total_payments_count": pay_count,
        "total_revenue": revenue,
        "total_emails_today": total_emails_today,
        "active_subscriptions": active_subscriptions,
        "total_recruiters": total_recruiters
    }

def get_admin_recruiters_list(limit=500, db_path=DEFAULT_DB_PATH):
    """Retrieves recruiter contacts from the master pool (user_id = 1)."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, title, company, category, email, status
        FROM contacts
        WHERE user_id = 1
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_admin_trends(days=7, db_path=DEFAULT_DB_PATH):
    """Retrieves signup and revenue trends grouped by day for the last N days."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    signup_trends = []
    revenue_trends = []
    
    # Generate list of dates for the last N days
    for i in range(days - 1, -1, -1):
        date_obj = datetime.now() - timedelta(days=i)
        date_str = date_obj.strftime("%Y-%m-%d")
        date_slashed = date_obj.strftime("%d/%m/%Y")
        label = date_obj.strftime("%b %d") # e.g. "Jul 19"
        
        # Query signups
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE created_at LIKE ? OR created_at LIKE ?
        """, (f"{date_str}%", f"{date_slashed}%"))
        signups = cursor.fetchone()[0] or 0
        signup_trends.append({"date": label, "value": signups})
        
        # Query revenue
        cursor.execute("""
            SELECT SUM(amount) FROM user_payments 
            WHERE status = 'success' AND (created_at LIKE ? OR created_at LIKE ?)
        """, (f"{date_str}%", f"{date_slashed}%"))
        revenue_paise = cursor.fetchone()[0] or 0
        revenue = revenue_paise / 100.0
        revenue_trends.append({"date": label, "value": revenue})
        
    conn.close()
    return {
        "signups": signup_trends,
        "revenue": revenue_trends
    }

def save_feedback(name, rating, comment, db_path=DEFAULT_DB_PATH):
    """Saves a new user feedback in the database."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    created_at = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO feedbacks (name, rating, comment, created_at)
        VALUES (?, ?, ?, ?)
    """, (name.strip(), int(rating), comment.strip(), created_at))
    conn.commit()
    conn.close()
    return True

def get_feedbacks(db_path=DEFAULT_DB_PATH):
    """Retrieves all feedbacks from the database, ordered by newest first."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, rating, comment, created_at FROM feedbacks ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    
    feedbacks_list = []
    for r in rows:
        feedbacks_list.append({
            "id": r[0],
            "name": r[1],
            "rating": r[2],
            "comment": r[3],
            "created_at": r[4]
        })
    return feedbacks_list
