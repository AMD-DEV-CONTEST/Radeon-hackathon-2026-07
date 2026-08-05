import os
import time
from fastapi import HTTPException
import db
from server import (
    admin_login,
    get_admin_analytics,
    admin_add_recruiters,
    admin_get_recruiters,
    AdminLoginRequest,
    AdminRecruiterAddRequest,
    ContactInput
)

def test_admin_flow():
    # 1. Setup DB state with test data
    db.init_db()
    
    # Create test user if none exists
    conn = db.get_connection()
    cursor = conn.cursor()
    ts = int(time.time())
    email = f"user_{ts}@example.com"
    cursor.execute(
        "INSERT OR IGNORE INTO users (email, password_hash, created_at, full_name) VALUES (?, 'hash', 'now', 'Admin Test User')",
        (email,)
    )
    user_id = cursor.lastrowid
    conn.commit()
    
    # Add a mock payment log
    cursor.execute("""
        INSERT OR IGNORE INTO user_payments (user_id, payment_id, order_id, signature, amount, plan_tier, status, created_at)
        VALUES (?, 'pay_mock_123', 'order_mock_123', 'sig_mock_123', 49900, 'standard', 'success', '2026-07-19 23:59:00')
    """, (user_id,))
    conn.commit()
    conn.close()

    print("Testing admin authentication...")
    
    # Correct login
    req_success = AdminLoginRequest(email="pitchdock.xyz@gmail.com", password="@Hariom12345")
    res_login = admin_login(req_success)
    assert res_login["status"] == "success"
    assert "admin_token" in res_login
    token = res_login["admin_token"]
    print("✓ Login successful with correct credentials.")

    # Incorrect login
    req_fail = AdminLoginRequest(email="pitchdock.xyz@gmail.com", password="wrongpassword")
    try:
        admin_login(req_fail)
        assert False, "Should have failed login with wrong credentials"
    except HTTPException as e:
        assert e.status_code == 401
        print("✓ Login correctly rejected with 401 for incorrect password.")

    # 2. Test analytics retrieval authorization gates
    print("Testing analytics retrieval authorization...")
    
    # Missing authorization header
    try:
        get_admin_analytics(None)
        assert False, "Should have rejected request with missing auth header"
    except HTTPException as e:
        assert e.status_code == 401
        print("✓ Access denied with missing header.")

    # Invalid token authorization header
    try:
        get_admin_analytics("Bearer fake_token")
        assert False, "Should have rejected request with invalid token"
    except HTTPException as e:
        assert e.status_code == 401
        print("✓ Access denied with invalid token.")

    # Valid token request
    res_analytics = get_admin_analytics(f"Bearer {token}")
    assert res_analytics["status"] == "success"
    assert "metrics" in res_analytics
    assert "users" in res_analytics
    assert "payments" in res_analytics
    
    metrics = res_analytics["metrics"]
    assert metrics["total_users"] > 0
    assert metrics["total_revenue"] >= 499.00
    assert len(res_analytics["users"]) > 0
    assert len(res_analytics["payments"]) > 0
    assert "total_recruiters" in metrics
    print("✓ Analytics metrics fetched successfully with valid admin token.")

    # 3. Test recruiter insertion & retrieval
    print("Testing admin recruiter insertion & retrieval...")
    test_recruiter_email = f"recruiter_{ts}@techcorp.com"
    add_req = AdminRecruiterAddRequest(
        contacts=[
            ContactInput(
                email=test_recruiter_email,
                name="Ananya Sharma",
                company="TechCorp Solutions",
                title="Lead Recruiter",
                category="Fintech"
            )
        ],
        seed_all_users=True
    )
    res_add = admin_add_recruiters(add_req, authorization=f"Bearer {token}")
    assert res_add["status"] == "success"
    assert res_add["result"]["inserted_rows"] >= 1
    print("✓ Single recruiter form submission succeeded via admin endpoint.")

    # Duplicate recruiter insertion check
    res_dup = admin_add_recruiters(add_req, authorization=f"Bearer {token}")
    assert res_dup["status"] == "success"
    assert res_dup["result"]["duplicate_rows"] >= 1
    print("✓ Duplicate recruiter contact correctly skipped.")

    # Get recruiters list check
    res_list = admin_get_recruiters(authorization=f"Bearer {token}")
    assert res_list["status"] == "success"
    assert len(res_list["recruiters"]) > 0
    matched = [r for r in res_list["recruiters"] if r["email"] == test_recruiter_email]
    assert len(matched) == 1
    assert matched[0]["name"] == "Ananya Sharma"
    assert matched[0]["company"] == "TechCorp Solutions"
    print("✓ Master recruiter pool retrieval verified successfully.")

    print("All Admin Analytics & Recruiter Intake tests passed successfully!")

if __name__ == "__main__":
    test_admin_flow()
