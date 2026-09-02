"""
Desktop oracle — verifies task completion criteria for desktop agents.
Every trace must include: screenshot hash, window title, action, verifier result, safety decision.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import OracleType, OracleVerdict

log = logging.getLogger(__name__)


def screenshot_contains_text(screenshot_path: str, expected_text: str) -> OracleVerdict:
    from vision.ocr_scanner import find_text_in_image

    try:
        matches = find_text_in_image(screenshot_path, expected_text)
        passed = len(matches) > 0
        return OracleVerdict(
            oracle_type=OracleType.DESKTOP,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"text={expected_text!r} found={passed} matches={len(matches)}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.DESKTOP, passed=False, score=0.0, evidence=str(exc)
        )


def window_title_matches(
    screen_controller: Any, expected: str, partial: bool = True
) -> OracleVerdict:
    from desktop.window_manager import get_window_list

    try:
        windows = get_window_list(screen_controller)
        titles = [w.get("title", "") for w in windows]
        if partial:
            passed = any(expected.lower() in t.lower() for t in titles)
        else:
            passed = expected in titles
        return OracleVerdict(
            oracle_type=OracleType.DESKTOP,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"expected={expected!r} titles={titles}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.DESKTOP, passed=False, score=0.0, evidence=str(exc)
        )


def visual_match(path_before: str, path_after: str, threshold: float = 0.05) -> OracleVerdict:
    from vision.visual_diff import compare

    try:
        result = compare(path_before, path_after, threshold=threshold)
        return OracleVerdict(
            oracle_type=OracleType.VISUAL,
            passed=result.similar,
            score=max(0.0, 1.0 - result.pixel_diff_score),
            evidence=f"pixel_diff={result.pixel_diff_score:.4f} threshold={threshold}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.VISUAL, passed=False, score=0.0, evidence=str(exc)
        )


def file_exists_in_vm(screen_controller: Any, path: str) -> OracleVerdict:
    """
    Verify a file exists inside the VM by running a command and checking output.
    screen_controller must support execute_command(cmd) -> str.
    """
    try:
        cmd_result = getattr(screen_controller, "execute_command", lambda c: "")(
            "test -f " + path + " && echo EXISTS || echo MISSING"
        )
        passed = "EXISTS" in (cmd_result or "")
        return OracleVerdict(
            oracle_type=OracleType.DESKTOP,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"path={path} result={cmd_result!r}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.DESKTOP, passed=False, score=0.0, evidence=str(exc)
        )
