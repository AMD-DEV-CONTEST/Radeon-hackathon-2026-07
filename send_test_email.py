import os
import json
import sqlite3
from dotenv import load_dotenv
import sender
import db

def main():
    # Load env variables
    load_dotenv()
    print("=== STARTING BACKEND EMAIL SENDING TEST ===")
    
    # Target testing email address
    target_email = "shubranshugudsol@gmail.com"
    
    # SMTP details
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    print(f"Configured Outbound Email: {sender_email}")
    
    if not sender_email or not sender_password:
        print("Error: SMTP credentials (SENDER_EMAIL, SENDER_PASSWORD) are not set in .env")
        return
        
    # Get profile details
    full_name = "Shubranshu Shekhar"
    experience = "3"
    ach1 = "Led development of a high-throughput microservice handling 10k+ requests per second, reducing latency by 40%."
    ach2 = "Architected and deployed a multi-tenant user authentication system used across 3 company products."
    
    recruiter_name = "Rohit"
    company_name = "AdaniConneX"
    
    # Template
    template_subject = "Exploring opportunities at {company_name}"
    template_body = """Hi {recruiter_name},

I know recruiters read hundreds of these, so I'll keep it short. I'm a software engineer with {experience} years of experience, and I'd like to talk about the role at {company_name}.

Two things that might be relevant to your team:
— {achievement_1}
— {achievement_2}

Résumé is attached. Happy to send more detail on any of it.

Best regards,
{my_name}"""

    # Compile template
    subject = template_subject.replace("{company_name}", company_name)
    body = template_body.replace("{recruiter_name}", recruiter_name)\
                         .replace("{company_name}", company_name)\
                         .replace("{experience}", experience)\
                         .replace("{achievement_1}", ach1)\
                         .replace("{achievement_2}", ach2)\
                         .replace("{my_name}", full_name)
                         
    print("\n--- COMPILED EMAIL DETAILS ---")
    print(f"To: {target_email}")
    print(f"Subject: {subject}")
    print("\nBody:")
    print(body)
    print("------------------------------\n")
    
    print("Sending email via SMTP fallback...")
    
    # Use sender.send_single_email directly
    # Using a dummy user_id to force SMTP fallback to os.environ credentials
    success, err = sender.send_single_email(
        to_email=target_email,
        subject=subject,
        body=body,
        user_id=99999,
        attachment_path=None
    )
    
    if success:
        print(f"\n✓ SUCCESS: Email sent successfully! Check your inbox at {target_email}")
    else:
        print(f"\n✗ FAILED: {err}")

if __name__ == "__main__":
    main()
