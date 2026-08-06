import time
from fastapi import Request, HTTPException
from starlette.responses import JSONResponse
from services.db import get_connection, close_connection
from services.rate_limiter import RateLimiter

rate_limiter = RateLimiter(default_limit=120, window_seconds=60)

# V1.24.6: Default deny query param API key. Set to True for backward compatibility.
_ALLOW_QUERY_API_KEY = False

def get_api_key(request: Request):
    """Get API key from X-API-Key header only."""
    header_key = request.headers.get("X-API-Key")
    if header_key:
        from app.dependencies.auth import VALID_KEYS
        if header_key in VALID_KEYS:
            return VALID_KEYS[header_key]
        raise HTTPException(status_code=401, detail="Invalid API key")
    raise HTTPException(status_code=401, detail="Missing API key (use X-API-Key header)")
