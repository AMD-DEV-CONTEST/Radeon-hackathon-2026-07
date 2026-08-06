#!/usr/bin/env python3
"""DEPRECATED: thin wrapper around sync_model_to_remote.py.

Kept for backward compatibility. The old name implied a specific GB10 host;
the new script supports any RemoteComputeNode. Existing callers that pass
--host / --remote-dir / --sidecar-url still work — they're just forwarded.

Example (still works):
  python scripts/sync_pi05_to_gb10.py --job-id e829bf6d-... --load

Prefer:
  python scripts/sync_model_to_remote.py --node-id <node> --model-id <id> --load
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

_NEW = Path(__file__).resolve().parent / "sync_model_to_remote.py"
if not _NEW.is_file():
    print(f"ERROR: wrapper target not found: {_NEW}", file=sys.stderr)
    raise SystemExit(1)

# Forward all argv. The new script accepts the same --host / --remote-dir /
# --sidecar-url / --model-id / --job-id / --load / --task-prompt / --status-file
# flags as the old one, plus the new --node-id / --jump.
warnings.warn(
    "sync_pi05_to_gb10.py is deprecated; use sync_model_to_remote.py",
    DeprecationWarning,
    stacklevel=2,
)
os.execv(sys.executable, [sys.executable, str(_NEW), *sys.argv[1:]])
