"""
Mobile oracle — verifies task completion criteria for mobile agents.
"""

from __future__ import annotations

import logging
import subprocess

from agents.base_agent import OracleType, OracleVerdict

log = logging.getLogger(__name__)


def _adb(serial: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", serial] + list(args), capture_output=True, text=True, timeout=15
    )


def package_opened(serial: str, package: str) -> OracleVerdict:
    try:
        r = _adb(serial, "shell", "dumpsys", "activity", "activities")
        passed = package in r.stdout
        return OracleVerdict(
            oracle_type=OracleType.MOBILE,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"package={package} found={passed}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.MOBILE, passed=False, score=0.0, evidence=str(exc)
        )


def activity_matches(serial: str, expected_activity: str) -> OracleVerdict:
    try:
        r = _adb(serial, "shell", "dumpsys", "activity", "activities")
        passed = expected_activity in r.stdout
        return OracleVerdict(
            oracle_type=OracleType.MOBILE,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"activity={expected_activity} found={passed}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.MOBILE, passed=False, score=0.0, evidence=str(exc)
        )


def ui_text_exists(serial: str, text: str) -> OracleVerdict:
    from mobile.uiautomator_reader import dump_ui_xml, find_element, parse_ui_tree

    try:
        xml = dump_ui_xml(serial)
        elements = parse_ui_tree(xml)
        matches = find_element(elements, text=text)
        passed = len(matches) > 0
        return OracleVerdict(
            oracle_type=OracleType.MOBILE,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"text={text!r} found={passed} matches={len(matches)}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.MOBILE, passed=False, score=0.0, evidence=str(exc)
        )


def screenshot_region_matches(
    path_before: str,
    path_after: str,
    threshold: float = 0.05,
) -> OracleVerdict:
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


def file_exists_on_device(serial: str, path: str) -> OracleVerdict:
    try:
        r = _adb(serial, "shell", "test", "-f", path, "&&", "echo", "YES")
        passed = "YES" in r.stdout
        return OracleVerdict(
            oracle_type=OracleType.MOBILE,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"path={path} exists={passed}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.MOBILE, passed=False, score=0.0, evidence=str(exc)
        )


def permission_dialog_handled(serial: str, expected_button: str = "Allow") -> OracleVerdict:
    from mobile.uiautomator_reader import dump_ui_xml, find_element, parse_ui_tree

    try:
        xml = dump_ui_xml(serial)
        elements = parse_ui_tree(xml)
        matches = find_element(elements, text=expected_button)
        # If button still visible, dialog was not handled
        passed = len(matches) == 0
        return OracleVerdict(
            oracle_type=OracleType.MOBILE,
            passed=passed,
            score=1.0 if passed else 0.0,
            evidence=f"button={expected_button!r} still_visible={not passed}",
        )
    except Exception as exc:
        return OracleVerdict(
            oracle_type=OracleType.MOBILE, passed=False, score=0.0, evidence=str(exc)
        )
