"""Every oracle must be able to tell correct code from broken code.

`Oracle.available()` asks whether a binary is on PATH. That is not the same as the oracle
working, and on 2026-08-02 running all twelve against a known-good and a known-bad program
found two real defects that a green 5,743-test suite did not:

  * **dotnet certified code that does not compile.** It ran only `dotnet test`, which on a
    non-test project restores and exits 0 without building -- captured output was two lines,
    "Determining projects to restore..." and "Restored ...". No JUnit, so total=0, no
    failures, and `passed = returncode == 0 and not hard` evaluated True. A class whose body
    was `a + oops` came back VERIFIED, under a comment reading "never silent-pass".

  * **swift blamed the user's code for a broken toolchain.** `swift.exe` was on PATH with a
    broken Windows SDK; every build died on `could not build C module 'SwiftOverlayShims'`,
    and the oracle reported the program as failing. Same shape as a timeout reported as a
    "collection or environment error": our problem, described as theirs.

The discriminating test is two programs per language. GOOD must PASS, BAD must FAIL. An
oracle that passes both is not verifying; one that fails both is accusing.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import determinex_oracle as O  # noqa: E402

# Kept to the toolchains that answer in about a second, so this stays runnable in CI. The
# slower ones (dotnet, swift, jvm) are exercised by scripts run on demand.
CASES: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "python": (
        {"solution.py": "def add(a, b):\n    return a + b\n",
         "test_add.py": "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
        {"solution.py": "def add(a, b):\n    return a + b\n",
         "test_add.py": "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 6\n"},
    ),
    "rust": (
        {"Cargo.toml": '[package]\nname = "p"\nversion = "0.1.0"\nedition = "2021"\n',
         "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"},
        {"Cargo.toml": '[package]\nname = "p"\nversion = "0.1.0"\nedition = "2021"\n',
         "src/lib.rs": 'pub fn add(a: i32, b: i32) -> i32 { a + "boom" }\n'},
    ),
    "go": (
        {"go.mod": "module p\n\ngo 1.21\n", "main.go": "package main\n\nfunc main() { _ = 1 }\n"},
        {"go.mod": "module p\n\ngo 1.21\n",
         "main.go": 'package main\n\nfunc main() { var x int = "boom"; _ = x }\n'},
    ),
    "c": (
        {"main.c": "int main(void) { return 0; }\n"},
        {"main.c": "int main(void) { return undeclared_thing(); }\n"},
    ),
}


def _ws(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return d


@pytest.mark.parametrize("lang", sorted(CASES))
def test_the_oracle_accepts_correct_code_and_rejects_broken_code(lang, monkeypatch):
    monkeypatch.setenv("DETERMINEX_ORACLE_APPROVED", "1")
    orc = O.get_oracle(lang)
    if not orc.available():
        pytest.skip(f"{lang} toolchain not installed")
    healthy, why = orc.toolchain_healthy()
    if not healthy:
        pytest.skip(f"{lang} toolchain installed but not working: {why[:120]}")

    good, bad = CASES[lang]
    assert orc.verify(_ws(good), approved=True).passed is True, (
        f"{lang}: correct code was rejected -- the oracle is accusing, not verifying"
    )
    assert orc.verify(_ws(bad), approved=True).passed is False, (
        f"{lang}: BROKEN code was accepted -- this is a silent pass, the one thing an "
        f"oracle must never do"
    )


def test_a_broken_toolchain_is_reported_as_unavailable_not_as_a_code_failure(monkeypatch):
    """THE SWIFT BUG, generalised. A toolchain that cannot compile hello world produces no
    evidence about anyone's code, so its verdict must not be dressed up as one."""
    monkeypatch.setenv("DETERMINEX_ORACLE_APPROVED", "1")
    orc = O.get_oracle("python")
    monkeypatch.setitem(O._TOOLCHAIN_HEALTH, "python", (False, "simulated broken toolchain"))
    ws = _ws({"solution.py": "def add(a, b):\n    return a + b\n",
              "test_add.py": "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 6\n"})
    with pytest.raises(O.OracleUnavailable) as ei:
        orc.verify(ws, approved=True)
    assert "not working" in str(ei.value)
    assert "not evidence about this code" in str(ei.value)


def test_a_healthy_toolchain_still_blames_genuinely_broken_code(monkeypatch):
    """NEGATIVE CONTROL for the fix above. If the toolchain-health check were consulted too
    eagerly -- or defaulted to 'broken' -- every real failure would be excused as an
    environment problem, and the oracle would stop being an oracle."""
    monkeypatch.setenv("DETERMINEX_ORACLE_APPROVED", "1")
    orc = O.get_oracle("python")
    O._TOOLCHAIN_HEALTH.pop("python", None)
    ws = _ws({"solution.py": "def add(a, b):\n    return a + b\n",
              "test_add.py": "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 6\n"})
    res = orc.verify(ws, approved=True)
    assert res.passed is False, "a real assertion failure must survive the health check"
    assert res.failures, "and must still carry the failing test"


def test_an_oracle_without_a_smoke_test_says_so_rather_than_claiming_health():
    """An absent measurement must never become a fabricated one -- the same rule the cost
    estimator follows for oracles it cannot price."""
    orc = O.get_oracle("cobol")
    O._TOOLCHAIN_HEALTH.pop(orc.name, None)
    if orc.name in O._TOOLCHAIN_SMOKE:
        pytest.skip("cobol now has a smoke test; pick another unprobed oracle")
    healthy, detail = orc.toolchain_healthy()
    assert healthy is True
    assert "no smoke test defined" in detail
