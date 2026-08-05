#!/usr/bin/env python3
"""
determinex_backend_cli.py -- JSON CLI over the IDE backend (for any editor frontend)
=================================================================================
A stable, transport-agnostic entry point so ANY frontend -- the Tauri shell, a
VS Code extension, a web app, a shell script -- can call Determinex's governed
backend commands the same way: argv command + a JSON args blob, JSON result out.

    python scripts/ide/determinex_backend_cli.py commands
    python scripts/ide/determinex_backend_cli.py preview_idea_oracle \
        --json '{"idea_text": "Write add(a,b). Examples: add(2,3)==5."}'
    python scripts/ide/determinex_backend_cli.py repair_diagnose \
        --json '{"workspace": "C:/path/to/repo"}'
    python scripts/ide/determinex_backend_cli.py get_governance_status

It delegates to TauriBackendBridge (which delegates to the governed command
surface, which delegates to the canonical engine). Nothing new is implemented
here -- it is the thinnest possible adapter so the editor layer never reaches
into Python internals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
for p in (str(_SCRIPTS), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _result_to_dict(res) -> dict:
    return {
        "status": getattr(res, "status", ""),
        "payload": getattr(res, "payload", {}) or {},
        "notes": list(getattr(res, "notes", ()) or ()),
    }


# Commands that invoke a model -- they need a LOCAL model config or the surface
# (correctly) blocks NO_MODEL. We build that config via the canonical wizard so the
# pinned-id / local-only / task-class checks still run (we satisfy the gate, not bypass it).
_MODEL_COMMANDS = {"build_idea", "diagnose_live_opt_in", "generate_patch_plan"}
_DEFAULT_LOCAL_MODEL = "determinex-engineer-v11-dsl"  # pinned; ollama resolves to :latest


def _build_local_config(model_id: str):
    """Opt-in LOCAL model config via the wizard (no duplication, free by construction).
    A blocked/invalid id -> None, which the surface reports as NO_MODEL."""
    try:
        from models.local_model_config_wizard import LocalModelConfigWizard, WizardConfig
    except Exception:
        return None
    root = Path.home() / ".determinex" / "local_models"
    rec = LocalModelConfigWizard(WizardConfig(config_root=root)).write_config(
        provider="ollama",
        model_id=model_id or _DEFAULT_LOCAL_MODEL,
        capabilities=("code",),
        task_classes_allowed=("BUILD_DIAGNOSIS",),
        enabled=True,
    )
    return rec if getattr(rec, "is_written", False) else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex backend JSON CLI")
    ap.add_argument("command")
    ap.add_argument("--json", default="{}", help="JSON args blob")
    args = ap.parse_args()

    from ide.tauri_backend_bridge import TauriBackendBridge, tauri_commands

    if args.command == "commands":
        print(json.dumps({"commands": list(tauri_commands())}))
        return 0

    try:
        kw = json.loads(args.json or "{}")
    except Exception as e:
        print(json.dumps({"status": "BAD_JSON", "error": str(e)}))
        return 2

    # map known string args into the bridge's typed kwargs
    call_kw = {}
    if "workspace" in kw and kw["workspace"]:
        call_kw["workspace"] = Path(kw["workspace"])
    for key in ("idea_text", "task_class", "verifier_status", "unified_diff"):
        if key in kw:
            call_kw[key] = kw[key]
    if "opt_in" in kw:
        call_kw["opt_in"] = bool(kw["opt_in"])

    config = None
    if args.command in _MODEL_COMMANDS or kw.get("model_id"):
        config = _build_local_config(str(kw.get("model_id") or ""))

    known = tuple(tauri_commands())
    if args.command not in known:
        # EXIT NON-ZERO, and say what IS available.
        #
        # The bridge already answers honestly -- status TAURI_COMMAND_BLOCKED_UNKNOWN -- but
        # this CLI printed that and returned 0, so every caller that checks an exit code saw
        # SUCCESS for a command that does not exist. Found 2026-08-02 by sweeping all 31
        # names in backend_command_surface.py through this CLI: 24 of them are not on the
        # bridge, and every one produced a well-formed envelope and exit 0.
        #
        # That gap is real and separate: this file's docstring promises "ANY frontend -- the
        # Tauri shell, a VS Code extension, a web app, a shell script -- can call
        # Determinex's governed backend commands the same way", and the bridge exposes 14 of
        # 31. The Tauri desktop app reaches the rest through its own Rust commands, so the
        # shortfall is invisible there and total for everyone else. Widening the bridge is a
        # governance decision about which commands are safe to expose transport-agnostically;
        # failing loudly is not, and it is what stops a caller acting on a success that
        # never happened.
        print(json.dumps({
            "status": "TAURI_COMMAND_BLOCKED_UNKNOWN",
            "payload": {},
            "notes": [
                f"unknown backend command {args.command!r}",
                f"this CLI exposes {len(known)} commands: {', '.join(sorted(known))}",
                "commands implemented in ide/backend_command_surface.py but not bridged here "
                "are reachable only from the Tauri shell's Rust layer",
            ],
        }))
        return 2

    try:
        res = TauriBackendBridge().call(args.command, config=config, **call_kw)
    except Exception as e:
        print(json.dumps({"status": "BACKEND_ERROR", "error": str(e)}))
        return 1
    print(json.dumps(_result_to_dict(res)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
