import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_actual_sending():
    print("=== STARTING ACTUAL EMAIL DELIVERY VERIFICATION TEST ===")
    
    # 0. Pre-clean existing target email to bypass unique constraints
    import sqlite3
    try:
        conn = sqlite3.connect("outreach.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM contacts WHERE email = ?", ("shubranshumishra22@gmail.com",))
        conn.commit()
        conn.close()
        print("✓ Pre-cleaned target email from database.")
    except Exception as e:
        print(f"Warning: database pre-clean failed: {e}")
        
    # 1. Register a test user
    ts = int(time.time())
    email = f"test_sender_{ts}@example.com"
    password = "senderpassword123"
    
    print(f"\n1. Registering test user: {email}...")
    res_signup = requests.post(f"{BASE_URL}/api/auth/signup", json={"email": email, "password": password})
    assert res_signup.status_code == 200, f"Signup failed: {res_signup.text}"
    token = res_signup.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✓ Registered successfully.")

    # 2. Add the user's real email as a target contact
    target_email = "shubranshumishra22@gmail.com"
    print(f"\n2. Adding target contact with email {target_email}...")
    contact_payload = {
        "contacts": [
            {
                "name": "Shubranshu Shekhar",
                "email": target_email,
                "company": "PitchDock Test Labs",
                "title": "Director of Engineering",
                "category": "Product MNCs"
            }
        ],
        "mode": "ai",
        "template_subject": "",
        "template_body": "",
        "auto_approve": False
    }
    res_add = requests.post(f"{BASE_URL}/api/contacts/add", json=contact_payload, headers=headers)
    assert res_add.status_code == 200, f"Failed to add contact: {res_add.text}"
    print("✓ Target contact added successfully.")

    # 3. Trigger outreach campaign (generation + sending)
    print("\n3. Triggering automated RAG cold outreach...")
    campaign_payload = {
        "full_name": "Test Candidate",
        "phone_number": "+91 98765 43210",
        "linkedin_profile": "https://linkedin.com/in/test-candidate",
        "current_designation": "AI Engineer",
        "experience_years": "4",
        "industry_domain": "Artificial Intelligence",
        "target_role": "Senior AI Architect",
        "achievements": [
            "Deployed production LLM pipelines handling 5M daily queries.",
            "Designed distributed training runs cutting resource costs by 40%."
        ],
        "resume_pdf_path": "",
        "category": "Product MNCs",
        "strategy": "template",  # Bypass Gemini call to verify SMTP
        "template_subject": "Exploring Opportunities - {role}",
        "template_body": "Dear {name}, I am {my_name}. I have experience of {experience} years."
    }
    
    res_campaign = requests.post(f"{BASE_URL}/api/free-outreach", json=campaign_payload, headers=headers)
    assert res_campaign.status_code == 200, f"Outreach triggering failed: {res_campaign.text}"
    print("✓ Outreach pipeline initialized.")
    print("Response detail:", res_campaign.json()["message"])

    # 4. Poll task status to watch AI generation and SMTP sending logs
    print("\n4. Polling background workers logs...")
    for _ in range(12):
        res_status = requests.get(f"{BASE_URL}/api/status", headers=headers)
        status = res_status.json()
        print(f"Status: {status.get('status')} | Current: {status.get('current')}/{status.get('total')} | Success: {status.get('success')} | Failed: {status.get('failed')}")
        if status.get("logs"):
            print("Latest log:", status["logs"][-1])
        if status.get("status") in ["completed", "failed"]:
            break
        time.sleep(3)

    # 5. Fetch contacts database to check status
    res_contacts = requests.get(f"{BASE_URL}/api/contacts", headers=headers)
    contacts = res_contacts.json()["contacts"]
    print("\n5. Verification Summary:")
    for c in contacts:
        print(f"Contact: {c['name']} | Email: {c['email']} | Status: {c['status']} | Error: {c.get('error_message')}")

    print("\n=== E2E ACTUAL DELIVERY TEST COMPLETED ===")

if __name__ == "__main__":
    test_actual_sending()
