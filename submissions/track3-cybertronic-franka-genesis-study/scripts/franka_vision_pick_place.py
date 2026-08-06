"""Launcher for the vision-guided apple-to-plate pick-and-place demo."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from franka_vision_pick_place import main  # noqa: E402


if __name__ == "__main__":
    main()
