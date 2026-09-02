"""No new silent-success site may appear on a load-bearing surface.

Six instances of "a failure or an unknown becomes a success" were found by hand on
2026-08-02, in six different files. They are one bug wearing six outfits, and grepping for
the last one never finds the next -- so the shape itself is now inventoried, exactly as
`parallel_execution_layer_audit.py` inventories execution sites.

The point of a closed-set classifier over an inventory is that a NEW site cannot be silently
absent: it lands in UNKNOWN_REQUIRES_REVIEW and this test goes red. An exemption is allowed,
but it must be DECLARED with a reason, which makes the exemption list reviewable.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_AUDIT = _ROOT / "scripts" / "dev" / "silent_success_audit.py"

sys.path.insert(0, str(_ROOT / "scripts" / "dev"))
import silent_success_audit as A  # noqa: E402


def test_no_undeclared_silent_success_on_a_load_bearing_surface():
    rows = A.audit()
    unknown = [r for r in rows if r["kind"] == "UNKNOWN_REQUIRES_REVIEW"]
    assert not unknown, "undeclared silent-success sites:\n" + "\n".join(
        f"  {r['file']}:{r['line']} {r['symbol']} {r['detail']}" for r in unknown
    )


def test_strict_mode_exits_non_zero_when_something_is_undeclared(tmp_path, monkeypatch):
    """Negative control for the guard itself. A --strict that always exits 0 would keep this
    file green forever while the audit found nothing -- the exact failure mode this project
    has been bitten by (a guard that matched nothing and passed)."""
    plant = _ROOT / "scripts" / "ide" / "_silent_success_audit_probe.py"
    plant.write_text(
        "def probe(d):\n"
        "    try:\n"
        "        return d['x']\n"
        "    except KeyError:\n"
        "        return True\n",
        encoding="utf-8",
    )
    try:
        p = subprocess.run([sys.executable, str(_AUDIT), "--strict"],
                           capture_output=True, text=True, timeout=600, cwd=str(_ROOT))
        assert p.returncode != 0, "a planted silent success must fail --strict"
        assert "_silent_success_audit_probe" in p.stdout
    finally:
        plant.unlink(missing_ok=True)

    clean = subprocess.run([sys.executable, str(_AUDIT), "--strict"],
                           capture_output=True, text=True, timeout=600, cwd=str(_ROOT))
    assert clean.returncode == 0, "and must pass again once it is removed"


def test_the_scanner_does_not_mistake_a_negation_for_success():
    """REGRESSION. The first version matched success tokens as SUBSTRINGS, so
    'IDE_PATCH_PLAN_BLOCKED_SCHEMA_INVALID' matched because INVALID contains VALID -- the
    audit reported a fail-closed default as a silent success, inverting its own finding."""
    assert A._asserts_success("TAURI_COMMAND_OK") is True
    assert A._asserts_success("IDE_PATCH_PLAN_BLOCKED_SCHEMA_INVALID") is False
    assert A._asserts_success("REAL_PATCH_PLAN_CONTEXT_BLOCKED_SCHEMA_INVALID") is False
    assert A._asserts_success("VERIFIER_UNHEALTHY") is False


def test_an_exemption_covers_one_expression_not_a_whole_function():
    """Exemptions are keyed by (file, symbol, detail). A (file, symbol) key would silently
    permit every future silent-success added anywhere inside that function."""
    for key in A._DECLARED_FAIL_CLOSED:
        assert len(key) == 3, f"exemption {key!r} must name the specific expression"
