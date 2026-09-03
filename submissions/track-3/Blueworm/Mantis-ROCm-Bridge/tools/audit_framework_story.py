#!/usr/bin/env python3
"""Audit framework-first narrative invariants without modifying project state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.port_profile import load_port_profile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "configs/framework-story-v3.json"
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_EXPECTED_ASSET_POLICY = {
    "mantis_strategy": "SAFE_FALLBACK_EXTERNALIZED",
    "redistribute_mantis_assets": False,
    "raw_asset_payloads_excluded": True,
    "rendered_mantis_demo_visuals_user_permitted": True,
    "permission_is_general_license": False,
    "send_authorization_request_in_this_work_package": False,
}
_EXPECTED_VISUAL_POLICY_INVARIANTS = {
    "files": {
        "README.md": [
            "Rendered Mantis visuals",
            "user-permitted only in the demonstration video",
            "not a general license or redistribution right",
            "Raw Mantis URDF",
        ],
        "configs/submission-identity-v1.json": [
            "rendered_mantis_demo_visuals_user_permitted",
            "raw_asset_payloads_excluded",
            "permission_is_general_license",
        ],
        "docs/FRAMEWORK_STORY_V1.md": [
            "Rendered Mantis visuals",
            "user-permitted only in the demonstration video",
            "not a general license or redistribution right",
            "Raw Mantis URDF",
        ],
        "docs/MANTIS_ASSET_AUTHORIZATION_REQUEST.md": [
            "rendered Mantis visuals",
            "user-permitted only in",
            "not an asset-owner grant",
            "Raw Mantis URDF",
        ],
        "docs/REPRODUCIBILITY.md": [
            "Rendered Mantis visuals",
            "user-permitted only in the demonstration video",
            "not a general license or redistribution right",
            "Raw Mantis URDF",
        ],
        "docs/URDF_ACT_COMPILER_MVP_V1.md": [
            "Rendered Mantis visuals",
            "user-permitted only in the demonstration video",
            "not a general license or redistribution right",
            "Raw Mantis URDF",
        ],
        "third_party/ASSET_LICENSES.md": [
            "rendered Mantis visuals",
            "user-permitted only in the demonstration video",
            "not an asset-owner grant",
            "Raw Mantis URDF",
        ],
        "submission/README.md": [
            "rendered Mantis visual media",
            "demonstration video",
            "does not establish general redistribution rights",
            "Mantis URDF",
        ],
        "submission/README.zh-CN.md": [
            "演示视频",
            "渲染",
            "不构成一般再分发权",
            "URDF",
        ],
        "submission/TECHNICAL_REPORT.md": [
            "rendered Mantis visual media",
            "demonstration video",
            "no general redistribution right",
            "Raw URDF",
        ],
        "submission/EVIDENCE_MATRIX.md": [
            "rendered demo visuals are user-permitted",
            "not a general license",
            "raw URDF",
        ],
        "submission/PUBLICATION_CHECKLIST.md": [
            "permits rendered Mantis visual",
            "demonstration video",
            "not a general redistribution right",
            "no URDF",
        ],
        "submission/VIDEO_STORYBOARD.md": [
            "permits rendered Mantis visual media",
            "demonstration video",
            "does not establish general redistribution rights",
            "Raw Mantis URDF",
        ],
    },
    "forbidden_phrases": [
        "Reports and video must not reproduce unlicensed Mantis screenshots",
        "video uses diagrams, terminal evidence, and neutral stand-ins only",
        "use_unlicensed_mantis_screenshots_or_video_in_submission_video",
        "use_unlicensed_mantis_visuals",
        "Mantis assets and visuals remain externalized",
        "completed clean-room reproduction or rendered video",
    ],
}
_FORBIDDEN_VISUAL_POLICY_PATTERNS = (
    (
        "broad_raw_asset_redistribution",
        re.compile(
            r"\braw\s+mantis\s+(?:urdf|meshes?|source\s+assets?|"
            r"asset\s+payloads?|assets?)\s+(?:may|can|are\s+(?:permitted|"
            r"allowed|authorized)\s+to)\s+(?:be\s+)?(?:redistribut\w*|"
            r"publish\w*|bundl\w*|includ\w*|ship\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "general_license_implication",
        re.compile(
            r"\b(?:demonstration[- ]video|rendered[- ]demo|demo[- ]video)\s+"
            r"permission\s+(?:is|constitutes|grants|provides)\s+(?:a\s+)?"
            r"general\s+(?:asset\s+)?license\b",
            re.IGNORECASE,
        ),
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    detail: str,
) -> None:
    checks.append({"id": check_id, "pass": passed, "detail": detail})


def _required_files(contract: Mapping[str, Any]) -> list[str]:
    invariants = contract["narrative_invariants"]
    paths = {"docs/FRAMEWORK_STORY_V1.md"}
    for value in invariants.values():
        if isinstance(value, list):
            paths.update(value)
    paths.update(contract["visual_policy_invariants"]["files"])
    return sorted(paths)


def _validate_visual_policy_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("asset_policy") != _EXPECTED_ASSET_POLICY:
        raise ContractError("framework story asset_policy changed")
    if contract.get("visual_policy_invariants") != _EXPECTED_VISUAL_POLICY_INVARIANTS:
        raise ContractError("framework story visual_policy_invariants changed")


def _read_story_files(
    root: Path,
    paths: Iterable[str],
    checks: list[dict[str, Any]],
) -> dict[str, str]:
    texts: dict[str, str] = {}
    for relative in paths:
        path = root / relative
        exists = path.is_file()
        _record(
            checks,
            f"file:{relative}",
            exists,
            "present" if exists else "missing",
        )
        if exists:
            texts[relative] = path.read_text(encoding="utf-8")
    return texts


def _check_tokens(
    texts: Mapping[str, str],
    paths: Iterable[str],
    tokens: Iterable[str],
    check_prefix: str,
    checks: list[dict[str, Any]],
) -> None:
    expected = tuple(tokens)
    for relative in paths:
        text = texts.get(relative, "")
        lowered = text.lower()
        missing = [token for token in expected if token.lower() not in lowered]
        _record(
            checks,
            f"{check_prefix}:{relative}",
            not missing,
            "all required tokens present"
            if not missing
            else f"missing tokens: {missing}",
        )


def _check_reproducibility_baseline(
    texts: Mapping[str, str],
    contract: Mapping[str, Any],
    checks: list[dict[str, Any]],
) -> None:
    invariant = contract["reproducibility_invariants"]
    relative = invariant["path"]
    text = texts.get(relative, "")
    missing = [
        token for token in invariant["required_tokens"] if token not in text
    ]
    forbidden = []
    for forbidden_path in invariant["forbidden_paths"]:
        candidate = texts.get(forbidden_path, "")
        forbidden.extend(
            f"{forbidden_path}:{token}"
            for token in invariant["forbidden_tokens"]
            if token in candidate
        )
    _record(
        checks,
        "reproducibility_baseline",
        not missing and not forbidden,
        f"missing={missing}, forbidden={forbidden}",
    )


def _check_visual_policy(
    texts: Mapping[str, str],
    contract: Mapping[str, Any],
    checks: list[dict[str, Any]],
) -> None:
    policy = _EXPECTED_VISUAL_POLICY_INVARIANTS
    files = policy["files"]
    for relative, required_tokens in files.items():
        text = texts.get(relative, "")
        normalized = " ".join(text.lower().split())
        missing = [
            token
            for token in required_tokens
            if " ".join(token.lower().split()) not in normalized
        ]
        _record(
            checks,
            f"visual_policy:{relative}",
            not missing,
            "all required policy tokens present"
            if not missing
            else f"missing tokens: {missing}",
        )

    policy_text = " ".join(
        "\n".join(texts.get(path, "") for path in files).lower().split()
    )
    stale = [
        phrase
        for phrase in policy["forbidden_phrases"]
        if " ".join(phrase.lower().split()) in policy_text
    ]
    _record(
        checks,
        "visual_policy_forbidden",
        not stale,
        f"matches={stale}",
    )

    contradictions: list[str] = []
    for relative in files:
        normalized = " ".join(texts.get(relative, "").split())
        for pattern_id, pattern in _FORBIDDEN_VISUAL_POLICY_PATTERNS:
            if pattern.search(normalized):
                contradictions.append(f"{relative}:{pattern_id}")
    _record(
        checks,
        "visual_policy_contradictions",
        not contradictions,
        f"matches={contradictions}",
    )


def _check_local_links(
    root: Path,
    texts: Mapping[str, str],
    checks: list[dict[str, Any]],
) -> None:
    broken: list[str] = []
    checked = 0
    for relative, text in texts.items():
        source = root / relative
        for match in _MARKDOWN_LINK_RE.finditer(text):
            raw_target = match.group(1).strip().strip("<>")
            target_without_anchor = raw_target.split("#", 1)[0]
            if (
                not target_without_anchor
                or "://" in target_without_anchor
                or target_without_anchor.startswith(("mailto:", "#"))
            ):
                continue
            checked += 1
            target = (source.parent / target_without_anchor).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                broken.append(f"{relative}->{raw_target} (outside root)")
                continue
            if not target.exists():
                broken.append(f"{relative}->{raw_target}")
    _record(
        checks,
        "markdown_local_links",
        not broken,
        f"checked={checked}, broken={broken}",
    )


def _check_entry_receipt(
    root: Path,
    contract: Mapping[str, Any],
    checks: list[dict[str, Any]],
) -> None:
    for index, criterion in enumerate(contract["entry_criteria"]):
        path = root / criterion["path"]
        exists = path.is_file()
        passed = exists
        detail = "present" if exists else "missing"
        if exists and "required_terminal" in criterion:
            payload = load_json(path)
            actual = payload.get("terminal")
            expected = criterion["required_terminal"]
            passed = actual == expected
            detail = f"terminal={actual!r}, expected={expected!r}"
        elif exists and criterion.get("required_hash_verification"):
            failures: list[str] = []
            skipped = set(criterion.get("allowed_post_entry_changes", []))
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                digest, relative = line.split(maxsplit=1)
                relative = relative.strip()
                if relative in skipped:
                    continue
                target = root / relative
                if not target.is_file() or _sha256(target) != digest:
                    failures.append(relative)
            passed = not failures
            detail = (
                f"manifest_failures={failures}, "
                f"allowed_post_entry_changes={sorted(skipped)}"
            )
        _record(checks, f"entry_criterion:{index}", passed, detail)


def _check_runtime_immutability(
    root: Path,
    checks: list[dict[str, Any]],
) -> None:
    contract = load_json(root / "configs/framework-mvp-v2.json")
    failures = [
        relative
        for relative, expected in contract["runtime_immutability"].items()
        if not (root / relative).is_file()
        or _sha256(root / relative) != expected
    ]
    _record(
        checks,
        "runtime_immutability",
        not failures,
        f"checked={len(contract['runtime_immutability'])}, failures={failures}",
    )


def audit_framework_story(
    root: str | Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    if contract.get("schema_version") != 1:
        raise ContractError("framework story schema_version must be 1")
    if contract.get("work_package_id") != "WP-FRAMEWORK-STORY-003":
        raise ContractError("framework story work_package_id changed")
    _validate_visual_policy_contract(contract)

    checks: list[dict[str, Any]] = []
    paths = _required_files(contract)
    texts = _read_story_files(project_root, paths, checks)
    invariants = contract["narrative_invariants"]

    _check_tokens(
        texts,
        invariants["framework_first_files"],
        ("framework", "Mantis", "reference"),
        "framework_first",
        checks,
    )
    _check_tokens(
        texts,
        invariants["reference_case_files"],
        ("stack_bowls_three", "Mantis"),
        "reference_case",
        checks,
    )
    _check_tokens(
        texts,
        invariants["official_g3_files"],
        ("0/10", "timeout", "collision_safety"),
        "official_g3",
        checks,
    )
    _check_tokens(
        texts,
        invariants["corrective_terminal_files"],
        ("COMPLETE_NOT_PROMOTABLE",),
        "corrective_terminal",
        checks,
    )
    _check_tokens(
        texts,
        invariants["identity_files"],
        ("Zhiwen Su", "Blueworm", "Mantis-ROCm Bridge", "Apache-2.0"),
        "identity",
        checks,
    )
    _check_tokens(
        texts,
        invariants["asset_boundary_files"],
        ("externalized",),
        "asset_boundary",
        checks,
    )
    _check_visual_policy(texts, contract, checks)
    _check_reproducibility_baseline(texts, contract, checks)

    all_text = "\n".join(texts.values()).lower()
    stale = [
        phrase
        for phrase in contract["stale_claims_forbidden"]
        if phrase.lower() in all_text
    ]
    _record(checks, "stale_claims", not stale, f"matches={stale}")
    _check_local_links(project_root, texts, checks)
    _check_entry_receipt(project_root, contract, checks)
    _check_runtime_immutability(project_root, checks)

    profile_paths = (
        "configs/robot-port-profile-template-v1.json",
        "configs/robot-port-profile-mantis-stack-bowls-v1.json",
        "tests/fixtures/robot-port-profile-synthetic-v1.json",
    )
    profile_failures: list[str] = []
    for relative in profile_paths:
        try:
            load_port_profile(project_root / relative)
        except ContractError:
            profile_failures.append(relative)
    _record(
        checks,
        "profile_validation",
        not profile_failures,
        f"checked={len(profile_paths)}, failures={profile_failures}",
    )

    failed_ids = [item["id"] for item in checks if not item["pass"]]
    return {
        "schema_version": 1,
        "work_package_id": contract["work_package_id"],
        "valid": not failed_ids,
        "check_count": len(checks),
        "failed_check_ids": failed_ids,
        "checks": checks,
        "claim_boundary": contract["claim_boundary"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read local framework-story artifacts and print a JSON audit."
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=DEFAULT_CONTRACT,
        help="framework story contract",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="project root used only for read-only local checks",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        contract = load_json(args.contract)
        result = audit_framework_story(args.project_root, contract)
    except ContractError as exc:
        result = {
            "valid": False,
            "error_type": "ContractError",
            "error": str(exc),
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
