"""Compatibility launcher for the Franka fruit-following demo.

The implementation lives in ../src to match the submission repository layout.
This wrapper keeps the original script path working:

    python scripts/franka_fruit_follow.py
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from franka_fruit_follow import main  # noqa: E402


if __name__ == "__main__":
    main()
