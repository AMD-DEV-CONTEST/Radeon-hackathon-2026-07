"""
sv_parser.py — Robust SystemVerilog extractor from raw LLM output.

Handles all common LLM output shapes without requiring an exact fence tag:
  - ```verilog ... ```        (conventional for code-tuned models)
  - ```systemverilog ... ```  (also accepted)
  - ```sv ... ```
  - ``` ... ```               (bare fence, no language tag)
  - Raw module...endmodule    (no fence at all — last resort)
  - Two fenced blocks: scans all blocks and returns the one containing 'module'
    — handles the case where a model "thinks out loud" with a draft before the
    real answer.

On extraction failure, write the raw response to a debug dump file in the
workspace so any NOT_RUN case is immediately debuggable from disk.
"""

import re
from pathlib import Path
from typing import Optional


# ─── Regex patterns ────────────────────────────────────────────────────────────
# Matches ```verilog, ```systemverilog, ```sv, or ``` (generic fence).
# Uses non-greedy match so two blocks in one response are handled correctly.
_FENCE_PATTERN = re.compile(
    r"```(?:systemverilog|verilog|sv)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

# Fallback: match a module...endmodule block directly in the text.
_MODULE_PATTERN = re.compile(
    r"(`(?:timescale|default_nettype)[^\n]*\n)*"  # optional directives before module
    r"\s*module\b.*?endmodule"                     # module body
    r"(?:\s*`default_nettype\s+\w+)?",             # optional trailing directive
    re.DOTALL | re.IGNORECASE,
)

# Sanity check: extracted block must contain the 'module' keyword.
_SV_SANITY = re.compile(r"\bmodule\b", re.IGNORECASE)


def strip_comments(code: str) -> str:
    """Strip single-line (//...) and multi-line (/*...*/) comments from SV code."""
    code_no_block = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    return re.sub(r'//[^\n]*', '', code_no_block)


def extract_module_name(code: str) -> Optional[str]:
    """
    Extract the top-level module name from SystemVerilog code.
    Anchored to ensure the identifier is followed by '(', ';', or '#'.
    Ignores occurrences inside comments.
    """
    if not code:
        return None
    clean_code = strip_comments(code)
    # Prefer tb_ prefixed module if present in testbench context
    tb_match = re.search(r'\bmodule\s+(tb_\w+)\s*[(;#]', clean_code)
    if tb_match:
        return tb_match.group(1)
    generic_match = re.search(r'\bmodule\s+(\w+)\s*[(;#]', clean_code)
    if generic_match:
        return generic_match.group(1)
    return None



def extract_systemverilog(
    raw_text: str,
    dump_on_failure: bool = False,
    dump_path: Optional[Path] = None,
    label: str = "extraction_failure",
) -> Optional[str]:
    """
    Extract SystemVerilog source from raw LLM output.

    Tries strategies in order of preference:
    1. Fenced code block with a recognized language tag (verilog/systemverilog/sv)
    2. Generic fenced code block (```) if it contains 'module'
    3. Bare module...endmodule block in the text

    When multiple fenced blocks are present, returns the last block containing
    'module' — models commonly emit a draft/scratch block first and the real
    corrected module last.

    Parameters
    ----------
    raw_text        : str          — raw LLM completion text
    dump_on_failure : bool         — if True, write raw_text to dump_path on failure
    dump_path       : Path | None  — where to write the dump file
    label           : str          — filename label for the dump file

    Returns
    -------
    str   — cleaned SV code, or None if nothing could be extracted.
    """
    if not raw_text:
        if dump_on_failure and dump_path:
            _dump_failure(raw_text or "", dump_path, label)
        return None

    # Strategy 1 & 2: fenced blocks — collect all, pick the last valid one.
    # "Last valid" handles the pattern where a model emits a draft block first
    # and the corrected final module last.
    matches = _FENCE_PATTERN.findall(raw_text)
    best: Optional[str] = None
    for candidate in matches:
        cleaned = candidate.strip()
        if cleaned and _SV_SANITY.search(cleaned):
            best = cleaned          # keep scanning — last valid wins

    if best is not None:
        return _normalize(best)

    # Strategy 3: bare module block
    m = _MODULE_PATTERN.search(raw_text)
    if m:
        cleaned = m.group(0).strip()
        if _SV_SANITY.search(cleaned):
            return _normalize(cleaned)

    # All strategies failed
    if dump_on_failure and dump_path:
        _dump_failure(raw_text, dump_path, label)
    return None


def _dump_failure(raw_text: str, workspace: Path, label: str) -> None:
    """Write the raw LLM response to a debug file so NOT_RUN cases are debuggable.
    Prefix is 'extraction_failure_' for easy grep/find in the workspace directory.
    """
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        dump_file = workspace / f"extraction_failure_{label}.txt"
        dump_file.write_text(raw_text, encoding="utf-8", errors="replace")
    except Exception:
        pass   # never crash the agent due to a debug dump


def _normalize(code: str) -> str:
    """
    Normalize extracted code:
    - Strip Windows-style line endings
    - Ensure `timescale directive is present (add if missing)
    - Ensure `default_nettype none is present (add if missing)
    - Ensure trailing `default_nettype wire
    - Enforce POSIX trailing newline (eliminates Verilator EOFNEWLINE warning)
    """
    code = code.replace("\r\n", "\n").strip()

    has_timescale      = "`timescale" in code
    has_nettype_none   = "`default_nettype none" in code

    header_lines = []
    if not has_timescale:
        header_lines.append("`timescale 1ns/1ps")
    if not has_nettype_none:
        header_lines.append("`default_nettype none")

    if header_lines:
        code = "\n".join(header_lines) + "\n\n" + code

    # Ensure trailing default_nettype wire
    if "`default_nettype wire" not in code:
        code = code + "\n\n`default_nettype wire"

    # POSIX EOF: Verilator emits EOFNEWLINE if file does not end with \n.
    # Enforce unconditionally -- silences the warning deterministically.
    if not code.endswith("\n"):
        code = code + "\n"

    return code


# ─── Inline self-test (run directly: python sv_parser.py) ─────────────────────
if __name__ == "__main__":
    _MINIMAL_MODULE = "module foo(input logic a, output logic b);\n  assign b = a;\nendmodule"

    _cases = [
        # (description, input_text, should_succeed)
        ("verilog fence",
         f"```verilog\n{_MINIMAL_MODULE}\n```", True),

        ("systemverilog fence",
         f"```systemverilog\n{_MINIMAL_MODULE}\n```", True),

        ("sv fence",
         f"```sv\n{_MINIMAL_MODULE}\n```", True),

        ("bare fence (no language tag)",
         f"```\n{_MINIMAL_MODULE}\n```", True),

        ("no fence at all (raw module)",
         _MINIMAL_MODULE, True),

        ("two blocks — second is real module",
         "Here is a draft:\n```verilog\nassign x = 1;\n```\n"
         f"And the final answer:\n```verilog\n{_MINIMAL_MODULE}\n```",
         True),

        ("two blocks — first has module, second also has module (should get last)",
         f"Draft:\n```verilog\nmodule draft();\nendmodule\n```\n"
         f"Final:\n```verilog\n{_MINIMAL_MODULE}\n```",
         True),

        ("empty response",
         "", False),

        ("no code at all",
         "I cannot generate that module.", False),
    ]

    print("sv_parser.py — self-test\n" + "=" * 50)
    all_pass = True
    for desc, text, should_succeed in _cases:
        result = extract_systemverilog(text)
        ok = (result is not None) == should_succeed
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  [{status}] {desc}")
        if not ok:
            print(f"         Expected success={should_succeed}, got result={'<code>' if result else 'None'}")

    # Verify two-block case returns the LAST valid module (not the first)
    two_block_text = (
        f"Draft:\n```verilog\nmodule draft();\nendmodule\n```\n"
        f"Final:\n```verilog\n{_MINIMAL_MODULE}\n```"
    )
    r = extract_systemverilog(two_block_text)
    if r and "foo" in r and "draft" not in r:
        print("  [PASS] two-block: returns last block (foo), not first (draft)")
    else:
        print("  [FAIL] two-block: did not return the correct last block")
        all_pass = False

    print()
    print("Result:", "ALL PASS" if all_pass else "SOME TESTS FAILED")
