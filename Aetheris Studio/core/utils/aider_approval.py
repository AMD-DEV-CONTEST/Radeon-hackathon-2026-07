import uuid
import time
from typing import Dict, Any, Optional

# token -> {"prompt": str, "files": list[str], "timestamp": float}
_PENDING_AIDER_EDITS: Dict[str, Dict[str, Any]] = {}

TTL_SECONDS = 15 * 60  # 15 minutes

def generate_approval_token(prompt: str, files: list[str]) -> str:
    token = str(uuid.uuid4())
    _PENDING_AIDER_EDITS[token] = {
        "prompt": prompt,
        "files": files,
        "timestamp": time.time()
    }
    return token

def get_and_validate_token(token: str) -> Optional[Dict[str, Any]]:
    if token not in _PENDING_AIDER_EDITS:
        return None
        
    data = _PENDING_AIDER_EDITS[token]
    age = time.time() - data["timestamp"]
    
    if age > TTL_SECONDS:
        # Purge expired token
        del _PENDING_AIDER_EDITS[token]
        return None
        
    return data

def pop_token(token: str) -> Optional[Dict[str, Any]]:
    """Retrieves and removes the token from pending state."""
    data = get_and_validate_token(token)
    if data:
        del _PENDING_AIDER_EDITS[token]
    return data
