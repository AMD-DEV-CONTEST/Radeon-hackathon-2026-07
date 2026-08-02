"""Local-only policy, path isolation, and audit helpers for SparkFencer."""

import json
import os
import time
from urllib.parse import urlparse


WORKSPACE_ROOT = os.path.realpath(os.getcwd())
AUDIT_PATH = os.path.join(WORKSPACE_ROOT, "outputs", ".audit", "agent_tools.jsonl")


def require_child_path(root, name):
    """Resolve *name* under root and reject traversal outside that directory."""
    root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath((root, candidate)) != root or candidate == root:
        raise ValueError("访问被拒绝：路径必须位于授权的本地目录内")
    return candidate


def require_local_endpoint(url):
    """Core model services must be loopback-only in local-only mode."""
    host = (urlparse(url).hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("访问被拒绝：核心模型服务必须运行在本机回环地址")
    return url


def require_model_endpoint(url):
    """Permit a model endpoint only when its privacy mode is explicitly enabled.

    SparkFencer is local-only by default. Radeon Cloud's shared API is the
    one opt-in exception supported for the contest deployment: enabling it
    sends prompts and VLM keyframes to that service. Keep the switch in the
    process environment so neither credentials nor the exception enter config.
    """
    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return url
    if (host == "developer.amd.com.cn"
            and os.environ.get("SPARKFENCER_ALLOW_RADEON_CLOUD_API") == "1"):
        return url
    raise ValueError(
        "访问被拒绝：核心模型服务必须是本地回环地址；"
        "如需显式使用 Radeon Cloud API，请设置 SPARKFENCER_ALLOW_RADEON_CLOUD_API=1"
    )


def audit_tool(tool, *, status="ok", details=None):
    """Append a minimal local audit record without storing user video/content."""
    os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": tool,
        "status": status,
        "details": details or {},
    }
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
