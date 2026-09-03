# -*- coding: utf-8 -*-
"""Build a public-safe, reproducible YIJIAN source snapshot with a hash manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path


SCHEMA = "yijian-public-source-snapshot-v1"
MAX_FILE_BYTES = 5 * 1024 * 1024
ROOT_FILES = (
    ".env.example", ".gitignore", ".python-version", "README.md", "requirements.txt",
    "requirements-lock.txt", "THIRD_PARTY_NOTICES.md",
)
TREE_RULES = {
    "backend": {".py", ".mjs", ".sgf"},
    "deploy/cloud": {".py", ".sh", ".md", ".cfg"},
    "scripts": {".py", ".ps1"},
}
PUBLIC_WEB_FILES = {"web/index.html"}
PUBLIC_BACKEND_EXCLUDED_FILES = {
    # This regression suite deliberately reads the owner's private game archive
    # and asserts real player names.  The application code is public, but this
    # fixture-bound test is outside the distributable boundary.
    "backend/tests/test_library_importers_coach.py",
}
PUBLIC_TRAINING_FILES = {
    "training/README.md",
    "training/sources.json",
    "training/agent_multitask_corpus.py",
    "training/assemble_unseen_award_eval.py",
    "training/audit_agent_tokenizer.py",
    "training/award_evaluation.py",
    "training/award_release_gate.py",
    "training/bound_position_outputs.py",
    "training/build_agent_source_cases.py",
    "training/build_ai_assisted_blind_review.py",
    "training/build_ai_blind_prescore.py",
    "training/build_creator_coverage_manifest.py",
    "training/build_creator_split.py",
    "training/build_lora_v2_corpus.py",
    "training/build_lora_v3_corpus.py",
    "training/build_micro_selection.py",
    "training/build_training_stage_profile.py",
    "training/build_unseen_position_eval.py",
    "training/expert_corpus.py",
    "training/freeze_lora_adapter.py",
    "training/generate_sft.py",
    "training/gold_answer_consistency.py",
    "training/gold_review_workflow.py",
    "training/merge_gold_releases.py",
    "training/run_vllm_jsonl.py",
    "training/summarize_inference_ablations.py",
    "training/train_lora_rocm.py",
    "training/trusted_source_chain.py",
    "training/validate_award_runtime.py",
    "training/validate_training_language_gate.py",
    "training/validate_top200_invariants.py",
}
PUBLIC_TRAINING_DATA_FILES = {
    "training/data/classical_sft_train.jsonl",
}
PUBLIC_TRAINING_TESTS = {
    "test_agent_award_contract.py",
    "test_agent_multitask_corpus.py",
    "test_assemble_unseen_award_eval.py",
    "test_audit_agent_tokenizer.py",
    "test_award_evaluation.py",
    "test_award_release_gate.py",
    "test_bound_position_outputs.py",
    "test_build_ai_assisted_blind_review.py",
    "test_build_ai_blind_prescore.py",
    "test_build_lora_v3_corpus.py",
    "test_build_micro_selection.py",
    "test_build_submission_hash_bundle.py",
    "test_build_submission_status.py",
    "test_cloud_vllm_install.py",
    "test_coexist_runtime.py",
    "test_freeze_lora_adapter.py",
    "test_public_submission_snapshot.py",
    "test_run_vllm_jsonl.py",
    "test_train_lora_rocm.py",
    "test_training_stage_profile.py",
    "test_validate_public_submission_snapshot.py",
    "test_verify_local_lora_archive.py",
}
PUBLIC_TRAINING_REMOTE_FILES = {
    "training/remote/download_qwen3_14b.sh",
    "training/remote/probe_vllm_lora_v3.sh",
    "training/remote/restore_27b.sh",
    "training/remote/run_lora_runtime_v3_stage.sh",
    "training/remote/run_smoke_with_restore_27b.sh",
    "training/remote/run_vllm_lora_v3_coexist_matrix.sh",
    "training/remote/serve_lora_transformers.py",
    "training/remote/start_lora14b_v3_fast_preview.sh",
}
EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", "workspace", "licensed", "data",
    "runtime", "logs", "attachments", "checkpoints", "adapter",
}
SENSITIVE_PATTERNS = {
    "windows_user_path": re.compile(r"[A-Za-z]:[\\/]Users[\\/](?!USERNAME(?:[\\/]|$))", re.I),
    "private_key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "literal_api_key": re.compile(r"(?i)(?:api[_-]?key|token|secret)\s*[=:]\s*['\"](?!replace-|your-|\$\{|os\.getenv)[^'\"]{12,}"),
}


class SnapshotError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def eligible(relative: Path) -> bool:
    normalized = relative.as_posix()
    if normalized in PUBLIC_TRAINING_DATA_FILES:
        return True
    if any(part in EXCLUDED_PARTS or part.startswith(".") for part in relative.parts[:-1]):
        return False
    if normalized in ROOT_FILES:
        return True
    if normalized in PUBLIC_BACKEND_EXCLUDED_FILES:
        return False
    if normalized in PUBLIC_WEB_FILES or normalized in PUBLIC_TRAINING_FILES:
        return True
    if len(relative.parts) >= 3 and relative.parts[:2] == ("training", "remote"):
        return normalized in PUBLIC_TRAINING_REMOTE_FILES
    if len(relative.parts) == 3 and relative.parts[:2] == ("training", "tests"):
        return relative.name in PUBLIC_TRAINING_TESTS
    if relative.parts and relative.parts[0] in {"training", "web"}:
        return False
    for root, suffixes in TREE_RULES.items():
        root_path = Path(root)
        try:
            relative.relative_to(root_path)
        except ValueError:
            continue
        return relative.suffix.lower() in suffixes
    return False


def scan_text(path: Path, relative: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [{"kind": "non_utf8", "path": relative.as_posix()}]
    findings = []
    for kind, pattern in SENSITIVE_PATTERNS.items():
        if pattern.search(text):
            findings.append({"kind": kind, "path": relative.as_posix()})
    return findings


def build(source_root: Path, output: Path) -> dict:
    source_root = source_root.resolve()
    output = output.resolve()
    if output.exists():
        raise SnapshotError(f"output already exists: {output}")
    files = []
    findings = []
    with tempfile.TemporaryDirectory(prefix="yijian-public-snapshot-", dir=output.parent) as temporary:
        staging = Path(temporary) / "source"
        for source in sorted(item for item in source_root.rglob("*") if item.is_file()):
            relative = source.relative_to(source_root)
            if not eligible(relative):
                continue
            if source.stat().st_size > MAX_FILE_BYTES:
                raise SnapshotError(f"public source file exceeds 5 MiB: {relative}")
            findings.extend(scan_text(source, relative))
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files.append({
                "path": relative.as_posix(),
                "bytes": source.stat().st_size,
                "sha256": sha256_file(source),
            })
        if findings:
            raise SnapshotError("public snapshot safety scan failed: " + json.dumps(findings, ensure_ascii=False))
        manifest = {
            "schemaVersion": SCHEMA,
            "passed": True,
            "files": len(files),
            "secretFindings": 0,
            "privateDataFindings": 0,
            "items": files,
        }
        (staging / "public-snapshot-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        shutil.move(str(staging), str(output))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source_root, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
