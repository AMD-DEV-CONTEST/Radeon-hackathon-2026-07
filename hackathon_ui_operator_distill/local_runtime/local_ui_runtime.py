from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pyautogui


ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT.parent / "screen_element_scanner" / "scan_screen.py"
LATEST = ROOT.parent / "screen_element_scanner" / "output" / "latest_elements.json"


@dataclass
class UIElement:
    role: str
    label: str
    bounds: list[int]
    center: list[int]
    source: str
    confidence: float


def scan_screen() -> list[UIElement]:
    if not SCANNER.exists():
        raise FileNotFoundError(f"Scanner not found: {SCANNER}")

    subprocess.run(["python", str(SCANNER), "--quiet"], check=True)
    payload = json.loads(LATEST.read_text(encoding="utf-8"))
    elements = []
    for item in payload.get("elements", []):
        elements.append(
            UIElement(
                role=item.get("role", ""),
                label=item.get("label") or item.get("automation_id") or "",
                bounds=item.get("bounds", [0, 0, 0, 0]),
                center=item.get("center", [0, 0]),
                source=item.get("source", ""),
                confidence=float(item.get("confidence", 0.0)),
            )
        )
    return elements


def find_by_text(elements: list[UIElement], target: str) -> UIElement | None:
    target_norm = target.strip().lower()
    exact = []
    partial = []
    for element in elements:
        label = element.label.strip().lower()
        if not label:
            continue
        if label == target_norm:
            exact.append(element)
        elif target_norm in label:
            partial.append(element)

    candidates = exact or partial
    if not candidates:
        return None

    role_priority = {
        "button": 0,
        "edit": 1,
        "hyperlink": 2,
        "menuitem": 3,
        "tabitem": 4,
    }
    return sorted(candidates, key=lambda e: (role_priority.get(e.role, 10), -e.confidence))[0]


def click_element(element: UIElement) -> None:
    x, y = element.center
    pyautogui.moveTo(x, y, duration=0.15)
    pyautogui.click()
