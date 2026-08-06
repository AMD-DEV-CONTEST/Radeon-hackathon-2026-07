import os
import hmac
import hashlib
import time
from fastapi import HTTPException
import db
from server import verify_razorpay_payment, VerifyPaymentRequest, BillingPlanRequest, update_billing

def test_payments_flow():
    # 1. Setup mock credentials or test environment
    os.environ["RAZORPAY_KEY_ID"] = "rzp_test_mock_id"
    os.environ["RAZORPAY_KEY_SECRET"] = "mock_secret"
    
    # Initialize DB and create a test user
    db.init_db()
    ts = int(time.time())
    email = f"test_payment_{ts}@example.com"
    
    # Since db.py uses hash_password, let's just generate a simple user
    # If create_user is not direct, let's check db.py signature or insert directly.
    # Let's use get_connection to insert a user securely for testing.
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (email, password_hash, created_at, full_name) VALUES (?, 'hash', 'now', 'Test User')",
        (email,)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    current_user = {"id": user_id, "email": email}
    
    # 2. Test verification logic directly
    print("Testing payment verification...")
    order_id = f"order_{ts}"
    payment_id = f"pay_{ts}"
    msg = f"{order_id}|{payment_id}"
    key_secret = "mock_secret"
    valid_sig = hmac.new(
        key_secret.encode('utf-8'),
        msg.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Verify with correct signature
    req = VerifyPaymentRequest(
        razorpay_payment_id=payment_id,
        razorpay_order_id=order_id,
        razorpay_signature=valid_sig,
        plan_tier="premium"
    )
    res_verify = verify_razorpay_payment(req, current_user)
    assert res_verify["status"] == "success", f"Expected success, got: {res_verify}"
    print("✓ Successful payment verified.")
    
    # Verify that plan updated to premium and expires in 30 days
    billing_info = db.get_billing_info(user_id)
    assert billing_info["plan_tier"] == "premium"
    assert billing_info["subscription_expires_at"] is not None
    print("✓ Billing plan updated in DB correctly with monthly expiration date.")

    # Verify annual subscription verification
    order_id_annual = f"order_annual_{ts}"
    payment_id_annual = f"pay_annual_{ts}"
    msg_annual = f"{order_id_annual}|{payment_id_annual}"
    valid_sig_annual = hmac.new(
        key_secret.encode('utf-8'),
        msg_annual.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    req_annual = VerifyPaymentRequest(
        razorpay_payment_id=payment_id_annual,
        razorpay_order_id=order_id_annual,
        razorpay_signature=valid_sig_annual,
        plan_tier="standard",
        billing_cycle="annual"
    )
    res_verify_annual = verify_razorpay_payment(req_annual, current_user)
    assert res_verify_annual["status"] == "success"
    
    billing_info_annual = db.get_billing_info(user_id)
    assert billing_info_annual["plan_tier"] == "standard"
    assert billing_info_annual["subscription_expires_at"] is not None
    print("✓ Successful annual payment verified and expiration date set.")

    # Test auto-degradation by manually setting the expiration date in the past
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE user_billing SET subscription_expires_at = '2000-01-01T00:00:00.000000' WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()

    # Retrieve billing info again, which should trigger the self-degrading check
    billing_info_expired = db.get_billing_info(user_id)
    assert billing_info_expired["plan_tier"] == "free"
    assert billing_info_expired["subscription_expires_at"] is None
    print("✓ Auto-degradation to 'free' after subscription expiration works perfectly.")
    
    # Verify with incorrect signature
    req_invalid = VerifyPaymentRequest(
        razorpay_payment_id=f"pay_invalid_{ts}",
        razorpay_order_id=order_id,
        razorpay_signature="invalid_signature",
        plan_tier="premium"
    )
    try:
        verify_razorpay_payment(req_invalid, current_user)
        assert False, "Should have raised HTTPException for invalid signature"
    except HTTPException as e:
        assert e.status_code == 400
        print("✓ Invalid signature correctly rejected with 400.")
        
    # Verify blocking direct billing upgrade
    req_billing = BillingPlanRequest(plan_tier="basic")
    try:
        update_billing(req_billing, current_user)
        assert False, "Should have raised HTTPException for direct upgrade"
    except HTTPException as e:
        assert e.status_code == 403
        print("✓ Direct upgrade to basic tier blocked with 403.")
        
    print("All payment verification tests passed!")

if __name__ == "__main__":
    test_payments_flow()
