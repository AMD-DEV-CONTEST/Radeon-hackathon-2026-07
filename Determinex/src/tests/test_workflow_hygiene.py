"""Workflow hygiene: things that silently break CI or silently weaken it.

Each check here exists because the corresponding mistake was made in this repository, not because
it is good practice in the abstract.

1. SHA-PINNED ACTIONS. `tauri-apps/tauri-action@v0` is a floating tag the upstream maintainer
   re-points, and `dtolnay/rust-toolchain@stable` is a force-pushed branch. Both ran in the
   release job that holds TAURI_SIGNING_PRIVATE_KEY with `contents: write`. Because
   `bundle.createUpdaterArtifacts` is true and the updater endpoint is live, that key signs
   archives every installed client accepts -- so a compromise of either ref is silent RCE across
   all installs, not one bad release. tauri-action shells out to cargo, which inherits the step
   env, so a poisoned toolchain action only needs to drop a `cargo` shim on PATH.

2. NO '#' COMMENT INSIDE A BACKTICK CONTINUATION. A PowerShell `run:` block that continues lines
   with a trailing backtick is broken by a comment line placed between them: the continuation
   terminates and the remaining arguments are lost. I did this to the release matrix while
   documenting a different fix in the same file.

3. THE WINDOWS BUNDLE TARGET. tauri-cli accepts only `msi` and `nsis` for --bundles on Windows.
   `-TauriBundleTarget all` made the Windows half of the release matrix unable to complete, and a
   test asserted that invalid value, so fixing the workflow would have broken the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"

# Refs that upstream can move under us. actions/* first-party ones are left alone deliberately:
# GitHub controls them, they are the ecosystem default, and pinning every one of them creates
# maintenance noise that gets abandoned. These four are third-party and two of them see the
# signing key.
MUTABLE_REF_ACTIONS = (
    "tauri-apps/tauri-action",
    "dtolnay/rust-toolchain",
    "astral-sh/setup-uv",
    "extractions/setup-just",
)


def _workflows() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))


def test_there_are_workflows_to_check():
    """Guard the guard: a glob that matches nothing would make every test below vacuous."""
    assert _workflows(), f"no workflow files found under {WORKFLOW_DIR}"


def test_every_workflow_is_valid_yaml():
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    for path in _workflows():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise AssertionError(f"{path.name} is not valid YAML: {exc}") from exc
        assert isinstance(loaded, dict), f"{path.name} did not parse to a mapping"
        assert loaded.get("jobs"), f"{path.name} declares no jobs"


@pytest.mark.parametrize("action", MUTABLE_REF_ACTIONS)
def test_third_party_actions_are_pinned_to_a_commit_sha(action: str):
    offenders: list[str] = []
    for path in _workflows():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(rf"uses:\s*{re.escape(action)}@(\S+)", line)
            if match and not re.fullmatch(r"[0-9a-f]{40}", match.group(1)):
                offenders.append(f"{path.name}:{i} -> {match.group(1)}")
    assert not offenders, (
        f"{action} must be pinned to a full 40-char commit SHA, not a movable tag or branch. "
        f"Offenders: {offenders}. Resolve with: "
        f"gh api repos/{action}/commits/<ref> --jq .sha"
    )


def test_no_comment_line_sits_inside_a_powershell_backtick_continuation():
    """A '#' line between backtick-continued arguments silently truncates the command."""
    offenders: list[str] = []
    for path in _workflows():
        lines = path.read_text(encoding="utf-8").splitlines()
        for i in range(len(lines) - 1):
            if not lines[i].rstrip().endswith("`"):
                continue
            # A COMMENT ending in a backtick continues nothing -- there is no command to
            # truncate. Without this the guard flags prose that quotes a `token` at the end
            # of a line, which is how it went red on a YAML comment explaining an earlier
            # CI fix. A guard that fires on prose trains people to edit prose around it.
            if lines[i].strip().startswith("#"):
                continue
            nxt = lines[i + 1].strip()
            if nxt.startswith("#"):
                offenders.append(f"{path.name}:{i + 2} -> {nxt[:60]}")
    assert not offenders, (
        "a '#' comment directly after a line ending in a backtick terminates the PowerShell "
        f"continuation and drops every remaining argument. Move it above the command. {offenders}"
    )


def test_bundle_targets_is_not_restricted_to_one_platform():
    """`release.yml` builds windows-x86_64, macos-x86_64, macos-aarch64 and linux-x86_64 from this
    single tauri.conf.json. Pinning `bundle.targets` to a Windows-only list (msi/nsis) therefore
    breaks three of the four release jobs.

    I did exactly that while testing whether an explicit targets array would make
    createUpdaterArtifacts emit anything (it did not), and reverted it. This is the guard so the next
    such experiment cannot ship.
    """
    import json as _json

    config = _json.loads(
        (ROOT / "frontend" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    targets = config.get("bundle", {}).get("targets")
    if isinstance(targets, str):
        return  # "all" is the portable form
    assert isinstance(targets, list), f"unexpected bundle.targets type: {type(targets)}"
    windows_only = {"msi", "nsis"}
    assert not set(targets).issubset(windows_only), (
        f"bundle.targets is {targets}, which is Windows-only; release.yml also builds macOS and "
        f'Linux from this config and those jobs would fail. Use "all", or pass --bundles per job.'
    )


def test_windows_jobs_do_not_request_an_invalid_bundle_target():
    """`all` is not a valid --bundles value on Windows; the job cannot complete with it."""
    for path in _workflows():
        text = path.read_text(encoding="utf-8")
        if "windows-latest" not in text:
            continue
        assert "-TauriBundleTarget all" not in text, (
            f"{path.name} passes -TauriBundleTarget all in a workflow that runs on windows-latest; "
            f"tauri-cli accepts only msi and nsis there"
        )
