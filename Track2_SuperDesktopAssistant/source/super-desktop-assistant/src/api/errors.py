"""
共享错误分类工具 —— 避免 allocator 和 main 中的重复模式匹配。

所有错误模式集中定义，确保 allocator 的重试策略和 main 的用户提示保持一致。
"""

# ─── 错误分类关键词 ───

# 鉴权/API Key 错误（永久错误，不应重试）
AUTH_KEYWORDS = [
    "401", "authentication", "unauthorized", "auth fail",
    "api key", "apikey", "invalid api", "incorrect api key",
    "invalid x-api-key", "invalid token", "access denied",
    "forbidden", "invalid_request_error",
]

# 配额/余额错误（永久错误，不应重试）
QUOTA_KEYWORDS = [
    "402", "insufficient_quota", "insufficient balance",
    "billing", "exceeded your quota", "quota exceeded",
    "out of quota", "not enough quota", "balance not enough",
    "insufficient user quota",
]

# 模型错误（永久错误，不应重试）
MODEL_KEYWORDS = [
    "model not found", "model does not exist", "not exist",
    "not found",
]

# 速率限制（瞬态错误，可以重试）
RATE_LIMIT_KEYWORDS = [
    "429", "rate limit", "too many requests", "throttl",
    "request frequency", "rate exceeded", "too frequent",
]

# 超时（瞬态错误，可以重试）
TIMEOUT_KEYWORDS = ["timeout", "timed out"]

# 网络连接（瞬态错误，可以重试）
NETWORK_KEYWORDS = [
    "connection", "refused", "unreachable", "dns",
    "resolve", "network", "name or service not known",
]

# 服务端错误（瞬态错误，可以重试）
SERVER_ERROR_KEYWORDS = [
    "500", "502", "503", "504", "internal server error",
    "service unavailable", "bad gateway", "gateway timeout",
]

# ─── 分类函数 ───

def is_permanent_error(error_msg: str) -> bool:
    """判断是否是永久错误（不应重试）。"""
    msg = error_msg.lower()
    all_permanent = AUTH_KEYWORDS + QUOTA_KEYWORDS + MODEL_KEYWORDS
    return any(k in msg for k in all_permanent)


def is_transient_error(error_msg: str) -> bool:
    """判断是否是瞬态错误（可以重试）。"""
    return not is_permanent_error(error_msg)


def classify_error(error_msg: str) -> str:
    """
    将错误分类为用户友好的中文提示类别。

    Returns:
        错误类别标签（用于生成用户提示）
    """
    msg = error_msg.lower()

    if any(k in msg for k in AUTH_KEYWORDS):
        return "auth"
    if any(k in msg for k in QUOTA_KEYWORDS):
        return "quota"
    if any(k in msg for k in MODEL_KEYWORDS):
        return "model"
    if any(k in msg for k in RATE_LIMIT_KEYWORDS):
        return "rate_limit"
    if any(k in msg for k in TIMEOUT_KEYWORDS):
        return "timeout"
    if any(k in msg for k in NETWORK_KEYWORDS):
        return "network"
    if any(k in msg for k in SERVER_ERROR_KEYWORDS):
        return "server_error"
    return "unknown"
