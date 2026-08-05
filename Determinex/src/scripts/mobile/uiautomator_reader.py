"""UIAutomator XML reader — extracts the Android accessibility/UI tree."""

from __future__ import annotations

import logging
import subprocess
import xml.etree.ElementTree as ET
from typing import Any

log = logging.getLogger(__name__)


def dump_ui_xml(serial: str) -> str:
    """Dump UIAutomator XML from device."""
    try:
        remote = "/sdcard/determinex_ui_dump.xml"
        subprocess.run(
            ["adb", "-s", serial, "shell", "uiautomator", "dump", remote],
            capture_output=True,
            timeout=15,
        )
        result = subprocess.run(
            ["adb", "-s", serial, "shell", "cat", remote],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout
    except Exception as exc:
        log.error("[uiautomator] dump_ui_xml failed: %s", exc)
        return ""


def parse_ui_tree(xml_text: str) -> list[dict[str, Any]]:
    """Parse UIAutomator XML into a flat list of element dicts."""
    elements: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
        _walk(root, elements)
    except ET.ParseError as exc:
        log.error("[uiautomator] XML parse failed: %s", exc)
    return elements


def _walk(node: ET.Element, out: list) -> None:
    attrib = node.attrib
    bounds = attrib.get("bounds", "")
    x, y, w, h = 0, 0, 0, 0
    if bounds:
        try:
            parts = bounds.replace("][", ",").strip("[]").split(",")
            x1, y1, x2, y2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            x, y, w, h = x1, y1, x2 - x1, y2 - y1
        except (ValueError, IndexError):
            pass
    out.append(
        {
            "class": attrib.get("class", ""),
            "resource_id": attrib.get("resource-id", ""),
            "text": attrib.get("text", ""),
            "content_desc": attrib.get("content-desc", ""),
            "clickable": attrib.get("clickable", "false") == "true",
            "enabled": attrib.get("enabled", "true") == "true",
            "focused": attrib.get("focused", "false") == "true",
            "x": x,
            "y": y,
            "w": w,
            "h": h,
        }
    )
    for child in node:
        _walk(child, out)


def find_element(
    elements: list[dict],
    text: str | None = None,
    resource_id: str | None = None,
    class_name: str | None = None,
) -> list[dict]:
    results = []
    for el in elements:
        if text and text.lower() not in el.get("text", "").lower():
            continue
        if resource_id and resource_id not in el.get("resource_id", ""):
            continue
        if class_name and class_name not in el.get("class", ""):
            continue
        results.append(el)
    return results


def get_element_center(element: dict) -> tuple[int, int]:
    return element["x"] + element["w"] // 2, element["y"] + element["h"] // 2
