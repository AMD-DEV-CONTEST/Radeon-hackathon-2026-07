from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from privateops.submission_evidence import build_submission_evidence


REQUIRED = [
    "README.md", "LICENSE", "requirements.txt", "privateops/agent.py", "privateops/server.py",
    "web/index.html", "web/app.js", "tests/test_agent.py",
    "submission/README.md", "submission/PrivateOps-Agent-Project-Specification.pdf",
    "submission/PrivateOps-Agent-Poster.pdf", "submission/PrivateOps-Agent-Competition-Deck.pptx",
    "submission/project-specification.html",
    "submission/poster.html", "submission/assets/architecture.svg", "submission/assets/architecture.png",
    "submission/assets/ui-development.png",
    "submission/demo-script.md", "submission/video-shot-list.md", "submission/radeon-cloud-runbook.md",
    "submission/benchmark-evidence.json", "submission/benchmark-evidence.csv",
    "submission/performance-and-stability-report.md", "submission/example-prompts.md",
    "submission/pr-submission.md", "submission/final-checklist.md", "submission/final-verification-report.md",
]
FORBIDDEN = re.compile(r"\b(TODO|TBD|FIXME|CHANGEME)\b|<ADD\b[^>]*>|sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}", re.IGNORECASE)
TEXT_SUFFIXES = {".md", ".html", ".json", ".csv", ".svg", ".py", ".js", ".css", ".txt", ".example", ".sh"}
SEMANTIC_REQUIREMENTS = {
    "README.md": [
        "LangChain",
        "Qwen/Qwen2.5-7B-Instruct",
        "ROCm",
        "Remote model / Local ROCm",
        "Broad visibility. Deliberate action. Evidence for every decision.",
    ],
    "submission/pr-submission.md": ["LangChain", "Qwen/Qwen2.5-7B-Instruct", "vLLM"],
    "submission/project-specification.html": [
        "LangChain Core",
        "Qwen/Qwen2.5-7B-Instruct",
        "1,511.072",
        "32.427",
        "Remote model",
        "Local ROCm",
        "Broad visibility. Deliberate action. Evidence for every decision.",
    ],
    "submission/radeon-cloud-runbook.md": ["same-instance loopback", "Local ROCm"],
}
STALE_COMPETITION_COPY = [
    "awaiting_account_owner_radeon_cloud_capture",
    "READY FOR REAL CLOUD EVIDENCE",
    "The repository-generated package contains no AMD performance number",
]


def validate(root: Path = ROOT) -> list[str]:
    problems = []
    for relative in REQUIRED:
        path = root / relative
        if not path.exists() or (path.is_file() and path.stat().st_size == 0):
            problems.append(f"missing or empty: {relative}")
    for path in list((root / "submission").rglob("*")) + [root / "README.md", root / ".env.example"]:
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative_path = path.relative_to(root).as_posix()
        if match := FORBIDDEN.search(text):
            problems.append(f"forbidden marker or credential pattern in {relative_path}: {match.group(0)}")
        for phrase in STALE_COMPETITION_COPY:
            if phrase in text:
                problems.append(f"stale competition copy in {relative_path}: {phrase}")
    evidence_path = root / "submission/benchmark-evidence.json"
    if evidence_path.exists():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence.get("status") == "awaiting_account_owner_radeon_cloud_capture" or not evidence.get("runs"):
            problems.append("benchmark evidence is still a pre-capture placeholder")
        source_path = root / "submission/evidence/rocm-verified/radeon-benchmark-run.json"
        latency_path = root / "submission/evidence/rocm-verified/rocm-agent-live-latency-zh.txt"
        if source_path.exists() and latency_path.exists():
            try:
                expected = build_submission_evidence(root)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                problems.append(f"invalid immutable Radeon evidence: {exc}")
            else:
                if evidence != expected:
                    problems.append("benchmark evidence drifted from immutable Radeon source")
    for relative, phrases in SEMANTIC_REQUIREMENTS.items():
        path = root / relative
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for phrase in phrases:
            if phrase not in content:
                problems.append(f"missing required competition detail in {relative}: {phrase}")
    return problems


def main() -> None:
    problems = validate()
    if problems:
        print("Submission validation failed:")
        for problem in problems:
            print(f"- {problem}")
        raise SystemExit(1)
    print(f"Submission validation passed: {len(REQUIRED)} required artifacts present; no unresolved markers or credential patterns detected.")


if __name__ == "__main__":
    main()
