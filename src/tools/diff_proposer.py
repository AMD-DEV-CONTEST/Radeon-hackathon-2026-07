"""
Unified diff generation tool for proposing code optimization changes.

The agent PROPOSES diffs as text output. It NEVER writes directly to the user's
source files. Saving a diff to disk requires explicit user approval routed
through the PermissionGate.
"""

import difflib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DiffProposal:
    """A proposed optimization expressed as a unified diff."""

    original_path: str
    original_code: str
    patched_code: str
    diff_text: str
    description: str
    pattern_type: str
    lines_added: int
    lines_removed: int

    def summary(self) -> str:
        return (
            f"Proposed diff for {Path(self.original_path).name} "
            f"(+{self.lines_added}/-{self.lines_removed} lines): {self.description}"
        )


def propose_diff(
    original_path: str,
    patched_code: str,
    description: str = "",
    pattern_type: str = "unknown",
) -> DiffProposal:
    """
    Generate a unified diff between the original file and the patched code.

    Args:
        original_path: Path to the existing source file.
        patched_code: The full new content of the file after applying the optimization.
        description: Human-readable description of what the optimization does.
        pattern_type: Optimization pattern category (e.g. "block_size_tuning", "lds_bank_conflict").

    Returns:
        DiffProposal containing the unified diff text and metadata.
        NOTHING IS WRITTEN TO DISK.
    """
    original_path = str(original_path)
    original_code = _read_original(original_path)

    original_lines = original_code.splitlines(keepends=True)
    patched_lines = patched_code.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            patched_lines,
            fromfile=f"a/{Path(original_path).name}",
            tofile=f"b/{Path(original_path).name}",
            lineterm="",
        )
    )

    diff_text = "\n".join(diff_lines)
    lines_added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    lines_removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    return DiffProposal(
        original_path=original_path,
        original_code=original_code,
        patched_code=patched_code,
        diff_text=diff_text,
        description=description,
        pattern_type=pattern_type,
        lines_added=lines_added,
        lines_removed=lines_removed,
    )


def propose_diff_from_strings(
    original_code: str,
    patched_code: str,
    filename: str = "workload.py",
    description: str = "",
    pattern_type: str = "unknown",
) -> DiffProposal:
    """
    Generate a diff directly from two code strings (no file read needed).
    Useful when the agent proposes a patch for inline code snippets.
    """
    original_lines = original_code.splitlines(keepends=True)
    patched_lines = patched_code.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            patched_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm="",
        )
    )

    diff_text = "\n".join(diff_lines)
    lines_added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    lines_removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    return DiffProposal(
        original_path=filename,
        original_code=original_code,
        patched_code=patched_code,
        diff_text=diff_text,
        description=description,
        pattern_type=pattern_type,
        lines_added=lines_added,
        lines_removed=lines_removed,
    )


def save_proposed_diff(
    proposal: DiffProposal,
    output_path: str,
) -> str:
    """
    Save a proposed diff to a .patch file at the specified output path.

    IMPORTANT: This function should only be called AFTER the user has explicitly
    approved the action via the PermissionGate. The orchestrator is responsible
    for enforcing this.

    Args:
        proposal: The DiffProposal to save.
        output_path: File path to save the .patch file (user-chosen location).

    Returns:
        The absolute path of the saved patch file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        f"# OmniKernel-ROCm Proposed Optimization\n"
        f"# Pattern: {proposal.pattern_type}\n"
        f"# Description: {proposal.description}\n"
        f"# Original: {proposal.original_path}\n"
        f"# Changes: +{proposal.lines_added}/-{proposal.lines_removed} lines\n"
        f"#\n"
        f"# To apply: git apply <this_file>  OR  patch -p1 < <this_file>\n"
        f"# Review carefully before applying.\n\n"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + proposal.diff_text + "\n")

    return str(output_path.resolve())


def _read_original(path: str) -> str:
    """Read original source file, returning empty string if it doesn't exist."""
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def format_diff_for_display(proposal: DiffProposal, max_lines: int = 60) -> str:
    """
    Return a formatted, truncated view of the diff for terminal display.
    """
    lines = proposal.diff_text.split("\n")
    if len(lines) > max_lines:
        shown = lines[:max_lines]
        truncated = len(lines) - max_lines
        shown.append(f"... ({truncated} more lines — save to file to see full diff)")
    else:
        shown = lines

    display = "\n".join(shown)
    header = (
        f"{'='*60}\n"
        f"PROPOSED DIFF: {proposal.description}\n"
        f"Pattern: {proposal.pattern_type} | "
        f"+{proposal.lines_added}/-{proposal.lines_removed} lines\n"
        f"{'='*60}\n"
    )
    return header + display
