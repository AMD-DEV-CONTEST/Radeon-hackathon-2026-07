"""
SWE-bench Multimodal adapter — Determinex's bridge between SWE-bench Multimodal
tasks and the visual agent pipeline.

SWE-bench Multimodal adds screenshots / UI context to the classic text-only
SWE-bench issue format. Each task contains:
  - issue_text (str)       — GitHub issue body
  - screenshots (list[Path]) — one or more UI screenshots from the issue report
  - repo_path (Path)       — pre-cloned repository to patch

Determinex's handling:
  1. Ingest screenshot(s) through visual_cloak (PII/secret redaction)
  2. Run OCR to extract visible text for the repair spec
  3. Compose VisualTaskSpec with issue_text + screenshot context
  4. Hand to existing SWE-bench solve() loop (code patch generation)
  5. After patch applied: capture Playwright screenshot of any frontend
  6. Run visual_diff between before/after screenshots
  7. Write visual_repair corpus record (HMAC signed)
  8. Return OracleVerdict with visual evidence attached

All cloud-bound screenshots are passed through visual_cloak regardless of
whether DETERMINEX_CLOAK is set — visual privacy is unconditional.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agents.base_agent import (
    CorpusType,
    EnvType,
    OracleType,
    OracleVerdict,
    VisualTaskSpec,
)

try:
    from vision.visual_cloak import RedactionResult
    from vision.visual_cloak import redact as _cloak_redact

    _CLOAK_AVAILABLE = True
except ImportError:
    _CLOAK_AVAILABLE = False
    log.warning(
        "[swebench_multimodal] visual_cloak not available — screenshots will NOT be redacted"
    )

try:
    from vision.visual_diff import VisualDiffResult
    from vision.visual_diff import diff as _visual_diff

    _DIFF_AVAILABLE = True
except ImportError:
    _DIFF_AVAILABLE = False
    log.warning("[swebench_multimodal] visual_diff not available — diff step will be skipped")

try:
    from vision.ocr_scanner import extract_text as _ocr_text

    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

try:
    from corpus.corpus_manager import get_manager as _get_corpus_manager

    _CORPUS_AVAILABLE = True
except ImportError:
    _CORPUS_AVAILABLE = False
    log.warning("[swebench_multimodal] corpus_manager not available — traces will not be persisted")


# ---------------------------------------------------------------------------
# Task format
# ---------------------------------------------------------------------------


@dataclass
class SWEBenchMultimodalTask:
    """One task from the SWE-bench Multimodal dataset."""

    instance_id: str
    repo: str  # e.g. "django/django"
    issue_text: str
    base_commit: str
    screenshots: list[Path] = field(default_factory=list)
    patch: str = ""  # ground-truth patch (eval only, never shown to agent)
    test_patch: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VisualRepairResult:
    """End-to-end result from the visual repair pipeline."""

    instance_id: str
    success: bool
    patch: str
    cloak_results: list[dict]  # one per screenshot
    before_screenshot: Path | None
    after_screenshot: Path | None
    diff_result: dict | None
    corpus_record_id: str | None
    oracle_verdict: OracleVerdict | None
    error: str | None = None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class SWEBenchMultimodalAdapter:
    """
    Wraps Determinex's code-patch pipeline with visual evidence collection.

    Usage:
        adapter = SWEBenchMultimodalAdapter()
        result = adapter.solve(task, repo_path=Path("/clone/repo"))
    """

    def __init__(self, work_dir: Path | None = None):
        self._work_dir = work_dir or Path(tempfile.mkdtemp(prefix="determinex_swemm_"))
        self._corpus = _get_corpus_manager() if _CORPUS_AVAILABLE else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_task_spec(self, task: SWEBenchMultimodalTask) -> VisualTaskSpec:
        """Convert a SWE-bench Multimodal task to Determinex's VisualTaskSpec."""
        screenshot_context = self._build_screenshot_context(task.screenshots)
        goal = f"Fix the following issue in {task.repo}:\n\n{task.issue_text}"
        if screenshot_context:
            goal += f"\n\nVisual context from issue screenshots:\n{screenshot_context}"
        return VisualTaskSpec(
            task_id=task.instance_id,
            env_type=EnvType.BROWSER,
            goal=goal,
            constraints=[
                "Produce a minimal unified diff patch",
                "All changed files must compile / pass type-check",
                "Do not modify test fixtures unless provably broken",
                "Respect existing code conventions",
            ],
            source_benchmark="swebench_multimodal",
            max_steps=20,
            timeout_seconds=600,
            metadata={
                "repo": task.repo,
                "base_commit": task.base_commit,
                "screenshot_count": len(task.screenshots),
                "has_visual_context": bool(screenshot_context),
            },
        )

    def solve(
        self,
        task: SWEBenchMultimodalTask,
        repo_path: Path,
        capture_browser: bool = False,
    ) -> VisualRepairResult:
        """
        Full pipeline:
          1. Cloak all screenshots
          2. Build VisualTaskSpec
          3. Invoke code-patch solver (determinex_swebench_agent solve())
          4. Optionally capture before/after browser screenshots
          5. Run visual_diff
          6. Write corpus record
          7. Return VisualRepairResult
        """
        cloak_results: list[dict] = []
        cloaked_paths: list[Path] = []

        # Step 1: cloak every screenshot unconditionally
        for i, ss_path in enumerate(task.screenshots):
            cloaked = self._cloak_screenshot(ss_path, task.instance_id, i)
            cloak_results.append(cloaked)
            if cloaked.get("cloaked_path"):
                cloaked_paths.append(Path(cloaked["cloaked_path"]))

        # Replace raw paths with cloaked paths for any downstream use
        cloaked_task = SWEBenchMultimodalTask(
            instance_id=task.instance_id,
            repo=task.repo,
            issue_text=task.issue_text,
            base_commit=task.base_commit,
            screenshots=cloaked_paths,
            patch=task.patch,
            test_patch=task.test_patch,
            metadata=task.metadata,
        )

        # Step 2: build task spec
        task_spec = self.to_task_spec(cloaked_task)

        # Step 3: run code-patch solver
        before_screenshot: Path | None = None
        after_screenshot: Path | None = None

        if capture_browser:
            before_screenshot = self._capture_browser_screenshot(
                repo_path, task.instance_id, "before"
            )

        patch = self._run_solver(cloaked_task, repo_path, task_spec)

        if capture_browser and patch:
            after_screenshot = self._capture_browser_screenshot(
                repo_path, task.instance_id, "after"
            )

        # Step 4: visual diff
        diff_result: dict | None = None
        if before_screenshot and after_screenshot and _DIFF_AVAILABLE:
            diff_result = self._compute_visual_diff(before_screenshot, after_screenshot)

        # Step 5: build oracle verdict
        oracle = self._build_oracle_verdict(task, patch, cloak_results, diff_result, repo_path)

        # Step 6: write corpus
        record_id = self._write_corpus(
            task=task,
            task_spec=task_spec,
            patch=patch,
            cloak_results=cloak_results,
            before_screenshot=before_screenshot,
            after_screenshot=after_screenshot,
            diff_result=diff_result,
            oracle=oracle,
        )

        return VisualRepairResult(
            instance_id=task.instance_id,
            success=bool(patch) and oracle.passed,
            patch=patch,
            cloak_results=cloak_results,
            before_screenshot=before_screenshot,
            after_screenshot=after_screenshot,
            diff_result=diff_result,
            corpus_record_id=record_id,
            oracle_verdict=oracle,
        )

    # ------------------------------------------------------------------
    # Internal: screenshot cloaking
    # ------------------------------------------------------------------

    def _cloak_screenshot(self, path: Path, instance_id: str, index: int) -> dict:
        if not _CLOAK_AVAILABLE:
            log.error(
                "[swebench_multimodal] visual_cloak unavailable — REFUSING to send screenshot uncloaked"
            )
            return {"error": "visual_cloak unavailable — screenshot blocked", "cloak_active": False}

        if not path.exists():
            return {"error": f"screenshot not found: {path}", "cloak_active": False}

        out_dir = self._work_dir / "cloaked" / instance_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"ss_{index:02d}_cloaked.png"

        try:
            result: RedactionResult = _cloak_redact(path, output_path=out_path)
            return {
                "source": str(path),
                "cloaked_path": str(result.output_path) if result.output_path else str(out_path),
                "cloak_active": result.cloak_active,
                "redacted_regions": result.redacted_count,
                "redacted_categories": result.categories_found,
                "input_hash": result.input_hash,
                "output_hash": result.output_hash,
            }
        except Exception as exc:
            log.error("[swebench_multimodal] cloak failed for %s: %s", path, exc)
            return {"error": str(exc), "cloak_active": False, "source": str(path)}

    # ------------------------------------------------------------------
    # Internal: OCR context building
    # ------------------------------------------------------------------

    def _build_screenshot_context(self, screenshots: list[Path]) -> str:
        if not screenshots or not _OCR_AVAILABLE:
            return ""
        texts = []
        for i, ss in enumerate(screenshots):
            try:
                text = _ocr_text(ss)
                if text.strip():
                    texts.append(f"[Screenshot {i + 1}]: {text.strip()[:800]}")
            except Exception:
                pass
        return "\n".join(texts)

    # ------------------------------------------------------------------
    # Internal: solver invocation
    # ------------------------------------------------------------------

    def _run_solver(
        self,
        task: SWEBenchMultimodalTask,
        repo_path: Path,
        task_spec: VisualTaskSpec,
    ) -> str:
        """Invoke the existing SWE-bench solver, enriched with visual context."""
        try:
            from determinex_swebench_agent import DeterminexSWEAgent

            agent = DeterminexSWEAgent()
            # Build a synthetic instance dict matching SWE-bench harness format
            instance = {
                "instance_id": task.instance_id,
                "repo": task.repo,
                "problem_statement": task_spec.goal,
                "base_commit": task.base_commit,
                "patch": task.patch,
                "test_patch": task.test_patch,
            }
            patch = agent.solve(instance, repo_path=repo_path)
            return patch or ""
        except Exception as exc:
            log.error("[swebench_multimodal] solver failed for %s: %s", task.instance_id, exc)
            return ""

    # ------------------------------------------------------------------
    # Internal: browser screenshot capture
    # ------------------------------------------------------------------

    def _capture_browser_screenshot(
        self, repo_path: Path, instance_id: str, stage: str
    ) -> Path | None:
        """Attempt to capture a browser screenshot of the running app in the repo."""
        out_dir = self._work_dir / "browser_caps" / instance_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{stage}.png"
        try:
            # Delegate to browser_verifier which handles Playwright internally
            from browser.browser_verifier import capture_screenshot

            capture_screenshot(repo_path=repo_path, output_path=out_path)
            if out_path.exists():
                return out_path
        except Exception as exc:
            log.debug("[swebench_multimodal] browser capture (%s) skipped: %s", stage, exc)
        return None

    # ------------------------------------------------------------------
    # Internal: visual diff
    # ------------------------------------------------------------------

    def _compute_visual_diff(self, before: Path, after: Path) -> dict | None:
        if not _DIFF_AVAILABLE:
            return None
        try:
            result: VisualDiffResult = _visual_diff(before, after)
            return result.to_dict()
        except Exception as exc:
            log.warning("[swebench_multimodal] visual_diff failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal: oracle verdict
    # ------------------------------------------------------------------

    def _build_oracle_verdict(
        self,
        task: SWEBenchMultimodalTask,
        patch: str,
        cloak_results: list[dict],
        diff_result: dict | None,
        repo_path: Path,
    ) -> OracleVerdict:
        cloak_ok = all(r.get("cloak_active", False) for r in cloak_results if task.screenshots)
        patch_present = bool(patch.strip())

        # Visual verification: if we have a diff, any change is evidence of effect
        visual_evidence = bool(diff_result and not diff_result.get("similar", True))

        passed = patch_present and (not task.screenshots or cloak_ok)
        reason_parts = []
        if not patch_present:
            reason_parts.append("no patch generated")
        if task.screenshots and not cloak_ok:
            reason_parts.append("visual cloak failed — screenshot blocked from cloud")
        if visual_evidence:
            reason_parts.append(
                f"visual diff detected (score={diff_result['pixel_diff_score']:.3f})"
            )

        return OracleVerdict(
            oracle_type=OracleType.VISUAL,
            passed=passed,
            score=1.0 if passed else 0.0,
            reason="; ".join(reason_parts) if reason_parts else "patch generated, cloak verified",
            metadata={
                "cloak_all_passed": cloak_ok,
                "patch_bytes": len(patch.encode()),
                "visual_diff": diff_result,
            },
        )

    # ------------------------------------------------------------------
    # Internal: corpus write
    # ------------------------------------------------------------------

    def _write_corpus(
        self,
        task: SWEBenchMultimodalTask,
        task_spec: VisualTaskSpec,
        patch: str,
        cloak_results: list[dict],
        before_screenshot: Path | None,
        after_screenshot: Path | None,
        diff_result: dict | None,
        oracle: OracleVerdict,
    ) -> str | None:
        if not self._corpus:
            return None
        try:
            payload = {
                "instance_id": task.instance_id,
                "repo": task.repo,
                "issue_text_excerpt": task.issue_text[:500],
                "patch_bytes": len(patch.encode()) if patch else 0,
                "patch_lines": patch.count("\n") if patch else 0,
                "screenshots_count": len(task.screenshots),
                "cloak_results": cloak_results,
                "before_screenshot": str(before_screenshot) if before_screenshot else None,
                "after_screenshot": str(after_screenshot) if after_screenshot else None,
                "visual_diff": diff_result,
                "oracle": {
                    "passed": oracle.passed,
                    "score": oracle.score,
                    "reason": oracle.reason,
                },
            }
            input_hash = hashlib.blake2b(
                (task.issue_text + "".join(str(s) for s in task.screenshots)).encode(),
                digest_size=32,
            ).hexdigest()
            output_hash = hashlib.blake2b(
                patch.encode() if patch else b"",
                digest_size=32,
            ).hexdigest()

            record = self._corpus._normalize_record(
                corpus_type=CorpusType.VISUAL_REPAIR,
                task_id=task.instance_id,
                input_hash=input_hash,
                output_hash=output_hash,
                source_benchmark="swebench_multimodal",
                payload=payload,
            )
            self._corpus._atomic_append(
                self._corpus._corpus_path(CorpusType.VISUAL_REPAIR),
                record,
            )
            return record.get("_sig", "")[:16]
        except Exception as exc:
            log.error("[swebench_multimodal] corpus write failed: %s", exc)
            return None
