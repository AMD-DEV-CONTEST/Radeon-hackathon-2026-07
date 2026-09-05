#!/usr/bin/env python3
"""Create (or update) a MedGlass account.

The web dashboard is login-gated. On first boot the server seeds an admin
account from MEDGLASS_LOGIN_USER / MEDGLASS_LOGIN_PASSWORD, or logs a random
one-time password. This script is a convenient alternative for operators:

    python3 scripts/add_user.py alice 's3cure-pass' --role clinician

Stores accounts (scrypt-hashed) in output/users.json. Run from the repo root.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The server starts from the repo root (uvicorn --app-dir src), so its data
# stores live under <repo>/output/. Run from there so we touch the same
# users.json the server reads.
SRC = ROOT
os.chdir(SRC)
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Create/update a MedGlass user.")
    ap.add_argument("username", help="login username")
    ap.add_argument("password", help="password (stored as an scrypt hash)")
    ap.add_argument("--role", default="clinician",
                    choices=["admin", "clinician"],
                    help="account role (default clinician)")
    args = ap.parse_args()

    import users  # noqa: E402  (path fix above)

    if not args.password:
        print("error: password must not be empty", file=sys.stderr)
        return 1

    users.create_user(args.username, args.password, role=args.role)
    print(f"ok: {args.username!r} upserted with role={args.role!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
