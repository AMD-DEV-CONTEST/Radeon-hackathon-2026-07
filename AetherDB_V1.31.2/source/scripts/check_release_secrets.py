"""Fail closed on real-looking secrets, staged changes, or model binaries."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {
    ".py", ".js", ".mjs", ".vue", ".rs", ".toml", ".json", ".yaml", ".yml",
    ".md", ".txt", ".html", ".css", ".bat", ".ps1", ".example",
}
MODEL_EXTENSIONS = {".onnx", ".bin", ".safetensors", ".gguf", ".pt", ".pth"}
SENSITIVE_NAMES = {".api_keys.json", ".env", "api_keys.json", "config.local.yaml", "config.yaml"}
PATTERNS = tuple(
    re.compile(value, re.IGNORECASE)
    for value in (
        r"sk-[A-Za-z0-9_-]{20,}",
        r"nvk_(?:admin_)?[a-f0-9]{32}",
        r"ghp_[A-Za-z0-9]{30,}",
        r"AIza[0-9A-Za-z_-]{30,}",
        r"xox[baprs]-[A-Za-z0-9-]{20,}",
        r"Bearer\s+[A-Za-z0-9._-]{24,}",
    )
)


def git_paths() -> list[Path]:
    output = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={ROOT}",
            "-c",
            "core.quotepath=false",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=ROOT,
    )
    return [ROOT / value.decode("utf-8") for value in output.split(b"\0") if value]


def scan(paths):
    hits = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(pattern.search(text) for pattern in PATTERNS):
            hits.append(path)
    return hits


def main() -> int:
    candidates = git_paths()
    evidence = list((ROOT / "local_agent_runs").rglob("*")) if (ROOT / "local_agent_runs").exists() else []
    secret_hits = scan(candidates)
    evidence_hits = scan(evidence)
    model_files = [path for path in candidates if path.suffix.lower() in MODEL_EXTENSIONS]
    sensitive_candidates = sorted(
        path.relative_to(ROOT).as_posix()
        for path in candidates
        if path.name in SENSITIVE_NAMES
    )
    staged = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={ROOT}",
            "diff",
            "--cached",
            "--name-only",
            "-z",
        ],
        cwd=ROOT,
    )
    staged_count = len([item for item in staged.split(b"\0") if item])

    print(f"candidate_files={len(candidates)}")
    print(f"candidate_secret_files={len(secret_hits)}")
    print(f"local_evidence_secret_files={len(evidence_hits)}")
    print(f"candidate_model_binaries={len(model_files)}")
    print(f"staged_files={staged_count}")
    print("sensitive_candidates=" + (",".join(sensitive_candidates) or "none"))
    for path in secret_hits + evidence_hits + model_files:
        print("BLOCKED_FILE=" + path.relative_to(ROOT).as_posix())
    if sensitive_candidates == ["config.yaml"]:
        print("KNOWN_RISK=config.yaml is historically tracked and must be removed from any future commit")
    return 1 if secret_hits or evidence_hits or model_files or staged else 0


if __name__ == "__main__":
    raise SystemExit(main())
