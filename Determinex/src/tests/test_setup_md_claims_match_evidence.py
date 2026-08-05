"""SETUP.md is the first thing a downloader reads. It must not claim more than the evidence.

FOUND 2026-07-31 by reading the generated file instead of the generator. Two of its claims were
false, and both were false in ways prose cannot avoid:

  "This is the verified Windows path: it has been installed, launched and uninstalled on a clean
   Windows host with no Visual C++ runtime present."

True of the artifact verified at the time, and false the next time anyone rebuilt — clean-host
evidence anchors to a specific installer HASH. Measured: the transcripts covered 5fdfe015, 3f72e1d4
and d1f369ef while the bundle being written contained 677273cb and 2942b161. The document whose
entire job is to prevent overclaiming was asserting clean-host verification for two binaries that
had never been near a clean host.

  "### Alternative: <nsis> (not clean-host verified) ... its clean-host check has not been re-run
   since a verification bug was fixed"

Stale in the *other* direction: NSIS had been clean-host verified hours earlier, so this steered
users away from a working installer for a reason that no longer held.

The lesson is the same both ways: a hardcoded sentence about gate state is wrong the moment the
state moves. Both are now derived — per artifact, from the transcript hashes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.release import package_download_bundle as P  # noqa: E402

GENERATOR = REPO_ROOT / "scripts" / "release" / "package_download_bundle.py"


def _artifact(name: str, digest: str) -> P.InstallerArtifact:
    return P.InstallerArtifact(
        source_path=Path(name),
        file_name=name,
        artifact_type="windows_msi" if name.endswith(".msi") else "windows_nsis_setup",
        size_bytes=1,
        sha256=digest,
        authenticode_status="NotSigned",
    )


class TestTheCleanHostClaimIsPerArtifact:
    def test_a_verified_hash_is_claimed(self):
        digest = "a" * 64
        note = "\n".join(
            P._clean_host_note(
                _artifact("x.msi", digest), {digest: "clean_host_install_transcript_x.json"}
            )
        )
        assert "clean-host verified" in note
        assert "has not itself been" not in note
        assert "clean_host_install_transcript_x.json" in note, (
            "the claim must name the transcript that backs it"
        )

    def test_an_unverified_hash_is_not_claimed_and_says_what_to_do(self):
        note = "\n".join(P._clean_host_note(_artifact("x.msi", "b" * 64), {"c" * 64: "other.json"}))
        assert "has not itself been clean-host verified" in note
        assert "run_windows_clean_host_install_smoke.ps1" in note, (
            "a reader told the evidence is missing needs the command that produces it"
        )

    def test_the_artifacts_hash_appears_so_the_reader_can_check(self):
        digest = "d" * 64
        note = "\n".join(P._clean_host_note(_artifact("x.msi", digest), {}))
        assert digest[:16] in note

    def test_no_evidence_at_all_does_not_silently_become_a_claim(self):
        """An empty verified-map is the state of a fresh checkout. It must not read as verified."""
        note = "\n".join(P._clean_host_note(_artifact("x.msi", "e" * 64), {}))
        assert "has not itself been clean-host verified" in note


class TestTranscriptHarvesting:
    def test_only_passing_transcripts_count(self, tmp_path):
        import json

        ev = tmp_path / "assurance" / "evidence"
        ev.mkdir(parents=True)
        good, bad = "1" * 64, "2" * 64
        (ev / "clean_host_install_transcript_good.json").write_text(
            json.dumps(
                {
                    "clean_host_fresh_install": True,
                    "installer_execution_performed": True,
                    "launch_performed": True,
                    "uninstall_performed": True,
                    "bundle": {"installer_sha256": good},
                }
            ),
            encoding="utf-8",
        )
        # Launch failed: the cycle did not complete, so it is not evidence of a working install.
        (ev / "clean_host_install_transcript_bad.json").write_text(
            json.dumps(
                {
                    "clean_host_fresh_install": True,
                    "installer_execution_performed": True,
                    "launch_performed": False,
                    "uninstall_performed": True,
                    "bundle": {"installer_sha256": bad},
                }
            ),
            encoding="utf-8",
        )

        found = P._clean_host_verified_hashes(tmp_path)
        assert good in found
        assert bad not in found, "a transcript whose launch failed is not clean-host evidence"

    def test_a_mocked_transcript_is_not_evidence(self, tmp_path):
        import json

        ev = tmp_path / "assurance" / "evidence"
        ev.mkdir(parents=True)
        (ev / "clean_host_install_transcript_template.json").write_text(
            json.dumps(
                {
                    "clean_host_fresh_install": True,
                    "installer_execution_performed": True,
                    "launch_performed": True,
                    "uninstall_performed": True,
                    "bundle": {"installer_sha256": "mocked_sha256"},
                }
            ),
            encoding="utf-8",
        )
        assert P._clean_host_verified_hashes(tmp_path) == {}, (
            "'mocked_sha256' is a template placeholder, not a verified artifact"
        )

    def test_it_reads_the_real_repo_without_crashing(self):
        found = P._clean_host_verified_hashes(REPO_ROOT)
        assert isinstance(found, dict)
        for digest in found:
            assert len(digest) == 64


class TestTheGeneratorHoldsNoHardcodedGateClaims:
    @pytest.mark.parametrize(
        "forbidden",
        [
            "This is the verified Windows path",
            "not clean-host verified)",
            "clean-host check has not been re-run",
            "Current blockers remain",
        ],
    )
    def test_the_stale_sentences_are_gone(self, forbidden):
        """Each of these was a hardcoded assertion about state that moves."""
        assert forbidden not in GENERATOR.read_text(encoding="utf-8"), (
            f"{forbidden!r} is back — a sentence about gate state cannot be hardcoded"
        )

    def test_signing_status_is_reported_from_measurement(self):
        source = GENERATOR.read_text(encoding="utf-8")
        assert "Signing status measured for the artifacts in this bundle" in source
        assert "a.authenticode_status for a in artifacts" in source, (
            "the signing line must come from the artifacts just probed, not from prose"
        )

    def test_readers_are_pointed_at_the_live_gate_command(self):
        source = GENERATOR.read_text(encoding="utf-8")
        assert "determinex_release_gates.py" in source


def test_the_shipped_setup_md_does_not_overclaim():
    """End-to-end on the newest generated bundle, if one exists in this checkout."""
    bundles = (
        sorted(
            (REPO_ROOT / ".tmp" / "determinex-download-bundles").glob("*/SETUP.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if (REPO_ROOT / ".tmp" / "determinex-download-bundles").is_dir()
        else []
    )
    if not bundles:
        pytest.skip("no generated download bundle in this checkout")
    text = bundles[0].read_text(encoding="utf-8", errors="replace")
    assert "This is the verified Windows path" not in text
    verified = P._clean_host_verified_hashes(REPO_ROOT)
    # Every clean-host claim in the document must be backed by a hash in the transcript set.
    if "This exact build is clean-host verified" in text:
        assert verified, "the document claims clean-host verification with no transcript on disk"
