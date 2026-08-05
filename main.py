import argparse
import sys
import os
import time
from datetime import datetime
import json

import db
import generator
import sender

def cmd_init(args):
    """Initializes the project configuration files if they don't exist."""
    print("Initializing configuration templates...")
    
    # Check for candidate_profile.json
    if not os.path.exists("candidate_profile.json"):
        profile_template = {
            "full_name": "Your Full Name",
            "phone_number": "+91 99999 99999",
            "linkedin_profile": "https://linkedin.com/in/yourprofile",
            "current_designation": "Software Engineer",
            "experience_years": "3",
            "industry_domain": "Fintech & SaaS",
            "target_role": "Senior Software Engineer",
            "achievements": [
                "Led development of a high-throughput microservice handling 10k+ requests per second, reducing latency by 40%.",
                "Architected and deployed a multi-tenant user authentication system used across 3 company products.",
                "Experienced in Python, AWS (ECS, RDS, Lambda), and PostgreSQL with a focus on scalable backend systems."
            ],
            "resume_pdf_path": "resume.pdf"
        }
        with open("candidate_profile.json", "w") as f:
            json.dump(profile_template, f, indent=2)
        print("✓ Created candidate_profile.json template.")
    else:
        print("ℹ candidate_profile.json already exists.")
        
    # Check for .env
    if not os.path.exists(".env"):
        env_content = """# Gemini API Configuration
GEMINI_API_KEY=your_gemini_api_key_here

# SMTP Configuration (For sending emails)
# Gmail: smtp.gmail.com | 587 (TLS) or 465 (SSL)
# Outlook: smtp.office365.com | 587 (TLS)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=your_email@gmail.com
# For Gmail, this must be an "App Password", not your main password
SENDER_PASSWORD=your_app_password_here
"""
        with open(".env", "w") as f:
            f.write(env_content)
        print("✓ Created .env template.")
    else:
        print("ℹ .env already exists.")
        
    print("\nNext steps:")
    print("1. Update the .env file with your GEMINI_API_KEY and SMTP credentials.")
    print("2. Update candidate_profile.json with your details and achievements.")
    print("3. Ensure your resume PDF is located at the path specified in your profile config.")

def cmd_load(args):
    """Loads contacts from Excel or PDF into the local SQLite database."""
    excel_path = getattr(args, 'excel_path', 'kaamkibaatein_HR_Contact_Database.xlsx')
    pdf_path = getattr(args, 'pdf_path', 'HR_Contact_List.pdf')
    db_path = args.db_path
    
    print(f"Loading contacts into database '{db_path}'...")
    try:
        if os.path.exists(pdf_path):
            print(f"Parsing PDF file '{pdf_path}'...")
            results = db.import_from_pdf(pdf_path, seed_all_users=True, db_path=db_path)
            print("PDF import completed successfully!")
            print(f" - Added new contacts: {results['added']}")
            print(f" - Ignored duplicates: {results['ignored_duplicates']}")
            print(f" - Total contacts parsed: {results['total_contacts_parsed']}")
        elif os.path.exists(excel_path):
            print(f"Parsing Excel file '{excel_path}'...")
            results = db.import_from_excel(excel_path, db_path=db_path)
            print("Excel import completed successfully!")
            print(f" - Added new contacts: {results['added']}")
            print(f" - Ignored duplicates: {results['ignored_duplicates']}")
            print(f" - Skipped rows: {results['invalid_or_empty']}")
        else:
            print("No Excel or PDF contact list found.", file=sys.stderr)
            return

        cmd_stats(args)
    except Exception as e:
        print(f"Error loading contacts: {e}", file=sys.stderr)


def cmd_stats(args):
    """Displays statistics of the contacts database."""
    db_path = args.db_path
    try:
        stats = db.get_stats(db_path)
        print(f"\n==========================================")
        print(f" Database Statistics: {db_path}")
        print(f"==========================================")
        print(f"Total Contacts: {stats['total']}")
        
        print("\nStatus Breakdown:")
        for status, count in stats['status_breakdown'].items():
            print(f" - {status.capitalize()}: {count}")
            
        print("\nCategory Breakdown:")
        for cat, count in stats['category_breakdown'].items():
            print(f" - {cat if cat else 'Uncategorized'}: {count}")
        print(f"==========================================")
    except Exception as e:
        print(f"Error reading statistics: {e}", file=sys.stderr)

def cmd_generate(args):
    """Generates personalized email drafts using Gemini."""
    db_path = args.db_path
    limit = args.limit
    category = args.category
    auto_approve = args.auto_approve
    dry_run = args.dry_run
    
    try:
        profile = generator.load_candidate_profile()
    except Exception as e:
        print(f"Error loading candidate profile: {e}", file=sys.stderr)
        return
        
    try:
        client = None if dry_run else generator.get_gemini_client()
    except Exception as e:
        print(f"Error initializing Gemini client: {e}", file=sys.stderr)
        return
        
    # Get pending contacts
    pending = db.get_contacts_by_status("pending", limit=limit, category=category, db_path=db_path)
    
    if not pending:
        print("No pending contacts found to generate drafts for.")
        return
        
    print(f"Found {len(pending)} pending contacts. Starting draft generation...")
    
    success_count = 0
    fail_count = 0
    
    for idx, contact in enumerate(pending, 1):
        print(f"[{idx}/{len(pending)}] Generating draft for {contact['name']} at {contact['company']} ({contact['email']})...")
        try:
            if dry_run:
                # Mock generation for dry run
                subject = f"Exploring opportunities at {contact['company']}"
                body = f"Hi {contact['name']},\n\n[Dry Run Mock Body for {profile['full_name']}]"
                print(f"  [DRY RUN] Subject: {subject}")
                success_count += 1
                continue
                
            subject, body = generator.generate_email_draft(contact, profile, client)
            
            target_status = "approved" if auto_approve else "drafted"
            db.update_contact_draft(contact["id"], subject, body, status=target_status, db_path=db_path)
            print(f"  ✓ Draft generated. Status set to '{target_status}'.")
            success_count += 1
            
            # Small cooldown between LLM API calls
            time.sleep(1)
            
        except Exception as e:
            print(f"  ✗ Failed to generate draft: {e}")
            fail_count += 1
            if not dry_run:
                db.update_contact_status(contact["id"], "failed", error_message=str(e), db_path=db_path)
                
    print(f"\nGeneration Run Completed:")
    print(f" - Successful: {success_count}")
    print(f" - Failed: {fail_count}")

def cmd_review(args):
    """CLI review tool to view and approve drafted emails."""
    db_path = args.db_path
    
    drafts = db.get_contacts_by_status("drafted", db_path=db_path)
    if not drafts:
        print("No drafts available for review. Run 'generate' first.")
        return
        
    print(f"Total drafts pending review: {len(drafts)}")
    print("\nChoose an option:")
    print("1. Approve ALL drafted emails")
    print("2. Review drafts one by one")
    print("3. Reset/Reject all drafted emails back to pending")
    print("4. Exit review")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        confirm = input("Are you sure you want to approve all drafts? (y/n): ").strip().lower()
        if confirm == "y":
            for d in drafts:
                db.update_contact_status(d["id"], "approved", db_path=db_path)
            print(f"✓ Approved all {len(drafts)} drafts.")
            
    elif choice == "2":
        for idx, d in enumerate(drafts, 1):
            print(f"\n==========================================")
            print(f" Draft {idx} of {len(drafts)}")
            print(f" Contact: {d['name']} ({d['title']} at {d['company']})")
            print(f" Email: {d['email']}")
            print(f"------------------------------------------")
            print(f" SUBJECT: {d['personalized_subject']}")
            print(f"------------------------------------------")
            print(f" BODY:\n{d['personalized_body']}")
            print(f"==========================================")
            
            action = input("\nAction: [a]pprove, [r]eject/reset, [s]kip, [q]uit: ").strip().lower()
            if action == "a":
                db.update_contact_status(d["id"], "approved", db_path=db_path)
                print("✓ Draft approved.")
            elif action == "r":
                db.update_contact_status(d["id"], "pending", db_path=db_path)
                print("✓ Draft rejected and reset to pending.")
            elif action == "q":
                print("Exiting review loop.")
                break
            else:
                print("Skipped.")
                
    elif choice == "3":
        confirm = input("Are you sure you want to reset all drafts to pending? (y/n): ").strip().lower()
        if confirm == "y":
            count = db.reset_status("drafted", "pending", db_path=db_path)
            print(f"✓ Reset {count} drafts to pending.")
            
    else:
        print("Review session closed.")

def cmd_send(args):
    """Sends approved emails via SMTP."""
    db_path = args.db_path
    limit = args.limit
    delay = args.delay
    
    try:
        profile = generator.load_candidate_profile()
    except Exception as e:
        print(f"Error loading candidate profile: {e}", file=sys.stderr)
        return
        
    resume_path = profile.get("resume_pdf_path")
    if resume_path and not os.path.exists(resume_path):
        print(f"WARNING: Resume file not found at: {resume_path}")
        confirm = input("Do you want to proceed without attaching a resume? (y/n): ").strip().lower()
        if confirm != "y":
            print("Aborted sending run.")
            return
            
    # Get approved contacts
    approved = db.get_contacts_by_status("approved", limit=limit, db_path=db_path)
    
    if not approved:
        print("No approved drafts found to send. Run 'generate' and 'review' first.")
        return
        
    print(f"Found {len(approved)} approved emails to send.")
    confirm = input(f"Confirm sending emails to {len(approved)} recipients? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return
        
    success_count = 0
    fail_count = 0
    
    for idx, contact in enumerate(approved, 1):
        print(f"[{idx}/{len(approved)}] Sending email to {contact['name']} ({contact['email']})...")
        
        success, err = sender.send_single_email(
            to_email=contact["email"],
            subject=contact["personalized_subject"],
            body=contact["personalized_body"],
            attachment_path=resume_path if resume_path and os.path.exists(resume_path) else None
        )
        
        sent_time = datetime.now().isoformat()
        if success:
            db.update_contact_status(contact["id"], "sent", sent_at=sent_time, db_path=db_path)
            print("  ✓ Sent successfully.")
            success_count += 1
        else:
            db.update_contact_status(contact["id"], "failed", error_message=err, db_path=db_path)
            print(f"  ✗ Failed: {err}")
            fail_count += 1
            
        # Rate limit delay between emails, skipping delay for the last email
        if idx < len(approved) and delay > 0:
            print(f"  Sleeping for {delay} seconds to avoid rate limiting...")
            time.sleep(delay)
            
    print(f"\nSending Run Completed:")
    print(f" - Successfully Sent: {success_count}")
    print(f" - Failed: {fail_count}")

def cmd_reset(args):
    """Resets contacts from one status to another."""
    db_path = args.db_path
    from_status = args.from_status
    to_status = args.to_status
    
    try:
        count = db.reset_status(from_status, to_status, db_path=db_path)
        print(f"✓ Successfully reset {count} contacts from '{from_status}' to '{to_status}'.")
    except Exception as e:
        print(f"Error resetting contacts: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(
        description="HR Cold Email Outreach Automator - Resilient and Personalized Outreach Tool"
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Workflow command to execute")
    
    # Init command
    subparsers.add_parser("init", help="Initialize project configuration templates")
    
    # Load command
    parser_load = subparsers.add_parser("load", help="Parse Excel sheet or PDF file and import contacts to SQLite database")
    parser_load.add_argument("--excel-path", default="kaamkibaatein_HR_Contact_Database.xlsx", help="Path to contact Excel sheet")
    parser_load.add_argument("--pdf-path", default="HR_Contact_List.pdf", help="Path to contact PDF file")
    parser_load.add_argument("--db-path", default="outreach.db", help="SQLite database path")
    
    # Stats command
    parser_stats = subparsers.add_parser("stats", help="Display statistics of current outreach database")
    parser_stats.add_argument("--db-path", default="outreach.db", help="SQLite database path")
    
    # Generate command
    parser_gen = subparsers.add_parser("generate", help="Generate personalized email drafts using Gemini")
    parser_gen.add_argument("--db-path", default="outreach.db", help="SQLite database path")
    parser_gen.add_argument("--limit", type=int, help="Limit number of contacts to generate drafts for in this run")
    parser_gen.add_argument("--category", help="Filter generation by category tier")
    parser_gen.add_argument("--auto-approve", action="store_true", help="Auto-approve drafts directly to 'approved' status")
    parser_gen.add_argument("--dry-run", action="store_true", help="Perform a dry-run draft generation without making API calls or updating DB")
    
    # Review command
    parser_rev = subparsers.add_parser("review", help="CLI review tool to inspect and approve generated drafts")
    parser_rev.add_argument("--db-path", default="outreach.db", help="SQLite database path")
    
    # Send command
    parser_send = subparsers.add_parser("send", help="Send approved email drafts via secure SMTP")
    parser_send.add_argument("--db-path", default="outreach.db", help="SQLite database path")
    parser_send.add_argument("--limit", type=int, help="Limit number of emails to send in this run")
    parser_send.add_argument("--delay", type=int, default=30, help="Delay in seconds between sending emails to prevent SMTP blocking")
    
    # Reset command
    parser_reset = subparsers.add_parser("reset", help="Reset contact status in the database")
    parser_reset.add_argument("--db-path", default="outreach.db", help="SQLite database path")
    parser_reset.add_argument("--from-status", required=True, choices=["pending", "drafted", "approved", "sent", "failed"], help="Current status to reset")
    parser_reset.add_argument("--to-status", default="pending", choices=["pending", "drafted", "approved"], help="Target status to change to")
    
    args = parser.parse_args()
    
    if args.command == "init":
        cmd_init(args)
    elif args.command == "load":
        cmd_load(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "review":
        cmd_review(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "reset":
        cmd_reset(args)

if __name__ == "__main__":
    main()
