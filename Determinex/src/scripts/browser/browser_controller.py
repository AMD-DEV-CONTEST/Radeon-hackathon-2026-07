"""
Browser controller — the ONLY module that calls Playwright.
Every action goes through safety_governor first. Every trace is written to corpus.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from agents.base_agent import (
    ActionResult,
    ActionType,
    AgentAction,
    AgentObservation,
    EnvType,
    VisualTaskSpec,
)
from agents.safety_governor import get_governor
from corpus.corpus_manager import get_manager

log = logging.getLogger(__name__)

try:
    from playwright.sync_api import Browser, Page, sync_playwright

    _PW_AVAILABLE = True
except ImportError:
    _PW_AVAILABLE = False
    log.warning("[browser_controller] playwright not installed — controller will raise on use")


class BrowserController:
    """
    Isolated browser controller. Every action:
      1. Passes safety_governor.evaluate_action()
      2. Executes via Playwright (isolated profile)
      3. Returns ActionResult
      4. Caller is responsible for writing corpus trace via CorpusManager.
    """

    def __init__(
        self,
        task: VisualTaskSpec,
        headless: bool = True,
        screenshot_dir: str | Path = ".",
    ) -> None:
        if not _PW_AVAILABLE:
            raise RuntimeError(
                "playwright is required for BrowserController. Install with: pip install playwright && playwright install"
            )
        self.task = task
        self.headless = headless
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._governor = get_governor()
        self._corpus = get_manager()
        self._pw = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._step = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def launch(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        # Isolated context — no persistent storage, no shared cookies
        context = self._browser.new_context(
            accept_downloads=False,  # block by default; confirm required
        )
        self._page = context.new_page()
        log.info(
            "[browser_controller] launched (headless=%s) task=%s", self.headless, self.task.task_id
        )

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception as exc:
            log.warning("[browser_controller] close error: %s", exc)

    def __enter__(self) -> BrowserController:
        self.launch()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Action execution (all actions must pass safety governor)
    # ------------------------------------------------------------------

    def execute(self, action: AgentAction) -> ActionResult:
        """Execute one action. Blocks or confirmation-gates via safety_governor."""
        obs_before = self._capture_observation()
        t0 = time.monotonic()

        # Safety gate
        decision = self._governor.evaluate_action(self.task, obs_before, action)
        action.safety_decision = decision.value.value

        if decision.is_blocked:
            self._corpus.write_refusal(
                task_id=self.task.task_id,
                trigger="action",
                layer="L5",
                category=decision.reason,
                violating_excerpt=f"{action.action_type.value}: {action.target or ''} {action.payload or ''}",
                benchmark=self.task.source_benchmark,
            )
            return ActionResult(
                action=action,
                success=False,
                error=f"BLOCKED by safety governor: {decision.reason}",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        if decision.needs_confirmation:
            log.warning(
                "[browser_controller] action %s requires human confirmation — AUTO-DENIED in non-interactive mode",
                action.action_type.value,
            )
            return ActionResult(
                action=action,
                success=False,
                error=f"Action {action.action_type.value} requires human confirmation (REQUIRE_CONFIRMATION policy)",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        # Execute
        try:
            result = self._dispatch(action)
            result.duration_ms = int((time.monotonic() - t0) * 1000)
            result.observation_after = self._capture_observation()
            self._step += 1
            return result
        except Exception as exc:
            log.error("[browser_controller] action %s failed: %s", action.action_type, exc)
            return ActionResult(
                action=action,
                success=False,
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

    def _dispatch(self, action: AgentAction) -> ActionResult:
        page = self._page
        assert page is not None

        at = action.action_type

        if at == ActionType.READ_SCREEN:
            path = self._take_screenshot(f"step_{self._step}_read_screen")
            return ActionResult(action=action, success=True, metadata={"screenshot": str(path)})

        if at == ActionType.READ_DOM:
            html = page.content()
            return ActionResult(action=action, success=True, metadata={"dom_length": len(html)})

        if at == ActionType.READ_ACCESSIBILITY_TREE:
            tree = page.accessibility.snapshot() or {}
            return ActionResult(action=action, success=True, metadata={"tree_keys": len(tree)})

        if at == ActionType.CLICK:
            if action.target:
                page.locator(action.target).click()
            elif action.x is not None and action.y is not None:
                page.mouse.click(action.x, action.y)
            else:
                raise ValueError("CLICK requires target selector or (x, y) coordinates")
            return ActionResult(action=action, success=True)

        if at == ActionType.TYPE:
            if not action.target:
                raise ValueError("TYPE requires a target selector")
            page.locator(action.target).fill(action.payload or "")
            return ActionResult(action=action, success=True)

        if at == ActionType.PRESS_KEY:
            page.keyboard.press(action.payload or "Enter")
            return ActionResult(action=action, success=True)

        if at == ActionType.SCROLL:
            x = action.x or 0
            y = action.y or 300
            page.mouse.wheel(x, y)
            return ActionResult(action=action, success=True)

        if at == ActionType.RUN_COMMAND:
            result = page.evaluate(action.payload or "undefined")
            return ActionResult(
                action=action, success=True, metadata={"js_result": str(result)[:500]}
            )

        raise ValueError(f"Unhandled action type in browser controller: {at}")

    # ------------------------------------------------------------------
    # Observation capture
    # ------------------------------------------------------------------

    def _capture_observation(self) -> AgentObservation:
        page = self._page
        if page is None:
            return AgentObservation(env_type=EnvType.BROWSER, step=self._step)
        try:
            from browser.dom_reader import dom_hash, get_dom_snapshot

            html = get_dom_snapshot(page)
            d_hash = dom_hash(html)
            screenshot_path = str(self._take_screenshot(f"obs_{self._step}"))
            return AgentObservation(
                env_type=EnvType.BROWSER,
                step=self._step,
                screenshot_path=screenshot_path,
                dom_snapshot=html[:8192],
                dom_hash=d_hash,
                url=page.url,
            )
        except Exception as exc:
            log.warning("[browser_controller] observation capture error: %s", exc)
            return AgentObservation(env_type=EnvType.BROWSER, step=self._step)

    def _take_screenshot(self, label: str) -> Path:
        path = self.screenshot_dir / f"{self.task.task_id}_{label}.png"
        if self._page:
            self._page.screenshot(path=str(path))
        return path

    # ------------------------------------------------------------------
    # Navigation helper (URL-screened)
    # ------------------------------------------------------------------

    def navigate(self, url: str) -> ActionResult:
        from browser.safe_browsing_policy import check_url

        verdict = check_url(url)
        if not verdict.allowed:
            self._corpus.write_refusal(
                task_id=self.task.task_id,
                trigger="action",
                layer="L5",
                category=verdict.reason,
                violating_excerpt=url[:200],
                benchmark=self.task.source_benchmark,
            )
            return ActionResult(
                action=AgentAction(action_type=ActionType.CLICK, step=self._step, target=url),
                success=False,
                error=f"URL blocked by safe_browsing_policy: {verdict.reason}",
            )
        if self._page:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return ActionResult(
            action=AgentAction(action_type=ActionType.CLICK, step=self._step, target=url),
            success=True,
            metadata={"navigated_to": url},
        )
