"""Accessibility tree reader for browser agents."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def get_accessibility_tree(page: Any) -> dict:
    """Return Playwright accessibility snapshot as a dict."""
    try:
        return page.accessibility.snapshot() or {}
    except Exception as exc:
        log.error("[accessibility_reader] snapshot failed: %s", exc)
        return {}


def accessibility_hash(tree: dict) -> str:
    payload = json.dumps(tree, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def find_by_role(tree: dict, role: str, name: str | None = None) -> list[dict]:
    """Walk the accessibility tree, collecting all nodes with a given role."""
    results: list[dict] = []

    def walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        if node.get("role", "").lower() == role.lower():
            if name is None or name.lower() in (node.get("name") or "").lower():
                results.append(node)
        for child in node.get("children", []):
            walk(child)

    walk(tree)
    return results


def find_by_name(tree: dict, name: str) -> list[dict]:
    results: list[dict] = []

    def walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        if name.lower() in (node.get("name") or "").lower():
            results.append(node)
        for child in node.get("children", []):
            walk(child)

    walk(tree)
    return results


def is_node_focused(tree: dict) -> bool:
    """Check if any node in the tree is focused."""

    def walk(node: dict) -> bool:
        if not isinstance(node, dict):
            return False
        if node.get("focused"):
            return True
        return any(walk(c) for c in node.get("children", []))

    return walk(tree)


def get_focusable_elements(tree: dict) -> list[dict]:
    focusable_roles = {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "listbox",
        "menuitem",
        "tab",
    }
    results: list[dict] = []

    def walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        if node.get("role", "").lower() in focusable_roles:
            results.append(node)
        for child in node.get("children", []):
            walk(child)

    walk(tree)
    return results
