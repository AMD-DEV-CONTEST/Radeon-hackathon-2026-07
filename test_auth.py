import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    print("=== STARTING AUTH AND USER ISOLATION VERIFICATION TESTS ===")
    
    # Generate unique test usernames based on current timestamp
    ts = int(time.time())
    user_a_email = f"user_a_{ts}@example.com"
    user_b_email = f"user_b_{ts}@example.com"
    password = "securepassword123"

    print(f"\n1. Testing Signup for User A ({user_a_email})...")
    res_signup_a = requests.post(f"{BASE_URL}/api/auth/signup", json={"email": user_a_email, "password": password})
    assert res_signup_a.status_code == 200, f"Signup A failed: {res_signup_a.text}"
    token_a = res_signup_a.json()["token"]
    print("✓ User A registered successfully.")

    print(f"\n2. Testing Signup for User B ({user_b_email})...")
    res_signup_b = requests.post(f"{BASE_URL}/api/auth/signup", json={"email": user_b_email, "password": password})
    assert res_signup_b.status_code == 200, f"Signup B failed: {res_signup_b.text}"
    token_b = res_signup_b.json()["token"]
    print("✓ User B registered successfully.")

    print("\n3. Testing Login for User A...")
    res_login_a = requests.post(f"{BASE_URL}/api/auth/login", json={"email": user_a_email, "password": password})
    assert res_login_a.status_code == 200, f"Login A failed: {res_login_a.text}"
    token_a = res_login_a.json()["token"]
    assert isinstance(token_a, str) and len(token_a) > 0
    print("✓ User A logged in successfully and retrieved new session token.")

    print("\n4. Testing Unauthenticated Request to Stats Endpoint...")
    res_stats_unauth = requests.get(f"{BASE_URL}/api/stats")
    assert res_stats_unauth.status_code == 401, f"Expected 401, got {res_stats_unauth.status_code}: {res_stats_unauth.text}"
    print("✓ Correctly returned 401 Unauthorized for request without headers.")

    print("\n5. Testing Authenticated Request for User A...")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    res_stats_a = requests.get(f"{BASE_URL}/api/stats", headers=headers_a)
    assert res_stats_a.status_code == 200, f"Stats A request failed: {res_stats_a.text}"
    print("✓ User A successfully fetched stats.")

    print("\n6. Creating Contact for User A and User B (isolation check)...")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    
    # Add a contact for User A
    contact_a_payload = {
        "contacts": [
            {
                "name": "A-Recruiter",
                "email": f"a-rec-{ts}@corp.com",
                "company": "A-Corp",
                "title": "HR Manager",
                "category": "Product MNCs"
            }
        ],
        "mode": "ai",
        "template_subject": "Outreach",
        "template_body": "Hello",
        "auto_approve": False
    }
    res_add_a = requests.post(f"{BASE_URL}/api/contacts/add", json=contact_a_payload, headers=headers_a)
    assert res_add_a.status_code == 200, f"Add contact A failed: {res_add_a.text}"

    # Add a contact for User B
    contact_b_payload = {
        "contacts": [
            {
                "name": "B-Recruiter",
                "email": f"b-rec-{ts}@corp.com",
                "company": "B-Corp",
                "title": "HR Lead",
                "category": "Startups"
            }
        ],
        "mode": "ai",
        "template_subject": "Hello",
        "template_body": "Hi there",
        "auto_approve": False
    }
    res_add_b = requests.post(f"{BASE_URL}/api/contacts/add", json=contact_b_payload, headers=headers_b)
    assert res_add_b.status_code == 200, f"Add contact B failed: {res_add_b.text}"
    print("✓ Added unique contacts for both User A and User B.")

    print("\n7. Verifying Contact Isolation...")
    # Fetch User A's contacts
    res_get_a = requests.get(f"{BASE_URL}/api/contacts", headers=headers_a)
    assert res_get_a.status_code == 200, f"Get contacts A failed: {res_get_a.text}"
    contacts_a = res_get_a.json()["contacts"]
    assert len(contacts_a) == 1, f"Expected 1 contact for A, got {len(contacts_a)}"
    assert contacts_a[0]["name"] == "A-Recruiter"
    print("✓ User A can only see User A's contacts.")

    # Fetch User B's contacts
    res_get_b = requests.get(f"{BASE_URL}/api/contacts", headers=headers_b)
    assert res_get_b.status_code == 200, f"Get contacts B failed: {res_get_b.text}"
    contacts_b = res_get_b.json()["contacts"]
    assert len(contacts_b) == 1, f"Expected 1 contact for B, got {len(contacts_b)}"
    assert contacts_b[0]["name"] == "B-Recruiter"
    print("✓ User B can only see User B's contacts.")

    print("\n8. Testing cross-user access attempts (Direct detail endpoint isolation)...")
    contact_a_id = contacts_a[0]["id"]
    res_cross_get = requests.get(f"{BASE_URL}/api/contact/{contact_a_id}", headers=headers_b)
    assert res_cross_get.status_code == 404, f"Expected 404, got {res_cross_get.status_code}: {res_cross_get.text}"
    print("✓ Correctly prevented User B from fetching User A's contact details (returned 404).")

    print("\n9. Testing Logout...")
    res_logout_a = requests.post(f"{BASE_URL}/api/auth/logout", headers=headers_a)
    assert res_logout_a.status_code == 200, f"Logout failed: {res_logout_a.text}"
    
    # Try fetching stats again
    res_after_logout = requests.get(f"{BASE_URL}/api/stats", headers=headers_a)
    assert res_after_logout.status_code == 401, f"Expected 401 after logout, got {res_after_logout.status_code}"
    print("✓ Successfully invalidated session on logout.")

    print("\n=== ALL AUTH AND ISOLATION TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run_tests()
