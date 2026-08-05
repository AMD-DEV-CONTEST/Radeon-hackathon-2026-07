import json
import subprocess
from pathlib import Path

import pytest

from scripts.release import public_distribution_packet


def _write_release_files(root: Path) -> None:
    (root / "LICENSE").write_text(
        "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        'license = { text = "AGPL-3.0-or-later" }\n', encoding="utf-8"
    )
    (root / "frontend/package.json").parent.mkdir(parents=True)
    (root / "frontend/package.json").write_text(
        '{"license":"AGPL-3.0-or-later"}\n', encoding="utf-8"
    )
    (root / "frontend/src-tauri/Cargo.toml").parent.mkdir(parents=True)
    (root / "frontend/src-tauri/Cargo.toml").write_text(
        'license = "AGPL-3.0-or-later"\n', encoding="utf-8"
    )
    (root / "frontend/vscode-extension/package.json").parent.mkdir(parents=True)
    (root / "frontend/vscode-extension/package.json").write_text(
        '{"license":"AGPL-3.0-or-later"}\n', encoding="utf-8"
    )
    (root / "docs/release").mkdir(parents=True)
    (root / "docs/release/MODEL_NOTICES.md").write_text(
        "# Model Notices\n\nNo bundled model weights.\n", encoding="utf-8"
    )
    (root / "docs/release/THIRD_PARTY_NOTICES.md").write_text(
        "# Third Party Notices\n\nSee SBOMs.\n\n"
        "Corpus inventory: `corpus/THIRD_PARTY_NOTICES.md` and "
        "`corpus/REDISTRIBUTION_BOUNDARY.json`.\n",
        encoding="utf-8",
    )
    _write_corpus_notices(root)


def _write_corpus_notices(root: Path, *, publishable: int = 359, withheld: int = 59) -> None:
    """The corpus is redistributed, so its notices are part of the distribution obligation."""
    (root / "corpus").mkdir(parents=True, exist_ok=True)
    (root / "corpus/THIRD_PARTY_NOTICES.md").write_text(
        "# Corpus Third-Party Notices\n\n## some-project\n\nMIT\n", encoding="utf-8"
    )
    (root / "corpus/REDISTRIBUTION_BOUNDARY.json").write_text(
        json.dumps(
            {
                "schema_version": "determinex-corpus-redistribution-boundary-v1",
                "rule": "a vendored tree is published only if it carries its own license text",
                "publishable_count": publishable,
                "withheld_count": withheld,
                "publishable": [],
                "withheld": [],
            }
        ),
        encoding="utf-8",
    )


def test_public_distribution_packet_requires_operator_review_for_legal_and_scrub(
    tmp_path: Path, monkeypatch
):
    _write_release_files(tmp_path)
    monkeypatch.setattr(
        public_distribution_packet, "_secret_scan_clean", lambda pushed: (True, "clean")
    )

    packet = public_distribution_packet.build_packet(tmp_path, operator_reviewed=False)

    assert packet["schema_version"] == "determinex-legal-public-distribution-evidence-v1"
    assert packet["license_inventory_reviewed"] is True
    assert packet["model_notice_reviewed"] is True
    assert packet["third_party_notices_present"] is True
    assert packet["public_repo_secret_scan_passed"] is True
    assert packet["legal_review_completed"] is False
    assert packet["public_repo_scrub_completed"] is False
    assert packet["authority_granted"] is False


def test_public_distribution_packet_can_record_operator_reviewed_release_packet(
    tmp_path: Path, monkeypatch
):
    _write_release_files(tmp_path)
    monkeypatch.setattr(
        public_distribution_packet, "_secret_scan_clean", lambda pushed: (True, "clean")
    )

    packet = public_distribution_packet.build_packet(tmp_path, operator_reviewed=True)

    assert packet["legal_review_completed"] is True
    assert packet["public_repo_scrub_completed"] is True
    assert packet["authority_granted"] is False


def test_public_distribution_packet_writes_json(tmp_path: Path, monkeypatch):
    _write_release_files(tmp_path)
    monkeypatch.setattr(
        public_distribution_packet, "_secret_scan_clean", lambda pushed: (True, "clean")
    )
    output = tmp_path / "assurance/evidence/public_distribution/legal_public_distribution_test.json"

    public_distribution_packet.write_packet(tmp_path, output, operator_reviewed=True)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == "determinex-legal-public-distribution-evidence-v1"
    assert data["legal_review_completed"] is True


def test_public_distribution_packet_records_secret_scan_timeout_as_blocker(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            ["python", "scripts/security/secret_scan.py", "--pushed"], 240
        )

    monkeypatch.setattr(public_distribution_packet.subprocess, "run", timeout)

    clean, transcript = public_distribution_packet._secret_scan_clean(pushed=True)

    assert clean is False
    assert "timed out" in transcript


# ── Corpus notices coverage (2026-07-31) ───────────────────────────────────────────────────────
# The corpus went from local-only to published, which turned every project vendored inside it into
# something this project redistributes. `third_party_notices_present` did not notice: it was true
# on the strength of a 17-line file naming three SBOMs, while the real inventory of upstream
# projects sat in a 449-line file the packet never opened. An operator attesting legal review off
# that packet would have been attesting over an inventory that omitted all of them.


class TestCorpusNoticesArePartOfTheObligation:
    def test_missing_corpus_notices_fail_the_check(self, tmp_path: Path):
        _write_release_files(tmp_path)
        (tmp_path / "corpus/THIRD_PARTY_NOTICES.md").unlink()

        ok, _ = public_distribution_packet._notices_present(tmp_path)
        assert ok is False, "the corpus ships; notices for what it vendors are not optional"

    def test_missing_boundary_manifest_fails_the_check(self, tmp_path: Path):
        _write_release_files(tmp_path)
        (tmp_path / "corpus/REDISTRIBUTION_BOUNDARY.json").unlink()

        ok, _ = public_distribution_packet._notices_present(tmp_path)
        assert ok is False

    def test_notices_that_exist_but_are_unreachable_fail(self, tmp_path: Path):
        """The exact regression: corpus notices on disk, and the document an operator reads
        never points at them. File-exists alone would have called this covered."""
        _write_release_files(tmp_path)
        (tmp_path / "docs/release/THIRD_PARTY_NOTICES.md").write_text(
            "# Third Party Notices\n\nSee SBOMs.\n", encoding="utf-8"
        )

        ok, _ = public_distribution_packet._notices_present(tmp_path)
        assert ok is False, (
            "notices an operator cannot reach from the release notices are not coverage"
        )

    def test_an_empty_boundary_is_not_coverage(self, tmp_path: Path):
        """A boundary accounting for zero trees would satisfy a file-exists check."""
        _write_release_files(tmp_path)
        _write_corpus_notices(tmp_path, publishable=0, withheld=0)

        ok, _ = public_distribution_packet._notices_present(tmp_path)
        assert ok is False

    def test_an_unparseable_boundary_is_not_coverage(self, tmp_path: Path):
        _write_release_files(tmp_path)
        (tmp_path / "corpus/REDISTRIBUTION_BOUNDARY.json").write_text(
            "{ not json", encoding="utf-8"
        )

        ok, _ = public_distribution_packet._notices_present(tmp_path)
        assert ok is False

    def test_full_coverage_passes_and_is_recorded_as_evidence(self, tmp_path: Path):
        _write_release_files(tmp_path)

        ok, evidence = public_distribution_packet._notices_present(tmp_path)
        assert ok is True
        assert "corpus/THIRD_PARTY_NOTICES.md" in evidence
        assert "corpus/REDISTRIBUTION_BOUNDARY.json" in evidence, (
            "the packet must name the corpus notices it relied on"
        )

    def test_a_notices_gap_blocks_the_attestation_not_just_a_flag(
        self, tmp_path: Path, monkeypatch
    ):
        """Coverage feeds legal_review_completed, so a gap cannot be attested past."""
        _write_release_files(tmp_path)
        (tmp_path / "corpus/THIRD_PARTY_NOTICES.md").unlink()
        monkeypatch.setattr(
            public_distribution_packet, "_secret_scan_clean", lambda pushed: (True, "clean")
        )

        packet = public_distribution_packet.build_packet(tmp_path, operator_reviewed=True)
        assert packet["third_party_notices_present"] is False
        assert packet["legal_review_completed"] is False, (
            "an operator must not be able to attest legal review over an incomplete inventory"
        )


def test_the_real_repo_notices_cover_the_shipped_corpus():
    """End-to-end against this checkout: the corpus really is published, so this must hold."""
    root = Path(__file__).resolve().parent.parent
    if not (root / "corpus").is_dir():
        pytest.skip("no corpus in this checkout")
    ok, evidence = public_distribution_packet._notices_present(root)
    assert ok is True, (
        "the shipped notices do not account for the published corpus -- "
        f"resolved evidence: {evidence}"
    )
