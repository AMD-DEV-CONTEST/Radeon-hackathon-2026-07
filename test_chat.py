import requests
import sqlite3
import time

BASE_URL = "http://127.0.0.1:8000"

def test_chat_customization():
    print("=== STARTING CHAT RECRUITER NAME SYNC VERIFICATION ===")
    
    # 1. Register a test user
    ts = int(time.time())
    email = f"chat_user_{ts}@example.com"
    password = "chatpassword123"
    
    res_signup = requests.post(f"{BASE_URL}/api/auth/signup", json={"email": email, "password": password})
    assert res_signup.status_code == 200, f"Signup failed: {res_signup.text}"
    signup_data = res_signup.json()
    token = signup_data["token"]
    user_id = signup_data["user"]["user_id"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"✓ Registered test user (ID: {user_id}).")

    # 2. Add a contact with old name
    old_name = "Original Recruiter Name"
    contact_email = f"contact_{ts}@example.com"
    contact_payload = {
        "contacts": [
            {
                "name": old_name,
                "email": contact_email,
                "company": "PitchDock Test Labs",
                "title": "Director of Recruiting",
                "category": "Tech MNCs"
            }
        ],
        "mode": "ai",
        "template_subject": "",
        "template_body": "",
        "auto_approve": False
    }
    res_add = requests.post(f"{BASE_URL}/api/contacts/add", json=contact_payload, headers=headers)
    assert res_add.status_code == 200, f"Failed to add contact: {res_add.text}"
    print(f"✓ Added contact '{old_name}' (Email: {contact_email}).")

    # Retrieve the contact ID from the DB
    conn = sqlite3.connect("outreach.db")
    cur = conn.cursor()
    cur.execute("SELECT id FROM contacts WHERE email = ? AND user_id = ?", (contact_email, user_id))
    contact_id = cur.fetchone()[0]
    conn.close()
    print(f"✓ Retrieved contact ID: {contact_id}.")

    # 3. Call chat customize to change the recruiter name to Rohit
    chat_payload = {
        "message": "recruiter's name is Rohit",
        "template_subject": "Hi {recruiter_name}, exploring opportunities",
        "template_body": "Dear {recruiter_name}, I am {my_name}.",
        "achievements": ["Achievement A", "Achievement B"],
        "target_role": "Data Engineer",
        "recruiter_id": contact_id
    }
    
    print("\nSending chat customize request: 'recruiter's name is Rohit'...")
    res_chat = requests.post(f"{BASE_URL}/api/chat-customize", json=chat_payload, headers=headers)
    assert res_chat.status_code == 200, f"Chat customize failed: {res_chat.text}"
    chat_data = res_chat.json()
    
    print("\nAPI Response:")
    print("Chat Response:", chat_data.get("chat_response"))
    print("Updated Recruiter Name:", chat_data.get("updated_recruiter_name"))
    print("Updated Subject Template:", chat_data.get("updated_subject"))

    assert chat_data.get("updated_recruiter_name") == "Rohit", "Failed: Recruiter name was not parsed correctly by Gemini!"
    print("\n✓ Correctly parsed updated_recruiter_name as 'Rohit'.")

    # 4. Verify database contact record was updated
    conn = sqlite3.connect("outreach.db")
    cur = conn.cursor()
    cur.execute("SELECT name, personalized_subject, personalized_body FROM contacts WHERE id = ?", (contact_id,))
    row = cur.fetchone()
    conn.close()
    
    updated_name, updated_subject, updated_body = row[0], row[1], row[2]
    
    print(f"Database Recruiter Name after sync: '{updated_name}'")
    print(f"Database Personalized Subject after sync: '{updated_subject}'")
    print(f"Database Personalized Body after sync length: {len(updated_body) if updated_body else 0}")
    
    assert updated_name == "Rohit", f"Failed: Database name remains '{updated_name}'!"
    assert updated_subject is not None and "Rohit" in updated_subject, f"Failed: Database draft subject is '{updated_subject}'!"
    assert updated_body is not None and len(updated_body) > 0, "Failed: Database draft body is empty!"
    
    print("\n=== ALL CHAT NAME & DRAFT SYNC TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    test_chat_customization()
