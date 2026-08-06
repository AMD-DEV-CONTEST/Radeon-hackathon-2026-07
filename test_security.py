import os
import time
from fastapi import HTTPException
from server import validate_safe_resume_path, update_profile, ProfileData
import db

def test_security_hardening():
    # 1. Test validate_safe_resume_path
    print("Testing validate_safe_resume_path logic...")
    assert validate_safe_resume_path("resume.pdf") == True
    assert validate_safe_resume_path("/Users/username/documents/resume.pdf") == True
    assert validate_safe_resume_path("/home/ubuntu/resume.PDF") == True
    
    assert validate_safe_resume_path("resume.docx") == False
    assert validate_safe_resume_path("../../.env") == False
    assert validate_safe_resume_path("/etc/passwd") == False
    assert validate_safe_resume_path("outreach.db") == False
    print("✓ Path validation tests passed.")
    
    # 2. Test profile endpoint validation
    print("Testing Profile PDF path injection blocks...")
    # Initialize DB
    db.init_db()
    # Create test user
    ts = int(time.time())
    email = f"sec_test_{ts}@example.com"
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (email, password_hash, created_at) VALUES (?, 'hash', 'now')",
        (email,)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    current_user = {"id": user_id, "email": email}
    
    # Valid update
    valid_data = ProfileData(
        full_name="John Doe",
        phone_number="12345",
        linkedin_profile="in/johndoe",
        current_designation="Eng",
        experience_years="5",
        industry_domain="Tech",
        target_role="Developer",
        achievements=["Did X"],
        resume_pdf_path="my_resume.pdf"
    )
    res = update_profile(valid_data, current_user)
    assert res["status"] == "success"
    print("✓ Safe resume path accepted.")
    
    # Invalid update (.env injection)
    invalid_data = ProfileData(
        full_name="John Doe",
        phone_number="12345",
        linkedin_profile="in/johndoe",
        current_designation="Eng",
        experience_years="5",
        industry_domain="Tech",
        target_role="Developer",
        achievements=["Did X"],
        resume_pdf_path="/Users/admin/.env"
    )
    try:
        update_profile(invalid_data, current_user)
        assert False, "Should have raised HTTPException for unsafe resume path"
    except HTTPException as e:
        assert e.status_code == 400
        print("✓ Unsafe resume path correctly rejected with 400.")
        
    print("All security hardening checks passed successfully!")

if __name__ == "__main__":
    test_security_hardening()
