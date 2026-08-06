"""Token-based auth for Gateway HTTP and WebSocket."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Request, status
from fastapi.responses import JSONResponse

# Load .env if not already loaded
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    try:
        # Try to load manually
        import os
        env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception:
        pass

# Auth is enabled by default; set AUTH_ENABLED=0 to disable
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "1") == "1"
AUTH_USERNAME = os.environ.get("AUTH_USERNAME", "admin")

# AUTH_PASSWORD and AUTH_SECRET MUST be set via environment for production.
# If AUTH_ENABLED=1 and neither is set, Gateway will refuse to start.
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")

if AUTH_ENABLED and (not AUTH_PASSWORD or not AUTH_SECRET):
    raise RuntimeError(
        "AUTH_ENABLED=1 but AUTH_PASSWORD or AUTH_SECRET is not set. "
        "Set both environment variables for production, or AUTH_ENABLED=0 for dev."
    )

# Active tokens: token → expires_at
# Now persisted in PostgreSQL instead of memory
TOKEN_TTL = int(os.environ.get("AUTH_TOKEN_TTL", "86400"))  # 24 hours

# Try to get DB connection from gateway db
try:
    from . import db as gateway_db
    _have_db = True
except ImportError:
    _have_db = False


def _generate_token() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(AUTH_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{ts}:{sig}"


async def _verify_token(token: str) -> bool:
    if not token:
        return False
    
    # If no DB available, fall back to empty check (should not happen in prod)
    if not _have_db:
        # Still do the HMAC verification even if we can't persist
        return _verify_hmac(token)
    
    try:
        pool = await gateway_db._get_pool()
        if not pool:
            return _verify_hmac(token)
        
        async with pool.acquire() as conn:
            # Clean up expired tokens first (as a maintenance step)
            await conn.execute("SELECT cleanup_expired_tokens()")
            
            # Look up the token
            row = await conn.fetchrow(
                "SELECT expires_at FROM active_tokens WHERE token = $1",
                token
            )
            
            if not row:
                # Token not in DB, check if it's valid via HMAC, if so add it to DB
                if _verify_hmac(token):
                    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL)
                    await conn.execute(
                        "INSERT INTO active_tokens (token, expires_at) VALUES ($1, $2) "
                        "ON CONFLICT (token) DO UPDATE SET expires_at = $2",
                        token,
                        expires_at
                    )
                    return True
                return False
            
            # Token exists, check if it's still valid
            if row["expires_at"] > datetime.now(timezone.utc):
                # Refresh expiration
                new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL)
                await conn.execute(
                    "UPDATE active_tokens SET expires_at = $1, updated_at = now() WHERE token = $2",
                    new_expires_at,
                    token
                )
                return True
            
            # Token expired, remove it and return false
            await conn.execute("DELETE FROM active_tokens WHERE token = $1", token)
            return False
            
    except Exception as e:
        # If DB error, still do HMAC check as fallback
        return _verify_hmac(token)


def _verify_hmac(token: str) -> bool:
    """Verify HMAC signature of token, independent of persistence."""
    parts = token.split(":")
    if len(parts) != 2:
        return False
    ts_str, sig = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if time.time() - ts > TOKEN_TTL:
        return False
    expected = hmac.new(AUTH_SECRET.encode(), ts_str.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return False
    return True


def login(username: str, password: str) -> str | None:
    if not AUTH_ENABLED:
        return _generate_token()
    if username == AUTH_USERNAME and password == AUTH_PASSWORD:
        token = _generate_token()
        # Don't need to add to DB immediately - will be added on first verification
        return token
    return None


async def logout(token: str) -> bool:
    """Revoke a token. Returns True if token was found and deleted."""
    if not _have_db:
        # No DB, can't do anything
        return False
    
    try:
        pool = await gateway_db._get_pool()
        if not pool:
            return False
        
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM active_tokens WHERE token = $1", token)
            # result format: "DELETE N" where N is number of rows deleted
            return result.split()[-1] != "0"
    except Exception:
        return False


def extract_token(request: Request) -> str:
    """Extract Bearer token from Authorization header or query param."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token", "")


async def auth_middleware(request: Request, call_next):
    """FastAPI HTTP middleware: reject unauthenticated requests."""
    if not AUTH_ENABLED:
        return await call_next(request)
    path = request.url.path
    if path in ("/auth/login", "/health") or path.startswith("/ws/") or request.method == "OPTIONS":
        return await call_next(request)
    
    token = extract_token(request)
    if not await _verify_token(token):
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED,
                           content={"detail": "Missing or invalid token"})
    return await call_next(request)


def ws_auth_from_url(url) -> bool:
    """WebSocket auth: verify token from URL query params.
    Note: This runs synchronously, so if DB is available it will still do HMAC check only.
    Persistence verification happens async after connection is accepted.
    """
    if not AUTH_ENABLED:
        return True
    import urllib.parse
    qs = ""
    if hasattr(url, 'query'):
        qs = url.query
        if isinstance(qs, bytes):
            qs = qs.decode()
    elif hasattr(url, 'query_params'):
        qs = str(url.query_params)
    params = urllib.parse.parse_qs(qs)
    tokens = params.get("token", [])
    token = tokens[0] if tokens else ""
    # For synchronous verification, just check HMAC
    # If DB is available the full verification will happen async in the endpoint before accepting connection
    # Actually wait, let's do the best we can synchronously
    if _have_db:
        # Can't do async here, so at least verify HMAC
        return _verify_hmac(token)
    return _verify_hmac(token)
