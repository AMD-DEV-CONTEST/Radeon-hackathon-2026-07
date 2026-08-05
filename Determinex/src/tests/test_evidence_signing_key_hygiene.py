"""Evidence-signing keys: bound the weak set, and never let it grow.

WHY THIS EXISTS
---------------
S1.13. 23 evidence-record families sign with `hmac.new(_record_key(), ...)` where `_record_key()`
falls back to a key written literally in the source, e.g.

    return b"determinex-bounded-rerun-lock-001-test-key"

None of the 23 override env vars is set in this checkout, so the literal is the live path. That
makes the paired `verify_*` a comparison of `hmac(k, x)` against `hmac(k, x)` with a `k` any reader
of the repository knows -- so it detects accidental corruption but cannot detect forgery, while
being named and shaped like an integrity check. `root_cause_packet_gate` REJECTS on signature
mismatch, which reads as enforcement and is not.

WHY THIS IS A GUARD AND NOT A FIX
---------------------------------
The correct pattern already exists one directory up, in `corpus_manager._load_hmac_key`: use the
configured key if valid, otherwise an ephemeral `os.urandom(32)` with a loud warning, so an
unconfigured run fails closed instead of signing with a known key. Copying it into the 23 would
invalidate every record already written across all 23 families -- and because the gate rejects on
mismatch, that turns today's green evidence red. It is a migration (new `signing_key_source` field
plus a re-sign pass, and `scripts/corpus/resign_corpus_records.py` already exists for that shape),
not a one-line change, and it is not something to attempt unattended before a public flip.

What is safe and worth doing now is bounding it. The weak set is enumerated below, so:

  * a 24th family cannot silently join it,
  * migrating one requires editing this list, which is where progress gets recorded,
  * the good pattern cannot regress to a literal without failing a test.

Threat model, stated plainly so the deferral is judged on facts: these records sign local evidence
inside the developer's own checkout. The weakness is integrity theatre rather than a credential
leak -- the literals are not secrets protecting anything else, and nothing authenticates to a
remote service with them. It still must not ship silently, because this project's claim is that it
does not overstate what it has verified.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

#: Families whose signing key falls back to a literal published in the source. Every entry is a
#: known gap, not an approval. Shrinking this list is the migration; growing it is a regression.
KNOWN_LITERAL_FALLBACK = {
    "corpus/programbench/alternate_cleanroom_image_provenance_record.py",
    "corpus/programbench/approved_scanner_setup_record.py",
    "corpus/programbench/artifact_source_escalation_record.py",
    "corpus/programbench/bounded_rerun_record.py",
    "corpus/programbench/cleanroom_build_recipe_provenance_gap_record.py",
    "corpus/programbench/cleanroom_build_recipe_recovery_record.py",
    "corpus/programbench/cleanroom_image_hydration_record.py",
    "corpus/programbench/cleanroom_image_import_record.py",
    "corpus/programbench/cleanroom_image_remediation_plan_record.py",
    "corpus/programbench/cleanroom_image_scan_record.py",
    "corpus/programbench/cleanroom_image_scan_triage_record.py",
    "corpus/programbench/cleanroom_image_scanner_admission_record.py",
    "corpus/programbench/cleanroom_recipe_provenance_recovery_record.py",
    "corpus/programbench/codex_completion_campaign_record.py",
    "corpus/programbench/dockerhub_manifest_provenance_record.py",
    "corpus/programbench/infra_failure_triage_record.py",
    "corpus/programbench/official_artifact_security_decision_record.py",
    "corpus/programbench/operator_artifact_admission_record.py",
    "corpus/programbench/operator_provenance_request_packet_record.py",
    "corpus/programbench/real_bounded_rerun_record.py",
    "corpus/programbench/rebuild_provenance_quarantine_decision_record.py",
    "corpus/programbench/root_cause_packet.py",
    "corpus/programbench/upstream_artifact_authority_recheck_record.py",
}

#: Modules that must stay fail-closed. Reference implementation for the migration.
MUST_STAY_FAIL_CLOSED = {"corpus/corpus_manager.py"}

_LITERAL_KEY_RETURN = re.compile(r'return\s+b"([^"]{8,})"')

# Key helpers are not consistently named: `_record_key`, `_load_hmac_key`, and root_cause_packet's
# `_packet_key` all exist. Matching only the first two reported root_cause_packet as unconfigurable
# when it reads DETERMINEX_ROOT_CAUSE_PACKET_KEY perfectly well -- a false finding from a narrow
# regex, which is exactly the kind of thing these tests must not manufacture.
_KEY_FN = re.compile(r"def _[a-z_]*key[a-z_]*\(\).*?(?=\ndef |\Z)", re.DOTALL)


def _signing_modules() -> dict[str, str]:
    """rel-path -> source, for everything that computes an HMAC."""
    out: dict[str, str] = {}
    for path in sorted(SCRIPTS.rglob("*.py")):
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "hmac.new" in src:
            out[path.relative_to(SCRIPTS).as_posix()] = src
    return out


def test_no_new_family_signs_with_a_key_published_in_the_source():
    """THE guard. A new evidence family copied from one of the 23 inherits the literal, and its
    verify_* then looks like enforcement while proving nothing."""
    found = {rel for rel, src in _signing_modules().items() if _LITERAL_KEY_RETURN.search(src)}
    added = sorted(found - KNOWN_LITERAL_FALLBACK)
    assert not added, (
        f"{len(added)} signing family/families return a hardcoded key literal and are not in the "
        f"known-gap list: {added}. Do not add to KNOWN_LITERAL_FALLBACK to make this pass -- copy "
        f"corpus_manager._load_hmac_key so an unconfigured run fails closed instead."
    )


def test_the_known_gap_list_does_not_silently_rot():
    """If a family is migrated or deleted, the list must be updated in the same change, so the
    recorded count stays the real count. This is what keeps the audit trail honest."""
    found = {rel for rel, src in _signing_modules().items() if _LITERAL_KEY_RETURN.search(src)}
    stale = sorted(KNOWN_LITERAL_FALLBACK - found)
    assert not stale, (
        f"these are listed as literal-fallback but no longer are (migrated or removed): {stale}. "
        f"Remove them from KNOWN_LITERAL_FALLBACK and update the count in "
        f"docs/audits/RELEASE_READINESS_SCOPE_20260730.md."
    )


def test_the_reference_implementation_stays_fail_closed():
    """corpus_manager is the pattern the 23 must migrate to. If it regresses to a literal, the
    migration loses its target."""
    mods = _signing_modules()
    for rel in MUST_STAY_FAIL_CLOSED:
        assert rel in mods, f"{rel} no longer computes an HMAC; has it moved?"
        src = mods[rel]
        assert "urandom(32)" in src, (
            f"{rel} no longer derives an ephemeral key; it is the fail-closed reference the 23 "
            f"literal-fallback families are meant to adopt"
        )
        assert not _LITERAL_KEY_RETURN.search(src), (
            f"{rel} has gained a hardcoded key literal -- the good pattern has regressed"
        )


def test_every_weak_family_can_at_least_be_configured_out_of_the_weakness():
    """The mitigation available today is setting the override env var. A family with a literal and
    NO override would be unfixable without a code change, which is strictly worse -- and would make
    the documented remediation a lie for that family."""
    unfixable: list[str] = []
    for rel, src in _signing_modules().items():
        if rel not in KNOWN_LITERAL_FALLBACK:
            continue
        # The override must be read inside the key function, not merely present in the file.
        key_fn = _KEY_FN.search(src)
        body = key_fn.group(0) if key_fn else ""
        if not re.search(r'environ\.get\("DETERMINEX_[A-Z0-9_]*KEY"', body):
            unfixable.append(rel)
    assert not unfixable, (
        f"these sign with a published literal and read no key override in their key function, so "
        f"an operator cannot mitigate without editing code: {unfixable}"
    )


def test_the_documented_env_vars_match_the_code():
    """docs/SECURITY_POSTURE.md lists the override vars so the mitigation is actually usable --
    the audit's original finding was that none of them was documented anywhere. A doc that drifts
    from the code is worse than no doc, because an operator would set a var nothing reads."""
    doc_path = REPO_ROOT / "docs" / "SECURITY_POSTURE.md"
    assert doc_path.is_file(), "docs/SECURITY_POSTURE.md is missing"
    doc = doc_path.read_text(encoding="utf-8", errors="replace")

    missing: list[str] = []
    for rel, src in _signing_modules().items():
        if rel not in KNOWN_LITERAL_FALLBACK:
            continue
        key_fn = _KEY_FN.search(src)
        body = key_fn.group(0) if key_fn else ""
        for var in re.findall(r'environ\.get\("(DETERMINEX_[A-Z0-9_]*KEY)"', body):
            if var not in doc:
                missing.append(f"{var} ({rel})")
    assert not missing, (
        f"{len(missing)} signing override var(s) are not documented in docs/SECURITY_POSTURE.md, "
        f"so the stated mitigation cannot be followed: {sorted(missing)[:8]}"
    )
