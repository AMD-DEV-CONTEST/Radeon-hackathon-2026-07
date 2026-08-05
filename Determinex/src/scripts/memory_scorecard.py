#!/usr/bin/env python3
"""Score Determinex project memory for freshness, retrieval shape, and safety."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token)\s*=\s*['\"][^'\"]{8,}['\"]"),
)
# Escapes, not literals. These ARE mojibake sequences -- that is the whole point -- so
# writing them literally made this detector trip the repository's own mojibake/CRLF
# guard: "scripts/memory_scorecard.py: U+FFFD replacement char (decode corruption)",
# failing pre-commit and CI on the one file whose job is to catch exactly this. The
# escaped form produces byte-identical strings at runtime and leaves no non-ASCII
# bytes in the source for the guard to find.
MOJIBAKE_PATTERNS = (
    "\u00e2",
    "\u00c3",
    "\ufffd",
    "\u00c2\u00b7",
    "\u00e2\u2020",
    "\u00e2\u20ac\u201d",
)


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


class MemoryScorecard:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self.results: list[CheckResult] = []

    def run(self) -> list[CheckResult]:
        self.results = []
        self._check_layer_files()
        self._check_companion_docs()
        self._check_stale_boundary_test()
        self._check_secret_exposure()
        self._check_mojibake()
        self._check_operational_tools()
        return self.results

    def _add(self, name: str, ok: bool, detail: str) -> None:
        self.results.append(CheckResult(name, "pass" if ok else "fail", detail))

    def _warn(self, name: str, detail: str) -> None:
        self.results.append(CheckResult(name, "warn", detail))

    def _read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8", errors="replace")

    def _check_layer_files(self) -> None:
        required = ("PROJECT.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md")
        missing = [path for path in required if not (self.root / path).exists()]
        self._add("layer_files_present", not missing, f"missing={missing}")
        if missing:
            return

        project = self._read("PROJECT.md")
        delegates = all(
            "PROJECT.md" in self._read(path) for path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
        )
        self._add("tool_overlays_delegate", delegates, "tool overlays reference PROJECT.md")
        self._add(
            "project_avoids_volatile_counts",
            "Do not copy volatile campaign counts" in project,
            "PROJECT.md carries stable rules, not live counts",
        )

    def _check_companion_docs(self) -> None:
        companion_dir = self.root / "docs" / "companions"
        docs = sorted(companion_dir.glob("COMPANION_*.md"))
        self._add("companion_docs_present", bool(docs), f"count={len(docs)}")
        for doc in docs:
            text = doc.read_text(encoding="utf-8", errors="replace")
            frontmatter_ok = text.startswith("---\n") and "\n---\n" in text[:1200]
            retrieval_ok = (
                "description:" in text and "depends:" in text and text.count("\n## ") >= 2
            )
            self._add(f"{doc.name}:frontmatter", frontmatter_ok, "has YAML frontmatter")
            self._add(
                f"{doc.name}:retrieval_shape",
                retrieval_ok,
                "has description, depends, and h2 chunks",
            )

    def _check_stale_boundary_test(self) -> None:
        path = (
            self.root
            / "frontend"
            / "src-tauri"
            / "tests"
            / "companion_rag_tauri_command_boundary.rs"
        )
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        stale = "OmniscienceHarvester.tsx" in text
        self._add(
            "boundary_test_tracks_live_ui", not stale, "removed stale OmniscienceHarvester target"
        )

    def _check_secret_exposure(self) -> None:
        scanned = self._memory_text_files()
        hits: list[str] = []
        for path in scanned:
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                hits.append(str(path.relative_to(self.root)))
        self._add("secret_patterns_absent", not hits, f"hits={hits[:10]}")

    def _check_mojibake(self) -> None:
        shared = self._shared_memory_text_files()
        shared_hits: list[str] = []
        for path in shared:
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(marker in text for marker in MOJIBAKE_PATTERNS):
                shared_hits.append(str(path.relative_to(self.root)))
        self._add(
            "mojibake_absent_from_shared_memory_docs",
            not shared_hits,
            f"hits={shared_hits[:20]}",
        )

        overlay_hits: list[str] = []
        for rel in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            path = self.root / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(marker in text for marker in MOJIBAKE_PATTERNS):
                overlay_hits.append(rel)
        if overlay_hits:
            self._warn("mojibake_present_in_legacy_tool_overlays", f"hits={overlay_hits}")

    def _check_operational_tools(self) -> None:
        scorecard = self.root / "scripts" / "memory_scorecard.py"
        inbox = self.root / "scripts" / "memory_learning_inbox.py"
        self._add(
            "memory_scorecard_present", scorecard.exists(), str(scorecard.relative_to(self.root))
        )
        self._add(
            "memory_learning_inbox_present", inbox.exists(), str(inbox.relative_to(self.root))
        )

    def _memory_text_files(self) -> list[Path]:
        paths: list[Path] = []
        for rel in ("PROJECT.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "ORIENTATION.md"):
            path = self.root / rel
            if path.exists():
                paths.append(path)
        companion_dir = self.root / "docs" / "companions"
        if companion_dir.exists():
            paths.extend(sorted(companion_dir.glob("COMPANION_*.md")))
        return paths

    def _shared_memory_text_files(self) -> list[Path]:
        paths: list[Path] = []
        for rel in ("PROJECT.md", "ORIENTATION.md"):
            path = self.root / rel
            if path.exists():
                paths.append(path)
        companion_dir = self.root / "docs" / "companions"
        if companion_dir.exists():
            paths.extend(sorted(companion_dir.glob("COMPANION_*.md")))
        return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Determinex memory docs and gates")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    results = MemoryScorecard().run()
    failed = [result for result in results if result.status == "fail"]
    payload = {
        "status": "pass" if not failed else "fail",
        "total": len(results),
        "failed": len(failed),
        "results": [asdict(result) for result in results],
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"memory_scorecard: {payload['status']} ({payload['total'] - payload['failed']}/{payload['total']})"
        )
        for result in results:
            marker = {"pass": "OK", "warn": "WARN"}.get(result.status, "FAIL")
            print(f"{marker} {result.name}: {result.detail}")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
