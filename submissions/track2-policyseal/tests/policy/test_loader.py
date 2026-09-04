from pathlib import Path

import pytest

from policyseal.policy.loader import PolicyLoadError, load_policy_pack


def test_v1_policy_has_stable_hash_and_unique_rule_ids() -> None:
    first = load_policy_pack(Path("policies/v1"))
    second = load_policy_pack(Path("policies/v1"))

    assert first.version == "1.0.0"
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
    assert len(first.rules) == 35
    assert len({rule.id for rule in first.rules}) == len(first.rules)


def test_policy_rejects_scripts_and_unknown_fields(tmp_path: Path) -> None:
    (tmp_path / "policy.yaml").write_text(
        "version: 1.0.0\n"
        "name: Unsafe\n"
        "synthetic_only: true\n"
        "default_action: require_approval\n"
        "evidence: []\n"
        "rules: [{id: PS-BAD, reason_code: unsafe_eval, reason: unsafe expression, "
        "when: {}, action: keep, evidence_ids: [EV-MISSING], eval: open('/tmp/x')}]\n",
        encoding="utf-8",
    )

    with pytest.raises(PolicyLoadError, match="schema validation failed"):
        load_policy_pack(tmp_path)


def test_policy_rejects_missing_evidence_marker(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "rules.md").write_text("# No marker\n", encoding="utf-8")
    (tmp_path / "policy.yaml").write_text(
        "version: 1.0.0\n"
        "name: Synthetic test\n"
        "synthetic_only: true\n"
        "default_action: block\n"
        "evidence:\n"
        "  - {id: EV-TEST-001, path: evidence/rules.md, title: Test evidence}\n"
        "rules:\n"
        "  - id: PS-TEST-001\n"
        "    reason_code: test_rule\n"
        "    reason: Controlled test decision\n"
        "    when: {}\n"
        "    action: keep\n"
        "    evidence_ids: [EV-TEST-001]\n",
        encoding="utf-8",
    )

    with pytest.raises(PolicyLoadError, match="evidence marker"):
        load_policy_pack(tmp_path)
