"""
Deterministic per-project session id derivation, shared by every CLI subcommand.

The id is a hash of the project folder, so relaunching the CLI in the same
directory resumes the same chat session, the same Flight Recorder trail,
and the same Time-Travel shadow ref.

The path is NORMALIZED before hashing (absolute, normcase, no trailing
separator). Hashing the raw string looks like it works until two commands
spell the same folder differently -- `aetheris chat` hashing os.getcwd()
("C:\\proj") and `aetheris undo -p C:/proj` hashing what the user typed
produce different ids for one folder, so the undo finds an empty timeline
and reports "no checkpoints" for edits that are sitting right there.
Reproduced directly while building `aetheris undo`.
"""

import hashlib
import os


def project_session_id(project_dir: str, prefix: str = "cli") -> str:
    """Stable session id for `project_dir`. Same folder -> same id,
    regardless of separator style, relative form, or (on Windows) case."""
    normalized = os.path.normcase(os.path.abspath(project_dir or os.getcwd()))
    normalized = normalized.rstrip("\\/") or normalized
    return f"{prefix}-{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:12]}"
