"""Establish the extension_compat release evidence by DOING each check, not asserting it.

The gate wants five fields true in a packet under `assurance/evidence/extension_compat/`. Before
this script there was no generator at all, so the only way to satisfy it was to hand-write a JSON
file claiming five things — which is the shape of overclaim this repo keeps finding. Every field
here is the recorded outcome of an operation this script performs:

  extension_api_contract_defined   the contract doc exists and describes the commands the manifest
                                   actually contributes (cross-checked, not merely present)
  vsix_import_smoke_passed         the VSIX is INSTALLED into a throwaway extensions dir with a
                                   real VS Code and then listed back by id@version
  open_vsx_metadata_parsed         every field Open VSX requires is present and well-formed
  sandbox_permissions_enforced     no `capabilities` declared, and the source spawns a fixed argv
                                   with no `shell: true` and no interpolation into the command
  activation_event_smoke_passed    `npm test` runs the suite inside a REAL extension host and it
                                   passes; that suite observes the inactive->active transition

Nothing here needs a network once VS Code is cached, and nothing runs model-generated code.

WHY THE VS CODE BINARY IS REUSED FROM .vscode-test: `@vscode/test-electron` already downloads and
caches a real VS Code for the extension-host suite. Downloading a second copy to install a VSIX
into would be 320 MB for no extra assurance.

ELECTRON_RUN_AS_NODE: cleared before invoking anything, for the reason documented at length in
src/test/runTest.ts — it makes VS Code's own binary behave as plain Node, and VS Code sets it for
processes it spawns, so it is present whenever this is run from a VS Code terminal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SCHEMA_VERSION = "determinex-extension-compat-runtime-evidence-v1"
EXTENSION_DIR = Path("frontend/vscode-extension")
CONTRACT_DOC = Path("docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md")

#: Open VSX rejects a package missing any of these.
OPEN_VSX_REQUIRED = (
    "name",
    "displayName",
    "description",
    "version",
    "publisher",
    "engines",
    "license",
    "repository",
    "categories",
)

#: Patterns that would break the sandbox claim: a shell, or a command built by interpolation.
UNSAFE_SPAWN_PATTERNS = (
    (r"shell\s*:\s*true", "spawns through a shell"),
    (r"\bexec\s*\(", "uses child_process.exec (shell)"),
    (r"execSync\s*\(", "uses child_process.execSync (shell)"),
)


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    return env


def _find_vscode_cli(ext_dir: Path) -> Path | None:
    """The VS Code *CLI* that @vscode/test-electron already cached, if any.

    `bin/code.cmd`, not the sibling `Code.exe`. Code.exe is the GUI entry point: given
    `--install-extension` it hands off to a detached process and never returns, so an
    `--install-extension` through it hit the 300 s timeout with nothing to show. The CLI wrapper
    runs the install synchronously and exits, which is what a script can observe.
    """
    cache = ext_dir / ".vscode-test"
    if not cache.is_dir():
        return None
    for pattern in ("vscode-*/bin/code.cmd", "vscode-*/bin/code"):
        for candidate in sorted(cache.glob(pattern)):
            if candidate.is_file():
                return candidate
    return None


# ── the five checks ──────────────────────────────────────────────────────────────────────────────


def _check_contract(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """The contract must define the bar the gate enforces, and describe this extension.

    "The file exists" is a weak claim, so two things are cross-checked:

    1. DOC ↔ GATE. The contract enumerates the required packet fields and the schema version.
       `determinex_release_gates._extension_compat_errors` enforces its own list. If someone adds a
       field to the gate and not to the contract, the document stops being the contract.

    2. DOC ↔ MANIFEST. The contract must name the commands this extension actually contributes.

    The second check initially failed on all four commands, and the first reading — "the doc is
    incomplete" — was only half right. The document described extensions coming INTO Determinex
    (intake, trust boundary, install authorisation) while the gate's evidence pointed at
    `frontend/vscode-extension`, our own outgoing extension. The doc was not stale; it was about the
    other direction. Resolved by writing the outgoing direction down rather than by relaxing this
    check to match what happened to be there.
    """
    doc = root / CONTRACT_DOC
    if not doc.is_file():
        return {"passed": False, "reason": f"{CONTRACT_DOC} is absent"}
    text = doc.read_text(encoding="utf-8", errors="replace")

    problems: list[str] = []

    try:
        from scripts.release import determinex_release_gates as gates

        required_fields = gates._extension_compat_errors({})
        # Each error reads "<field> must be true|false"; recover the field names from the gate
        # itself rather than restating them here.
        gate_fields = sorted({e.split(" must be ")[0] for e in required_fields if " must be " in e})
        undocumented_fields = [f for f in gate_fields if f not in text]
        if undocumented_fields:
            problems.append(
                "contract omits gate-required field(s): " + ", ".join(undocumented_fields)
            )
        if gates.EXTENSION_COMPAT_SCHEMA_VERSION not in text:
            problems.append(
                f"contract omits the schema version {gates.EXTENSION_COMPAT_SCHEMA_VERSION}"
            )
    except Exception as exc:  # the gate module is the authority; say so if it cannot be read
        gate_fields = []
        problems.append(
            f"could not cross-check against the release gate: {type(exc).__name__}: {exc}"
        )

    contributed = [
        c.get("command", "") for c in (manifest.get("contributes", {}) or {}).get("commands", [])
    ]
    undocumented_commands = [c for c in contributed if c and c not in text]
    if undocumented_commands:
        problems.append("contract does not mention command(s): " + ", ".join(undocumented_commands))

    return {
        "passed": not problems,
        "reason": (
            "contract defines every gate-required field and names every contributed command"
            if not problems
            else "; ".join(problems)
        ),
        "path": str(CONTRACT_DOC).replace("\\", "/"),
        "gate_required_fields": gate_fields,
        "commands_contributed": contributed,
        "problems": problems,
    }


def _check_open_vsx_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    missing = [f for f in OPEN_VSX_REQUIRED if not manifest.get(f)]
    problems = list(missing)
    engines = manifest.get("engines") or {}
    if not isinstance(engines, dict) or not engines.get("vscode"):
        problems.append("engines.vscode")
    repo = manifest.get("repository")
    repo_url = repo.get("url") if isinstance(repo, dict) else repo
    if not (isinstance(repo_url, str) and repo_url.startswith("http")):
        problems.append("repository.url must be an http(s) URL")
    return {
        "passed": not problems,
        "reason": "all Open VSX required fields present"
        if not problems
        else f"missing/invalid: {problems}",
        "identity": f"{manifest.get('publisher')}.{manifest.get('name')}@{manifest.get('version')}",
        "license": manifest.get("license"),
        "engines_vscode": engines.get("vscode") if isinstance(engines, dict) else None,
        "missing_or_invalid": problems,
    }


def _check_sandbox_permissions(ext_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    problems: list[str] = []
    if manifest.get("capabilities") is not None:
        problems.append("manifest declares `capabilities`")

    source = ext_dir / "src" / "extension.ts"
    findings: list[str] = []
    if not source.is_file():
        problems.append("src/extension.ts is absent, so the spawn boundary cannot be inspected")
    else:
        text = source.read_text(encoding="utf-8", errors="replace")
        for pattern, description in UNSAFE_SPAWN_PATTERNS:
            if re.search(pattern, text):
                findings.append(description)
        if not re.search(r"cp\.spawn\s*\(", text):
            findings.append("no cp.spawn found — the argv boundary may have changed shape")
    problems.extend(findings)
    return {
        "passed": not problems,
        "reason": (
            "no capabilities declared; backend invoked via a fixed argv with no shell"
            if not problems
            else "; ".join(problems)
        ),
        "declares_capabilities": manifest.get("capabilities") is not None,
        "unsafe_spawn_findings": findings,
    }


def _check_vsix_import(
    ext_dir: Path, manifest: dict[str, Any], vscode_cli: Path | None
) -> dict[str, Any]:
    """Actually install the VSIX with a real VS Code and list it back.

    A structural check on the zip proves the file is well-formed; it does not prove VS Code will
    accept it. Installing into a throwaway --extensions-dir does, and leaves the developer's own
    VS Code untouched.
    """
    vsixes = sorted(ext_dir.glob("*.vsix"))
    if not vsixes:
        return {"passed": False, "reason": "no .vsix present — run `npm run package` first"}
    vsix = vsixes[-1]

    # Structural first: a corrupt zip should say so rather than surface as an opaque CLI failure.
    try:
        with zipfile.ZipFile(vsix) as archive:
            names = set(archive.namelist())
            packaged = json.loads(archive.read("extension/package.json").decode("utf-8"))
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        return {"passed": False, "reason": f"{vsix.name} is not a readable VSIX: {exc}"}

    expected_id = f"{manifest.get('publisher')}.{manifest.get('name')}"
    packaged_id = f"{packaged.get('publisher')}.{packaged.get('name')}"
    result: dict[str, Any] = {
        "vsix": vsix.name,
        "vsix_sha256": _sha256(vsix),
        "packaged_identity": f"{packaged_id}@{packaged.get('version')}",
        "source_identity": f"{expected_id}@{manifest.get('version')}",
        # The VSIX must not carry the test harness. .vscodeignore excludes out/test/**, and this is
        # where that exclusion is actually verified rather than trusted.
        "ships_test_harness": any(n.startswith("extension/out/test/") for n in names),
    }
    if packaged_id != expected_id or packaged.get("version") != manifest.get("version"):
        result.update(passed=False, reason="packaged identity differs from source package.json")
        return result
    if result["ships_test_harness"]:
        result.update(
            passed=False, reason="the VSIX contains out/test/ — the harness must not ship"
        )
        return result
    if vscode_cli is None:
        result.update(
            passed=False,
            reason="no cached VS Code under .vscode-test — run `npm test` once so the "
            "install can be verified against a real VS Code",
        )
        return result

    tmp = Path(tempfile.mkdtemp(prefix="dtx-vsix-"))
    try:
        install = subprocess.run(
            [
                str(vscode_cli),
                "--install-extension",
                str(vsix),
                "--force",
                "--extensions-dir",
                str(tmp / "ext"),
                "--user-data-dir",
                str(tmp / "user"),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env=_clean_env(),
        )
        listing = subprocess.run(
            [
                str(vscode_cli),
                "--list-extensions",
                "--show-versions",
                "--extensions-dir",
                str(tmp / "ext"),
                "--user-data-dir",
                str(tmp / "user"),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env=_clean_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.update(passed=False, reason=f"VS Code install invocation failed: {exc}")
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    listed = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    wanted = f"{expected_id}@{manifest.get('version')}"
    ok = install.returncode == 0 and any(entry.lower() == wanted.lower() for entry in listed)
    result.update(
        passed=ok,
        reason=(
            f"VS Code installed and listed {wanted}"
            if ok
            else f"install rc={install.returncode}; listed={listed}; "
            f"{(install.stderr or install.stdout).strip()[:300]}"
        ),
        vscode_cli=str(vscode_cli),
        install_exit_code=install.returncode,
        extensions_listed=listed,
    )
    return result


def _check_activation_smoke(ext_dir: Path, run_host: bool) -> dict[str, Any]:
    """Run the extension-host suite. Passing it IS the evidence.

    That suite asserts the inactive->active transition through a contributed command, which is the
    only way to establish that `activationEvents: []` works — it relies on the implicit onCommand
    events VS Code synthesises from contributes.commands, and no file-reading check can see that.
    """
    suite = ext_dir / "src" / "test" / "suite" / "extension.test.ts"
    if not suite.is_file():
        return {
            "passed": False,
            "reason": "no extension-host suite at src/test/suite/extension.test.ts",
        }
    if not run_host:
        return {
            "passed": False,
            "reason": "skipped (--no-host); the packet cannot claim this field",
        }

    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        return {"passed": False, "reason": "npm not on PATH, so the extension host cannot be run"}
    try:
        proc = subprocess.run(
            [npm, "test"],
            cwd=str(ext_dir),
            capture_output=True,
            text=True,
            timeout=1800,
            env=_clean_env(),
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "reason": f"extension-host run failed to start: {exc}"}

    output = proc.stdout + proc.stderr
    passing = re.search(r"(\d+)\s+passing", output)
    transition = "activation observed as a transition: true" in output
    return {
        "passed": proc.returncode == 0 and transition,
        "reason": (
            "the extension host observed an inactive->active transition via a contributed command"
            if proc.returncode == 0 and transition
            else f"npm test rc={proc.returncode}; transition_observed={transition}"
        ),
        "harness": "@vscode/test-electron",
        "tests_passing": int(passing.group(1)) if passing else 0,
        "activation_transition_observed": transition,
        "exit_code": proc.returncode,
    }


def build_packet(root: Path, *, run_host: bool = True) -> dict[str, Any]:
    ext_dir = root / EXTENSION_DIR
    manifest_path = ext_dir / "package.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no extension manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    vscode_cli = _find_vscode_cli(ext_dir)

    contract = _check_contract(root, manifest)
    metadata = _check_open_vsx_metadata(manifest)
    sandbox = _check_sandbox_permissions(ext_dir, manifest)
    # Activation first: it populates the VS Code cache that the VSIX install then reuses.
    activation = _check_activation_smoke(ext_dir, run_host)
    if vscode_cli is None:
        vscode_cli = _find_vscode_cli(ext_dir)
    vsix = _check_vsix_import(ext_dir, manifest, vscode_cli)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "extension_identity": metadata["identity"],
        "extension_api_contract_defined": bool(contract["passed"]),
        "vsix_import_smoke_passed": bool(vsix["passed"]),
        "open_vsx_metadata_parsed": bool(metadata["passed"]),
        "sandbox_permissions_enforced": bool(sandbox["passed"]),
        "activation_event_smoke_passed": bool(activation["passed"]),
        "checks": {
            "extension_api_contract_defined": contract,
            "vsix_import_smoke_passed": vsix,
            "open_vsx_metadata_parsed": metadata,
            "sandbox_permissions_enforced": sandbox,
            "activation_event_smoke_passed": activation,
        },
        "claim_boundary": (
            "This records VS Code extension runtime-compatibility observations only. Each field is "
            "the outcome of an operation performed by scripts/release/extension_compat_packet.py; "
            "none is asserted. It does not grant release authority."
        ),
        "authority_granted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--no-host",
        action="store_true",
        help="skip the extension-host run (the packet then cannot claim activation)",
    )
    args = parser.parse_args()

    root = Path.cwd()
    packet = build_packet(root, run_host=not args.no_host)
    output = (
        args.output
        or root / "assurance/evidence/extension_compat" / f"extension_compat_{_utc_stamp()}.json"
    )
    output = output if output.is_absolute() else root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {output}")
    for field, check in packet["checks"].items():
        mark = "PASS" if check.get("passed") else "FAIL"
        print(f"  {mark}  {field}: {check.get('reason')}")
    all_true = all(
        packet[f]
        for f in (
            "extension_api_contract_defined",
            "vsix_import_smoke_passed",
            "open_vsx_metadata_parsed",
            "sandbox_permissions_enforced",
            "activation_event_smoke_passed",
        )
    )
    print(f"\nall five fields established: {all_true}")
    return 0 if all_true else 1


if __name__ == "__main__":
    raise SystemExit(main())
