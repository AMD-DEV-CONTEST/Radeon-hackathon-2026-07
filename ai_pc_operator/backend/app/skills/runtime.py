"""Skill runtime - dispatches skill handlers, retries, verifies.

A skill handler is a Python async function registered by dotted path
in the registry. The runtime imports it, validates inputs, runs it
with retry/timeout, runs verification, and records the run.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from app.skills.contracts import (
    SkillDefinition,
    SkillRunResult,
    SkillStatus,
)
from app.skills.registry import SkillRegistry
from app.skills.verification import VerificationEngine

logger = logging.getLogger(__name__)


SkillHandler = Callable[..., Awaitable[Dict[str, Any]]]


class SkillRuntime:
    """Executes skills with retry, timeout, and verification."""

    def __init__(
        self,
        registry: SkillRegistry,
        verification: VerificationEngine,
        handler_overrides: Optional[Dict[str, SkillHandler]] = None,
    ) -> None:
        self.registry = registry
        self.verification = verification
        self._handler_overrides = handler_overrides or {}
        self._handler_cache: Dict[str, SkillHandler] = {}

    async def execute(
        self,
        skill_id: str,
        inputs: Dict[str, Any],
        task_id: Optional[str] = None,
        node_id: Optional[str] = None,
        command_id: Optional[int] = None,
    ) -> SkillRunResult:
        """Run a skill end-to-end."""
        skill = await self.registry.get(skill_id)
        if skill is None:
            return SkillRunResult(
                skill_id=skill_id,
                status=SkillStatus.FAILED,
                error=f"unknown skill: {skill_id}",
            )
        if not skill.enabled:
            return SkillRunResult(
                skill_id=skill_id,
                status=SkillStatus.BLOCKED,
                error="skill disabled",
            )

        # Validate inputs
        missing = [
            inp.name
            for inp in skill.inputs
            if inp.required and inp.name not in inputs
        ]
        if missing:
            return SkillRunResult(
                skill_id=skill_id,
                status=SkillStatus.FAILED,
                error=f"missing required inputs: {missing}",
            )

        handler = self._resolve_handler(skill)
        if handler is None:
            return SkillRunResult(
                skill_id=skill_id,
                status=SkillStatus.FAILED,
                error=f"handler not found: {skill.handler}",
            )

        attempts = 0
        last_error: Optional[str] = None
        outputs: Dict[str, Any] = {}
        start = time.time()
        while attempts <= skill.retry_limit:
            attempts += 1
            try:
                outputs = await asyncio.wait_for(
                    handler(**inputs),
                    timeout=skill.timeout_sec,
                )
                outputs = outputs or {}
                last_error = None
                break
            except asyncio.TimeoutError:
                last_error = f"timeout after {skill.timeout_sec}s"
                logger.warning("Skill %s timed out (attempt %d)", skill_id, attempts)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.warning(
                    "Skill %s failed (attempt %d): %s", skill_id, attempts, exc
                )
        duration_ms = int((time.time() - start) * 1000)

        if last_error is not None:
            result = SkillRunResult(
                skill_id=skill_id,
                status=SkillStatus.FAILED,
                error=last_error,
                duration_ms=duration_ms,
                attempts=attempts,
            )
            await self.registry.record_run(
                skill_id=skill_id,
                status=SkillStatus.FAILED,
                inputs=inputs,
                outputs={},
                duration_ms=duration_ms,
                task_id=task_id,
                node_id=node_id,
                command_id=command_id,
                error=last_error,
            )
            return result

        # Verification
        verification_passed: Optional[bool] = None
        verification_details: list = []
        if skill.verification:
            v = await self.verification.verify(skill.verification, outputs)
            verification_passed = bool(v.get("passed"))
            verification_details = v.get("checks", [])
            if not verification_passed:
                result = SkillRunResult(
                    skill_id=skill_id,
                    status=SkillStatus.FAILED,
                    outputs=outputs,
                    error="verification failed",
                    duration_ms=duration_ms,
                    attempts=attempts,
                    verification_passed=False,
                    verification_details=verification_details,
                )
                await self.registry.record_run(
                    skill_id=skill_id,
                    status=SkillStatus.FAILED,
                    inputs=inputs,
                    outputs=outputs,
                    duration_ms=duration_ms,
                    task_id=task_id,
                    node_id=node_id,
                    command_id=command_id,
                    error="verification failed",
                )
                return result

        result = SkillRunResult(
            skill_id=skill_id,
            status=SkillStatus.SUCCESS,
            outputs=outputs,
            duration_ms=duration_ms,
            attempts=attempts,
            verification_passed=verification_passed,
            verification_details=verification_details,
        )
        await self.registry.record_run(
            skill_id=skill_id,
            status=SkillStatus.SUCCESS,
            inputs=inputs,
            outputs=outputs,
            duration_ms=duration_ms,
            task_id=task_id,
            node_id=node_id,
            command_id=command_id,
        )
        return result

    def _resolve_handler(self, skill: SkillDefinition) -> Optional[SkillHandler]:
        if skill.id in self._handler_overrides:
            return self._handler_overrides[skill.id]
        if skill.id in self._handler_cache:
            return self._handler_cache[skill.id]
        try:
            module_path, _, attr = skill.handler.rpartition(".")
            if not module_path:
                return None
            module = importlib.import_module(module_path)
            fn = getattr(module, attr, None)
            if fn is None:
                return None
            if not inspect.iscoroutinefunction(fn):
                # Wrap sync functions so they can be awaited uniformly.
                async def _async_wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
                    out = fn(*args, **kwargs)
                    if not isinstance(out, dict):
                        return {"result": out}
                    return out

                self._handler_cache[skill.id] = _async_wrapper
                return _async_wrapper
            self._handler_cache[skill.id] = fn
            return fn
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to import handler %s: %s", skill.handler, exc)
            return None
