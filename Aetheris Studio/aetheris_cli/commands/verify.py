"""
Verification subcommand implementation (aetheris verify).
Verifies the cryptographic hash-chain integrity of a session's Flight Recorder audit log file.
"""

import json
import os
import sys
from typing import Optional


def verify_session_command(session_id_or_path: str, json_mode: bool = False) -> int:
    log_path = session_id_or_path
    if not os.path.exists(log_path):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
        possible_path = os.path.join(project_root, "logs", "audit", f"{session_id_or_path}.jsonl")
        if os.path.exists(possible_path):
            log_path = possible_path

    if not os.path.exists(log_path):
        if json_mode:
            sys.stdout.write(json.dumps({"ok": False, "error": f"Log file not found: {session_id_or_path}"}) + "\n")
        else:
            sys.stderr.write(f"Error: Audit log file not found for '{session_id_or_path}'.\n")
        return 8

    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
        script_path = os.path.join(project_root, "scripts", "audit_verify.py")

        if os.path.exists(script_path):
            import importlib.util
            spec = importlib.util.spec_from_file_location("audit_verify", script_path)
            if spec and spec.loader:
                audit_verify = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(audit_verify)
                ok, count, first_bad_seq, errors = audit_verify.verify(log_path)

                if json_mode:
                    sys.stdout.write(json.dumps({
                        "ok": ok,
                        "verified_entries": count,
                        "failed_seq": first_bad_seq,
                        "errors": errors,
                    }) + "\n")
                else:
                    if ok:
                        sys.stdout.write(f"OK -- {count} entries verified, chain intact for '{log_path}'.\n")
                    else:
                        sys.stderr.write(f"FAILED at entry seq={first_bad_seq} ({count} entries verified before failure).\n")
                        for err in errors:
                            sys.stderr.write(f"  {err}\n")

                return 0 if ok else 8

    except Exception as e:
        if json_mode:
            sys.stdout.write(json.dumps({"ok": False, "error": str(e)}) + "\n")
        else:
            sys.stderr.write(f"Verification exception: {e}\n")
        return 8

    return 8
