"""Verification engine - layered post-action checks.

Each skill can declare one or more verification methods. After a skill
runs, the engine runs the verifiers and returns pass/fail with details.
If a required verifier fails, the skill result is marked failed and
the task graph can trigger rollback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db.database import db_session
from app.skills.contracts import SkillVerificationSpec

logger = logging.getLogger(__name__)


class VerificationEngine:
    """Runs verification methods against skill outputs."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Any] = {
            "file_exists": self._verify_file_exists,
            "file_contains": self._verify_file_contains,
            "http_status": self._verify_http_status,
            "json_path": self._verify_json_path,
            "process_healthy": self._verify_process_healthy,
            "ocr_text": self._verify_ocr_text,
            "dom_state": self._verify_dom_state,
            "screenshot_diff": self._verify_screenshot_diff,
        }

    async def verify(
        self,
        methods: List[SkillVerificationSpec],
        outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run all verification methods and return aggregate result."""
        if not methods:
            return {"passed": True, "checks": [], "required_passed": True}

        checks: List[Dict[str, Any]] = []
        required_passed = True
        for spec in methods:
            handler = self._handlers.get(spec.method)
            if handler is None:
                checks.append(
                    {
                        "method": spec.method,
                        "passed": False,
                        "error": f"unknown verification method: {spec.method}",
                        "required": spec.required,
                    }
                )
                if spec.required:
                    required_passed = False
                continue
            try:
                passed, detail = await handler(spec.config, outputs)
            except Exception as exc:  # noqa: BLE001
                passed, detail = False, f"verifier raised: {exc}"
            checks.append(
                {
                    "method": spec.method,
                    "passed": bool(passed),
                    "detail": detail,
                    "required": spec.required,
                }
            )
            if spec.required and not passed:
                required_passed = False

        return {
            "passed": required_passed,
            "checks": checks,
            "required_passed": required_passed,
        }

    async def record_evidence(
        self,
        task_id: Optional[str],
        node_id: Optional[str],
        skill_id: Optional[str],
        kind: str,
        path: Optional[str] = None,
        summary: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Persist an evidence row for replay/audit."""
        async with db_session() as db:
            cur = await db.execute(
                """
                INSERT INTO evidence (task_id, node_id, skill_id, kind, path, summary, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    node_id,
                    skill_id,
                    kind,
                    path,
                    summary,
                    json.dumps(data, default=str) if data else None,
                ),
            )
            await db.commit()
            return cur.lastrowid or 0

    # ------------------------------------------------------------------
    # Built-in verifiers
    # ------------------------------------------------------------------

    async def _verify_file_exists(
        self, config: Dict[str, Any], outputs: Dict[str, Any]
    ) -> tuple[bool, str]:
        path = config.get("path") or outputs.get("path")
        if not path:
            return False, "no path provided"
        exists = Path(path).exists()
        return exists, f"path={path} exists={exists}"

    async def _verify_file_contains(
        self, config: Dict[str, Any], outputs: Dict[str, Any]
    ) -> tuple[bool, str]:
        path = config.get("path") or outputs.get("path")
        needle = config.get("text") or outputs.get("text")
        if not path or needle is None:
            return False, "missing path or text"
        try:
            content = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return False, f"read failed: {exc}"
        ok = str(needle) in content
        return ok, f"path={path} contains={ok}"

    async def _verify_http_status(
        self, config: Dict[str, Any], outputs: Dict[str, Any]
    ) -> tuple[bool, str]:
        url = config.get("url") or outputs.get("url")
        expected = int(config.get("expected", 200))
        if not url:
            return False, "no url provided"
        try:
            import urllib.request

            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                code = resp.status
        except Exception as exc:  # noqa: BLE001
            return False, f"http error: {exc}"
        return code == expected, f"url={url} status={code} expected={expected}"

    async def _verify_json_path(
        self, config: Dict[str, Any], outputs: Dict[str, Any]
    ) -> tuple[bool, str]:
        path = config.get("path", "")
        expected = config.get("equals")
        data = outputs.get("data") or outputs
        cur: Any = data
        for part in path.split(".") if path else []:
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)] if int(part) < len(cur) else None
            else:
                return False, f"cannot descend into {part}"
        if expected is None:
            return cur is not None, f"path={path} value={cur}"
        return cur == expected, f"path={path} value={cur} expected={expected}"

    async def _verify_process_healthy(
        self, config: Dict[str, Any], outputs: Dict[str, Any]
    ) -> tuple[bool, str]:
        name = config.get("name") or outputs.get("process")
        if not name:
            return False, "no process name provided"
        try:
            import psutil  # type: ignore

            for proc in psutil.process_iter(["name"]):
                if name.lower() in (proc.info["name"] or "").lower():
                    return True, f"process {name} running"
            return False, f"process {name} not found"
        except Exception as exc:  # noqa: BLE001
            return False, f"psutil error: {exc}"

    async def _verify_ocr_text(
        self, config: Dict[str, Any], outputs: Dict[str, Any]
    ) -> tuple[bool, str]:
        # OCR verification is best-effort; if OCR is not loaded we report unknown.
        text = outputs.get("ocr_text") or ""
        needle = config.get("contains", "")
        if not needle:
            return True, "no needle configured"
        return needle.lower() in text.lower(), f"contains={needle in text.lower()}"

    async def _verify_dom_state(
        self, config: Dict[str, Any], outputs: Dict[str, Any]
    ) -> tuple[bool, str]:
        selector = config.get("selector")
        expected = config.get("text")
        dom = outputs.get("dom") or {}
        if not selector:
            return True, "no selector configured"
        node = dom.get(selector)
        if node is None:
            return False, f"selector {selector} not found"
        if expected is None:
            return True, f"selector {selector} present"
        return expected in (node.get("text") or ""), f"text match={expected in (node.get('text') or '')}"

    async def _verify_screenshot_diff(
        self, config: Dict[str, Any], outputs: Dict[str, Any]
    ) -> tuple[bool, str]:
        # Without a stored baseline we treat the screenshot as evidence only.
        path = outputs.get("screenshot") or config.get("path")
        if not path:
            return False, "no screenshot path"
        return Path(path).exists(), f"screenshot={path} exists={Path(path).exists()}"
