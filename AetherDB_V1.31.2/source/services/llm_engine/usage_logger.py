"""Token usage and API call logging."""
import json, os, logging
from datetime import datetime

LOG_PATH = "logs/llm_usage.jsonl"
log = logging.getLogger(__name__)

def log_call(task_type: str, model: str, tokens_in: int, tokens_out: int, duration_ms: float, success: bool):
    """Record an LLM API call."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "task_type": task_type,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "duration_ms": round(duration_ms, 1),
        "success": success,
    }
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("Failed to log LLM usage: %s", e)

def get_stats() -> dict:
    """Get usage statistics."""
    if not os.path.exists(LOG_PATH):
        return {"total_calls": 0, "total_tokens_in": 0, "total_tokens_out": 0}
    total = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "errors": 0}
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    total["calls"] += 1
                    total["tokens_in"] += entry.get("tokens_in", 0)
                    total["tokens_out"] += entry.get("tokens_out", 0)
                    if not entry.get("success", True):
                        total["errors"] += 1
    except: pass
    return total
