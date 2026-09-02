"""PreToolUse hook: surface what the corpus already knows before a file is edited.

WHY A HOOK AND NOT A DOCUMENTED STEP
------------------------------------
AUDIT BEFORE BUILD is already the project's stated rule, and it is already in CLAUDE.md.
It still did not prevent the num_ctx bug from being rediscovered on 2026-08-01, for two
compounding reasons: the knowledge existed only as a code comment in one module (so no
query could have found it -- see class knowledge_that_lives_only_in_a_code_comment), and
consulting the corpus required already suspecting there was something to consult.

A rule that depends on remembering to follow it fails exactly when someone is deep in a
problem, which is when it matters. This makes the consult automatic and costs one JSON
read of a file that is already on disk.

ADVISORY, NEVER BLOCKING. It prints context and exits 0 unconditionally. A hook that can
block an edit because a keyword matched would be disabled within a day, and a disabled
hook surfaces nothing at all.

    "hooks": {
      "PreToolUse": [
        {"matcher": "Edit|Write",
         "hooks": [{"type": "command",
                    "command": "python scripts/dev/corpus_brief_hook.py"}]}
      ]
    }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# One reminder per file per session. Repeating the same six lines on every edit of the
# same file is how advisory output becomes noise that gets scrolled past.
SEEN = REPO / ".determinex" / "corpus_brief_seen.json"


def _already_shown(path: str) -> bool:
    try:
        seen = set(json.loads(SEEN.read_text(encoding="utf-8")))
    except Exception:
        seen = set()
    if path in seen:
        return True
    seen.add(path)
    try:
        SEEN.parent.mkdir(parents=True, exist_ok=True)
        SEEN.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    except Exception:
        pass  # a cache write failure must never cost the reminder itself
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = payload.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("path") or ""
    if not target:
        return 0

    try:
        rel = str(Path(target).resolve().relative_to(REPO)).replace("\\", "/")
    except Exception:
        return 0  # outside the repo -- the corpus has nothing to say about it

    if _already_shown(rel):
        return 0

    try:
        from determinex_corpus_api import brief, format_brief

        text = format_brief(brief([rel]), [rel])
    except Exception:
        return 0  # the corpus being unreadable must not stop anyone working

    if text:
        print(text, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
