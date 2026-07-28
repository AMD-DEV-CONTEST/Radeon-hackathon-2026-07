"""
Audit package export subcommand implementation (aetheris export).
Bundles session log files, verification scripts, and verification metadata into a standalone ZIP file for third-party client audit.
"""

import os
import sys
import zipfile


def export_command(session_id: str, output_zip_path: str = "") -> int:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))

    log_path = os.path.join(project_root, "logs", "audit", f"{session_id}.jsonl")
    if not os.path.exists(log_path):
        sys.stderr.write(f"Error: Audit log file for session '{session_id}' not found at {log_path}\n")
        return 1

    if not output_zip_path:
        output_zip_path = f"{session_id}_audit_bundle.zip"

    script_path = os.path.join(project_root, "scripts", "audit_verify.py")

    try:
        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(log_path, arcname=f"{session_id}.jsonl")
            if os.path.exists(script_path):
                zf.write(script_path, arcname="audit_verify.py")

            readme_content = (
                f"Aetheris Audit Verification Bundle\n"
                f"Session ID: {session_id}\n\n"
                f"To verify this audit trail independently without Aetheris installed:\n"
                f"  python audit_verify.py {session_id}.jsonl\n"
            )
            zf.writestr("README.txt", readme_content)

        sys.stdout.write(f"Audit package created successfully: {output_zip_path}\n")
        return 0
    except Exception as e:
        sys.stderr.write(f"Failed to create export zip: {e}\n")
        return 1
