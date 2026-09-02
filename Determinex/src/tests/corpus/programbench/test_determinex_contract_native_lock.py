"""Tests for determinex_contract.native_code_contract.

2026-07-02: py_contract (ast.parse -- PYTHON syntax) was being applied
unconditionally in determinex_pb_reimpl.py, including to native (--lang
c/rust/go/...) candidates. Real C/Rust/Go source essentially never parses as
Python, so every native candidate was failing its own contract check and
burning resample budget on a check that could never pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from determinex_contract import native_code_contract, py_contract  # noqa: E402


def test_native_contract_accepts_real_c_code():
    code = '#include <stdio.h>\nint main() { printf("hi"); return 0; }\n'
    ok, _ = native_code_contract(code)
    assert ok is True


def test_py_contract_wrongly_rejects_real_c_code():
    # documents the bug this fix routes around -- py_contract is PYTHON-only.
    code = '#include <stdio.h>\nint main() { printf("hi"); return 0; }\n'
    ok, _ = py_contract(code)
    assert ok is False


def test_native_contract_rejects_prose():
    ok, reason = native_code_contract("I think the answer is to use getopt.")
    assert ok is False
    assert "prose" in reason


def test_native_contract_rejects_truncated_output():
    ok, reason = native_code_contract("int main() { if (x) {")
    assert ok is False
    assert "unbalanced" in reason


def test_native_contract_rejects_empty():
    ok, reason = native_code_contract("   ")
    assert ok is False
    assert reason == "empty output"


def test_native_contract_accepts_rust_code():
    code = 'fn main() {\n    println!("hi");\n}\n'
    ok, _ = native_code_contract(code)
    assert ok is True


def test_native_contract_accepts_fenced_code_block():
    code = "```c\nint main() { return 0; }\n```"
    ok, _ = native_code_contract(code)
    assert ok is True


def test_reimpl_picks_native_contract_for_non_python_lang():
    import determinex_pb_reimpl as reimpl

    assert reimpl.native_code_contract is not None
    assert reimpl.py_contract is not None
