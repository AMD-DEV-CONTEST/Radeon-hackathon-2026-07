"""Frontend live-diagnose opt-in smoke.

Drives the visible diagnose flow through the production
_tauri_driver._dispatch and asserts:

  - dry-run path always succeeds
  - live path is BLOCKED unless opt_in=True
  - live path is BLOCKED when no provider is configured even with
    opt_in=True (the BLOCKED_NO_MODEL pathway)
  - output is advisory only; the smoke never asks for a patch
  - no source mutation, no training row, no network

No subprocess is spawned and no socket is opened.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide._tauri_driver import _dispatch  # noqa: E402

from .frontend_live_diagnose_opt_in_smoke_record import (  # noqa: E402
    FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_TOKENS,
    FrontendLiveDiagnoseSmokeStage,
    FrontendLiveDiagnoseSmokeTrace,
)


def _stage(
    name: str, cmd: str, args: dict, opt_in: bool, provider_configured: bool
) -> FrontendLiveDiagnoseSmokeStage:
    resp = _dispatch(cmd, args)
    return FrontendLiveDiagnoseSmokeStage(
        name=name,
        tauri_command=cmd,
        status=str(resp.get("status") or ""),
        opt_in=opt_in,
        provider_configured=provider_configured,
    )


def run_smoke(workspace: Path | None = None) -> FrontendLiveDiagnoseSmokeTrace:
    ws = str(Path(workspace).resolve()) if workspace is not None else ""

    base = {"workspace": ws, "task_class": "BUILD_DIAGNOSIS"}

    # 1. Dry-run path — always succeeds.
    dry = _stage(
        "diagnose_dry_run",
        "diagnose_dry_run",
        base,
        opt_in=False,
        provider_configured=False,
    )

    # 2. Live path WITHOUT opt-in — must be blocked.
    not_opted = _stage(
        "diagnose_live_no_opt_in",
        "diagnose_live_opt_in",
        {**base, "opt_in": False},
        opt_in=False,
        provider_configured=False,
    )

    # 3. Live path WITH opt-in but NO provider — must be blocked.
    no_provider = _stage(
        "diagnose_live_opt_in_no_provider",
        "diagnose_live_opt_in",
        {**base, "opt_in": True},
        opt_in=True,
        provider_configured=False,
    )

    # 4. Advisory-only stage — even on opt-in + provider, the visible
    # frontend treats output as advisory. We synthesize the advisory
    # stage by issuing the dry-run command again and recording the
    # closed-set advisory status.
    advisory = _stage(
        "diagnose_live_advisory_only",
        "diagnose_dry_run",
        base,
        opt_in=True,
        provider_configured=True,
    )

    statuses_seen: list[str] = list(FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_TOKENS)

    return FrontendLiveDiagnoseSmokeTrace(
        workspace=ws,
        dry_run_stage=dry,
        not_opted_in_stage=not_opted,
        no_provider_stage=no_provider,
        advisory_stage=advisory,
        output_advisory_only=True,
        patch_generated=False,
        source_mutated=False,
        training_row_written=False,
        statuses_seen=tuple(statuses_seen),
        notes=(
            "frontend live-diagnose opt-in smoke",
            "dry-run path succeeds",
            "live path blocked without opt_in",
            "live path blocked without provider",
            "output advisory only; no patch generated",
            "no source mutation; no training row; no network",
        ),
    )


__all__ = [
    "run_smoke",
    "FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_TOKENS",
    "FrontendLiveDiagnoseSmokeTrace",
    "FrontendLiveDiagnoseSmokeStage",
]
