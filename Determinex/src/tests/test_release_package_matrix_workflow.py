from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release_package_matrix.yml"


def test_release_package_matrix_workflow_builds_windows_and_linux_bundles():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "windows-latest" in text
    assert "ubuntu-24.04" in text
    assert "build_release_package.ps1" in text
    # "msi,nsis", never "all". Corrected 2026-07-30: this asserted `-TauriBundleTarget all`, and the
    # Windows job runs on windows-latest where tauri-cli rejects "all" as a --bundles value (only
    # msi and nsis are accepted). So the test was PINNING A BUG -- the Windows half of the release
    # matrix could not complete, and fixing the workflow would have broken this test. Its sibling
    # tests/test_build_release_package_script.py already asserts the corrected msi,nsis default.
    assert "-TauriBundleTarget msi,nsis" in text
    assert "-TauriBundleTarget all" not in text, (
        "'all' is not a valid --bundles value on Windows; the job cannot complete with it"
    )
    assert "npm.cmd" in text
    assert "appimage,deb,rpm" in text
    assert "package_download_bundle.py" in text
    assert "determinex-package-matrix" in text
    assert "actions/upload-artifact@v4" in text
    assert "windows_trust_packet.py" in text
    assert "assurance\\evidence\\windows_trust\\windows_trust_ci.json" in text
    assert "run_windows_clean_host_install_smoke.ps1" in text
    assert "clean_host_install_transcript.py --validate" in text


def test_release_package_matrix_workflow_keeps_release_authority_out_of_ci():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "release_ready: true" not in text
    assert "authority_granted: true" not in text
    assert "workflow_dispatch" in text
    assert "push:" not in text


def test_release_package_matrix_workflow_merges_platform_artifacts_into_public_bundle():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "combined-download-bundle:" in text
    assert "needs: [windows-packages, linux-packages]" in text
    assert "actions/download-artifact@v4" in text
    assert "name: determinex-package-matrix-windows" in text
    assert "name: determinex-package-matrix-linux" in text
    assert ".tmp/combined-installers" in text
    assert "scripts/release/package_download_bundle.py" in text
    assert "scripts/release/determinex_release_gates.py" in text
    assert "determinex-package-matrix-combined" in text
