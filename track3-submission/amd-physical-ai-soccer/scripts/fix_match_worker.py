#!/usr/bin/env python3
"""Fix patch for match_worker.py — applies the import fallback fix.

This script does NOT modify the original match_worker.py.
Instead, it creates match_worker_fixed.py with the import fix applied.

Root cause: match_worker.py line 81 does:
    from envs.soccer_env_hierarchical import SoccerEnvHierarchical
But the file is at /workspace/radeon-repo/soccer_env_hierarchical.py (top level),
NOT inside an envs/ package. This causes ModuleNotFoundError for all 6 workers.

Fix: Add try/except import fallback, same as render_hierarchical.py does.
"""
import os
import sys

ORIGINAL = "/workspace/radeon-repo/match_worker.py"
FIXED = "/workspace/radeon-repo/match_worker_fixed.py"


def apply_fix():
    """Create a fixed copy of match_worker.py."""
    if not os.path.exists(ORIGINAL):
        print(f"[fix_match_worker] ERROR: {ORIGINAL} not found")
        return False

    with open(ORIGINAL, "r") as f:
        content = f.read()

    # The problematic line (line 81 area):
    #   from envs.soccer_env_hierarchical import SoccerEnvHierarchical
    old_import = "from envs.soccer_env_hierarchical import SoccerEnvHierarchical"

    # Replacement with fallback (same pattern as render_hierarchical.py):
    new_import = """try:
        from envs.soccer_env_hierarchical import SoccerEnvHierarchical
    except ImportError:
        from soccer_env_hierarchical import SoccerEnvHierarchical"""

    if old_import not in content:
        print(f"[fix_match_worker] WARNING: Could not find expected import line")
        print(f"[fix_match_worker] The file may already be fixed or have different code")
        # Check if it already has the fix
        if "from soccer_env_hierarchical import SoccerEnvHierarchical" in content:
            print(f"[fix_match_worker] Fix already present")
            return True
        return False

    fixed_content = content.replace(old_import, new_import)

    # Also fix: the setup() method references 'envs' in sys.path but doesn't add PROJECT_ROOT
    # Add sys.path fix after the existing sys.path.insert
    old_path = 'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))'
    new_path = """sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Also add parent directory for envs/ package compatibility
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))"""

    if old_path in fixed_content:
        fixed_content = fixed_content.replace(old_path, new_path)

    with open(FIXED, "w") as f:
        f.write(fixed_content)

    print(f"[fix_match_worker] Fixed copy saved to: {FIXED}")
    print(f"[fix_match_worker] Changes:")
    print(f"  1. Added import fallback: try envs.soccer_env_hierarchical, except: soccer_env_hierarchical")
    print(f"  2. Added parent directory to sys.path for envs/ package")

    return True


if __name__ == "__main__":
    success = apply_fix()
    sys.exit(0 if success else 1)
