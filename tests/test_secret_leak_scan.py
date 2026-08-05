"""
THEMIS Automated Secret Leak Scanner
Scans source code, configuration, and documentation files to ensure
no live secrets, API tokens, or credentials are hardcoded or leaked.
"""

import os
import re
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SECRET_PATTERNS = [
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token (classic)"),
    (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth Access Token"),
    (r"glpat-[a-zA-Z0-9\-]{20}", "GitLab Personal Access Token"),
    (r"xox[baprs]-[0-9]{12}-[0-9]{12}-[a-zA-Z0-9]{24}", "Slack API Token"),
    (r"AIzaSy[a-zA-Z0-9_\-]{33}", "Google Cloud API Key"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----", "Private Key Header"),
]

EXCLUDE_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
EXCLUDE_FILES = {"test_secret_leak_scan.py"}


def scan_workspace(root_dir: str):
    print("🔒 Running Automated Secret Leak Scan...")
    violations = []
    scanned_count = 0

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

        for filename in filenames:
            if filename in EXCLUDE_FILES or filename.endswith((".png", ".jpg", ".ico", ".pdf", ".pyc")):
                continue

            filepath = os.path.join(dirpath, filename)
            scanned_count += 1

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                for pattern, name in SECRET_PATTERNS:
                    matches = re.findall(pattern, content)
                    if matches:
                        rel_path = os.path.relpath(filepath, root_dir)
                        violations.append((rel_path, name, len(matches)))

            except Exception as e:
                print(f"⚠️  Could not read {filepath}: {e}")

    print(f"✅ Scanned {scanned_count} files.")
    if violations:
        print("❌ SECRET LEAKS DETECTED:")
        for path, name, count in violations:
            print(f"   • [{name}] found in {path} ({count} occurrence(s))")
        sys.exit(1)
    else:
        print("🟢 ZERO SECRET LEAKS FOUND — Workspace clean and ready for submission!")


if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    scan_workspace(project_root)
