"""Ledger integrity must be reported from evidence, never defaulted.

`public_readiness_spine_dashboard_status` read:

    pre_chain_valid      = bool(pre.get("ledger_chain_valid", True))
    pre_mutation_detected = bool(pre.get("mutation_detected", False))

Both values are display-only -- they populate the dashboard and gate nothing -- which is
precisely why the defaults mattered. A checkpoint that said nothing about the hash chain was
reported as "chain valid, no mutation detected". The dashboard's entire job is to state what
the evidence says, and on absent evidence it stated the reassuring answer.

Found 2026-08-02 by an AST scan for `.get(..., <success literal>)`, the same scan that found
the authority-boundary hole. Latent, not live: the current reconciliation record carries both
keys, which is what made tightening it safe.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide import public_readiness_spine_dashboard_status as M  # noqa: E402

_RECON_PARAM = next(
    (p for p in __import__("inspect").signature(M.load).parameters if "recon" in p.lower()),
    None,
)


def _stage(mutate) -> Path:
    chosen = M._locate_latest_evidence(M._RECON_010_DIR)
    assert chosen is not None
    blob = json.loads(chosen.read_text(encoding="utf-8"))
    mutate(blob)
    d = Path(tempfile.mkdtemp())
    (d / chosen.name).write_text(json.dumps(blob), encoding="utf-8")
    return d


def test_the_live_dashboard_still_passes():
    """Load-bearing negative control: tightening a reporting gate must not move it."""
    assert M.load().decision.endswith("PASSED")


def test_the_real_checkpoint_carries_both_integrity_keys():
    """Documents why the fix was safe, and fails loudly if an evidence generator stops
    emitting them -- instead of the dashboard silently starting to block."""
    blob = json.loads(M._locate_latest_evidence(M._RECON_010_DIR).read_text(encoding="utf-8"))
    pre = blob.get("post_claude_pre_reconciliation_checkpoint") or {}
    for key in ("ledger_chain_valid", "mutation_detected"):
        assert key in pre, f"reconciliation evidence no longer states {key}"


def test_a_checkpoint_without_chain_validity_blocks_instead_of_claiming_valid():
    assert _RECON_PARAM, "load() must expose the reconciliation dir for testing"
    d = _stage(lambda b: b["post_claude_pre_reconciliation_checkpoint"].pop("ledger_chain_valid"))
    st = M.load(**{_RECON_PARAM: d})
    assert "BLOCKED" in st.decision, st.decision
    assert any("ledger_chain_valid" in str(n) for n in st.notes)


def test_a_checkpoint_without_mutation_status_blocks_instead_of_claiming_none():
    """`mutation_detected` defaulted to False -- 'no tampering seen' asserted from silence."""
    assert _RECON_PARAM
    d = _stage(lambda b: b["post_claude_pre_reconciliation_checkpoint"].pop("mutation_detected"))
    st = M.load(**{_RECON_PARAM: d})
    assert "BLOCKED" in st.decision, st.decision
    assert any("mutation_detected" in str(n) for n in st.notes)


def test_a_genuinely_invalid_chain_is_reported_as_invalid_not_blocked():
    """Negative control for the fix: present-and-False must still flow through as a real
    reported value. Converting every falsy integrity signal into a block would hide the very
    finding the dashboard exists to show."""
    assert _RECON_PARAM
    d = _stage(
        lambda b: b["post_claude_pre_reconciliation_checkpoint"].update(
            {"ledger_chain_valid": False}
        )
    )
    st = M.load(**{_RECON_PARAM: d})
    assert "ledger_chain_valid is absent" not in str(st.notes)
