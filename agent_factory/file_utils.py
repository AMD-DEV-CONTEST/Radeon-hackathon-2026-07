"""文件操作相关的通用工具函数"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


def file_sha256(path: Path) -> str:
    """计算文件的 SHA256 哈希值，使用 1MB 分块读取以处理大文件"""
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
