from src.auth import classify_login_error

def test_invalid_password():
    assert classify_login_error("AUTH_INVALID") == "invalid_credentials"
    assert classify_login_error(401) == "invalid_credentials"

def test_locked_account():
    assert classify_login_error("AUTH_LOCKED") == "locked"

def test_rate_limited():
    assert classify_login_error(429) == "rate_limited"

def test_unknown():
    assert classify_login_error("WTF") == "unknown"
    assert classify_login_error(None) == "unknown"
