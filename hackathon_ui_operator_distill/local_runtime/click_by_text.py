from __future__ import annotations

import argparse
import time

from local_ui_runtime import click_element, find_by_text, scan_screen


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan screen and click an element by visible/accessibility text.")
    parser.add_argument("text", help="Button/input/link text to click.")
    parser.add_argument("--dry-run", action="store_true", help="Only print target, do not click.")
    args = parser.parse_args()

    elements = scan_screen()
    target = find_by_text(elements, args.text)
    if target is None:
        raise SystemExit(f"No matching UI element found for: {args.text}")

    print({
        "role": target.role,
        "label": target.label,
        "source": target.source,
        "bounds": target.bounds,
        "center": target.center,
        "confidence": target.confidence,
    })

    if args.dry_run:
        return

    before = [element.center for element in elements]
    click_element(target)
    time.sleep(0.6)
    after = [element.center for element in scan_screen()]
    print({"clicked": target.label, "screen_map_changed": before != after})


if __name__ == "__main__":
    main()

