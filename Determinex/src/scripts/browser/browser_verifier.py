"""
Browser oracle — verifies task completion criteria after actions.
Returns OracleVerdict from the base_agent contract.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agents.base_agent import OracleType, OracleVerdict

log = logging.getLogger(__name__)


def url_matches(page: Any, expected_url: str, partial: bool = True) -> OracleVerdict:
    try:
        actual = page.url
        passed = expected_url in actual if partial else actual == expected_url
        return OracleVerdict(
            oracle_type=OracleType.BROWSER,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"url={actual} expected={expected_url}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.BROWSER, passed=False, score=0.0, evidence=str(exc)
        )


def selector_exists(page: Any, selector: str) -> OracleVerdict:
    try:
        count = page.locator(selector).count()
        passed = count > 0
        return OracleVerdict(
            oracle_type=OracleType.DOM,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"selector={selector} count={count}",
        )
    except Exception as exc:
        return OracleVerdict(oracle_type=OracleType.DOM, passed=False, score=0.0, evidence=str(exc))


def text_exists(page: Any, text: str, case_sensitive: bool = False) -> OracleVerdict:
    from browser.dom_reader import extract_visible_text

    try:
        content = extract_visible_text(page) or ""
        if not case_sensitive:
            passed = text.lower() in content.lower()
        else:
            passed = text in content
        return OracleVerdict(
            oracle_type=OracleType.DOM,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"text={text!r} found={passed}",
        )
    except Exception as exc:
        return OracleVerdict(oracle_type=OracleType.DOM, passed=False, score=0.0, evidence=str(exc))


def form_value_matches(page: Any, selector: str, expected_value: str) -> OracleVerdict:
    from browser.dom_reader import get_input_value

    try:
        actual = get_input_value(page, selector)
        passed = actual == expected_value
        return OracleVerdict(
            oracle_type=OracleType.DOM,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"selector={selector} actual={actual!r} expected={expected_value!r}",
        )
    except Exception as exc:
        return OracleVerdict(oracle_type=OracleType.DOM, passed=False, score=0.0, evidence=str(exc))


def accessibility_node_exists(page: Any, role: str, name: str | None = None) -> OracleVerdict:
    from browser.accessibility_reader import find_by_role, get_accessibility_tree

    try:
        tree = get_accessibility_tree(page)
        nodes = find_by_role(tree, role, name)
        passed = len(nodes) > 0
        return OracleVerdict(
            oracle_type=OracleType.ACCESSIBILITY,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"role={role} name={name} found={len(nodes)}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.ACCESSIBILITY, passed=False, score=0.0, evidence=str(exc)
        )


def visual_region_matches(
    screenshot_path_a: str,
    screenshot_path_b: str,
    threshold: float = 0.05,
) -> OracleVerdict:
    from vision.visual_diff import compare

    try:
        result = compare(screenshot_path_a, screenshot_path_b, threshold=threshold)
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


def run_evaluator(evaluator_fn: Callable[..., bool], *args: Any, **kwargs: Any) -> OracleVerdict:
    """Run a custom task-specific evaluator function."""
    try:
        passed = bool(evaluator_fn(*args, **kwargs))
        return OracleVerdict(
            oracle_type=OracleType.BROWSER,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"custom_evaluator={evaluator_fn.__name__}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.BROWSER, passed=False, score=0.0, evidence=str(exc)
        )
