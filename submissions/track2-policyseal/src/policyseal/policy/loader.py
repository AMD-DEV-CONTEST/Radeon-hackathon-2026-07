from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from policyseal.policy.schema import PolicyDefinition, PolicyPack


class PolicyLoadError(ValueError):
    """A policy pack is malformed, incomplete, or unsafe to load."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise PolicyLoadError(f"cannot read policy file: {error}") from error
    if not isinstance(raw, dict):
        raise PolicyLoadError("policy.yaml must contain a mapping")
    return raw


def load_policy_pack(root: Path) -> PolicyPack:
    root = root.resolve()
    raw = _read_yaml(root / "policy.yaml")
    try:
        definition = PolicyDefinition.model_validate(raw)
    except ValidationError as error:
        raise PolicyLoadError(f"policy schema validation failed: {error}") from error

    rule_ids = [rule.id for rule in definition.rules]
    evidence_ids = [record.id for record in definition.evidence]
    if len(rule_ids) != len(set(rule_ids)):
        raise PolicyLoadError("policy rule IDs must be unique")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise PolicyLoadError("evidence IDs must be unique")

    evidence_by_id = {record.id: record for record in definition.evidence}
    evidence_hashes: dict[str, str] = {}
    for record in definition.evidence:
        evidence_path = (root / record.path).resolve()
        if not evidence_path.is_relative_to(root):
            raise PolicyLoadError(f"evidence path escapes the policy pack: {record.path}")
        try:
            evidence_bytes = evidence_path.read_bytes()
        except OSError as error:
            raise PolicyLoadError(f"missing evidence file: {record.path}") from error
        marker = f"<!-- evidence-id: {record.id} -->".encode()
        if marker not in evidence_bytes:
            raise PolicyLoadError(f"evidence marker {record.id} is missing from {record.path}")
        evidence_hashes[record.path] = hashlib.sha256(evidence_bytes).hexdigest()

    for rule in definition.rules:
        missing = sorted(set(rule.evidence_ids) - evidence_by_id.keys())
        if missing:
            raise PolicyLoadError(f"rule {rule.id} cites unknown evidence: {', '.join(missing)}")

    digest_payload = {
        "definition": definition.model_dump(mode="json"),
        "evidence_sha256": dict(sorted(evidence_hashes.items())),
    }
    digest = hashlib.sha256(_canonical_json(digest_payload)).hexdigest()
    return PolicyPack(definition=definition, sha256=digest, root=root)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and fingerprint a PolicySeal policy pack"
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    pack = load_policy_pack(args.path)
    print(f"PolicySeal policy {pack.version}: {len(pack.rules)} rules, sha256={pack.sha256}")


if __name__ == "__main__":
    main()
