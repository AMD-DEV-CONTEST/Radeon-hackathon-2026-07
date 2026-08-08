"""Download tools - safe file downloading with approval."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DOWNLOAD_DIR = ROOT / "ai_pc_operator" / "data" / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# Dangerous extensions
DANGEROUS_EXTENSIONS = [
    ".exe", ".msi", ".bat", ".cmd",
    ".ps1", ".vbs", ".scr",
    ".jar", ".js",
]


class DownloadTools:
    """Download management tools."""

    def _is_dangerous(self, filename: str) -> bool:
        """Check if file has dangerous extension."""
        filename_lower = filename.lower()
        for ext in DANGEROUS_EXTENSIONS:
            if filename.endswith(ext):
                return True
        return False

    async def download_file(
        self, url: str, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Download a file safely."""
        try:
            if not filename:
                filename = url.split("/")[-1]

            # Check if dangerous
            is_dangerous = self._is_dangerous(filename)

            download_path = DOWNLOAD_DIR / filename

            # Download
            urllib.request.urlretrieve(url, str(download_path))

            # Calculate hash
            file_hash = hashlib.sha256(
                download_path.read_bytes()
            ).hexdigest()

            return {
                "status": "success",
                "url": url,
                "path": str(download_path),
                "size": download_path.stat().st_size,
                "hash": file_hash,
                "is_dangerous": is_dangerous,
                "requires_approval_to_run": is_dangerous,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def list_downloads(self) -> Dict[str, Any]:
        """List downloaded files."""
        try:
            items = []
            for item in DOWNLOAD_DIR.iterdir():
                if item.is_file():
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "size": item.stat().st_size,
                        "modified": item.stat().st_mtime,
                        "is_dangerous": self._is_dangerous(item.name),
                    })

            return {
                "status": "success",
                "items": items,
                "count": len(items),
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }
