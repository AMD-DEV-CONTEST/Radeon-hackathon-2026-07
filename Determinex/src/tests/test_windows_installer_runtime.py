"""Can the installed Windows app actually start on a machine that is not a dev box?

WHY THIS EXISTS
---------------
On 2026-07-29 the shipped MSI installed cleanly (exit 0) and produced an app that could not
start at all. `determinex.exe` died in loader initialisation with 0xC0000135
(STATUS_DLL_NOT_FOUND) about 2 s after launch, because it imports MSVCP140.dll and
MSVCP140_1.dll (plus VCRUNTIME140.dll transitively) and a clean Windows 11 image ships none of
them. A developer machine cannot reproduce it: any Visual Studio or VC++ redistributable
satisfies the dependency permanently.

The package was trying to handle it and failed twice over. `windows/vc_redist.wxs` declared a
CustomAction to run the redistributable it shipped, and (1) the WiX linker pruned the whole
fragment because nothing referenced it, silently, so the action was absent from the MSI while
`tauri build` reported success; and (2) once anchored so it genuinely ran, it returned 1618
(ERROR_INSTALL_ALREADY_RUNNING) because a nested install cannot run inside our own MSI
transaction, and Return="ignore" converted that into a silent success. Both faults produced a
green build and a green test suite.

So the runtime is now shipped app-local, beside the executable, where the loader looks first.
See frontend/src-tauri/CRT_RUNTIME.md.

The guard below is deliberately derived FROM THE BINARY, not from a list of DLL names. A
hardcoded list would have to be remembered every time a native dependency changes, and the
failure mode of forgetting is an app that cannot start. Parsing the import table means a new
must-ship dependency fails a test instead.
"""

from __future__ import annotations

import base64
import json
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TAURI_DIR = ROOT / "frontend" / "src-tauri"
CONFIG_PATH = TAURI_DIR / "tauri.conf.json"

# Windows provides these itself, so their absence is not an installer problem. The UCRT
# (api-ms-win-crt-*) has been an OS component since Windows 10; the VC++ CRT (MSVCP140*,
# VCRUNTIME140*) never has, which is the entire distinction this bug turned on.
OS_PROVIDED_PREFIXES = ("api-ms-win-", "ext-ms-win-")
OS_PROVIDED = {
    "kernel32.dll",
    "user32.dll",
    "gdi32.dll",
    "advapi32.dll",
    "shell32.dll",
    "ole32.dll",
    "oleaut32.dll",
    "ws2_32.dll",
    "ntdll.dll",
    "crypt32.dll",
    "bcrypt.dll",
    "secur32.dll",
    "shlwapi.dll",
    "comdlg32.dll",
    "comctl32.dll",
    "userenv.dll",
    "version.dll",
    "psapi.dll",
    "dbghelp.dll",
    "setupapi.dll",
    "winmm.dll",
    "imm32.dll",
    "dwmapi.dll",
    "uxtheme.dll",
    "propsys.dll",
    "windowscodecs.dll",
    "d3d11.dll",
    "d3d12.dll",
    "dxgi.dll",
    "directml.dll",
    "d3dcompiler_47.dll",
    "gdiplus.dll",
    "msimg32.dll",
    "iphlpapi.dll",
    "winhttp.dll",
    "wininet.dll",
    "rpcrt4.dll",
    "ucrtbase.dll",
    "msvcrt.dll",
    "bcryptprimitives.dll",
    "cfgmgr32.dll",
    "powrprof.dll",
    "normaliz.dll",
    "dnsapi.dll",
    "mswsock.dll",
    "wintrust.dll",
    "urlmon.dll",
    "oleacc.dll",
    "wtsapi32.dll",
    "credui.dll",
    "dcomp.dll",
    "hid.dll",
    "opengl32.dll",
    "shcore.dll",
    "combase.dll",
    "kernelbase.dll",
    "pdh.dll",
    "mpr.dll",
    "netapi32.dll",
    "authz.dll",
    "sspicli.dll",
    "profapi.dll",
    "win32u.dll",
}


def _config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _resources() -> list[str]:
    resources = _config().get("bundle", {}).get("resources", [])
    # The map form is also legal; both spellings are accepted here so the test does not break
    # if the declaration style changes.
    return list(resources.keys()) if isinstance(resources, dict) else list(resources)


def pe_imports(path: Path) -> list[str]:
    """DLL names from a PE import table.

    Reads data directory index 1. Index 0 is the EXPORT table, and reading that by mistake
    reports the binary's own exported symbols as if they were imports, which is exactly how
    this investigation lost half an hour.
    """
    b = path.read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    if b[pe : pe + 4] != b"PE\0\0":
        raise ValueError(f"{path} is not a PE file")
    n_sections = struct.unpack_from("<H", b, pe + 6)[0]
    opt_size = struct.unpack_from("<H", b, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", b, opt)[0]
    dirs = opt + (112 if magic == 0x20B else 96)
    import_rva = struct.unpack_from("<I", b, dirs + 8)[0]
    if not import_rva:
        return []

    sections = []
    sec = opt + opt_size
    for i in range(n_sections):
        base = sec + i * 40
        vsize, va, rawsize, raw = struct.unpack_from("<IIII", b, base + 8)
        sections.append((va, max(vsize, rawsize), raw))

    def to_off(rva: int) -> int | None:
        for va, size, raw in sections:
            if va <= rva < va + size:
                return raw + (rva - va)
        return None

    names: list[str] = []
    off = to_off(import_rva)
    if off is None:
        return []
    while True:
        entry = b[off : off + 20]
        if len(entry) < 20 or entry == b"\0" * 20:
            break
        name_rva = struct.unpack_from("<I", entry, 12)[0]
        if name_rva == 0:
            break
        noff = to_off(name_rva)
        if noff is None:
            break
        names.append(b[noff : b.index(b"\0", noff)].decode("ascii", "replace"))
        off += 20
    return names


def must_ship(imported: list[str]) -> set[str]:
    out = set()
    for dll in imported:
        low = dll.lower()
        if low in OS_PROVIDED or low.startswith(OS_PROVIDED_PREFIXES):
            continue
        out.add(low)
    return out


def _built_exe() -> Path | None:
    for candidate in (
        Path("T:/determinex-target/release/determinex.exe"),
        TAURI_DIR / "target" / "release" / "determinex.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def test_the_crt_runtime_is_shipped_beside_the_executable():
    """THE regression, in config terms.

    Tauri preserves a resource's relative path under the resource root, and on Windows that
    root is the executable's own directory. A bare filename therefore lands next to the exe,
    which is where the loader looks first. A subdirectory would not be on the search path, so
    these must stay bare.
    """
    resources = _resources()
    required = {"vcruntime140.dll", "msvcp140.dll", "msvcp140_1.dll"}
    declared = {r.lower() for r in resources}
    missing = required - declared
    assert not missing, (
        f"bundle.resources does not ship {sorted(missing)}. determinex.exe imports these (or "
        f"pulls them in transitively) and a clean Windows host has none of them, so the "
        f"installed app dies with 0xC0000135 before showing a window."
    )
    for dll in sorted(required):
        matches = [r for r in resources if r.lower() == dll]
        assert matches and "/" not in matches[0] and "\\" not in matches[0], (
            f"{dll} must be declared as a bare filename so it lands beside the exe, not in a "
            f"subdirectory the loader does not search (got {matches})"
        )


def test_the_shipped_crt_files_exist_and_are_one_consistent_version():
    """Mixing CRT versions across MSVCP140*/VCRUNTIME140* is unsupported by Microsoft and
    fails in ways far less obvious than a missing file."""
    crt = [
        r
        for r in _resources()
        if re.fullmatch(r"(msvcp140.*|vcruntime140.*|concrt140)\.dll", r, re.I)
    ]
    assert crt, "no CRT DLLs declared in bundle.resources"
    for name in crt:
        path = TAURI_DIR / name
        assert path.is_file(), f"{name} is declared in bundle.resources but missing at {path}"
        assert path.stat().st_size > 0, f"{name} is empty"


def test_every_non_os_import_of_the_built_exe_is_actually_shipped():
    """The guard that generalises.

    Derived from the binary's import table, so a native dependency added later that needs
    shipping fails here instead of shipping an app that cannot start. Skips when no build
    output is present.
    """
    exe = _built_exe()
    if exe is None:
        pytest.skip("no built determinex.exe; run the Tauri build to exercise this")

    needed = must_ship(pe_imports(exe))
    shipped = {Path(r).name.lower() for r in _resources()}
    missing = sorted(needed - shipped)
    assert not missing, (
        f"{exe.name} imports {missing}, which Windows does not provide and bundle.resources "
        f"does not ship. A clean-host install will fail to launch with 0xC0000135. Either add "
        f"the file to bundle.resources or, if Windows really does provide it, add it to "
        f"OS_PROVIDED in this test with a note."
    )


def _wix_fragments() -> list[Path]:
    """WiX fragment files this config actually ships, or an empty list.

    Both callers used to loop over `wix.get("fragmentPaths", [])` directly, and the CRT app-local
    fix removed the only fragment (windows/vc_redist.wxs) -- so `fragmentPaths` is now ABSENT and
    both loops iterated zero times. Two tests named "no MSI custom action tries to nest an installer"
    and "no fragment comment contains a double hyphen" therefore reported PASSED having examined no
    files at all, which is precisely the "green means verified" claim this suite exists to refuse.
    Callers now skip instead, so "nothing to check" is visible rather than indistinguishable from
    "checked and clean". Found 2026-07-30 by scanning for tests whose every assertion sits inside a
    loop over a dynamic iterable with no emptiness guard.
    """
    wix = _config().get("bundle", {}).get("windows", {}).get("wix", {})
    return [TAURI_DIR / rel for rel in wix.get("fragmentPaths", []) or []]


def test_no_msi_custom_action_tries_to_nest_an_installer():
    """A nested install cannot work, and its failure is invisible.

    The previous design ran vc_redist.x64.exe from a deferred CustomAction inside our own MSI
    transaction. Windows Installer allows one install at a time, so it returned 1618
    (ERROR_INSTALL_ALREADY_RUNNING) every time, and Return="ignore" translated that to
    success. Nothing in the build output or the MSI hinted at it. If a nested installer is
    ever genuinely needed it belongs in a Burn bootstrapper wrapping the MSI, not here.
    """
    fragments = [p for p in _wix_fragments() if p.is_file()]
    if not fragments:
        pytest.skip("this config ships no WiX fragments, so there is no CustomAction to check")
    for path in fragments:
        xml = path.read_text(encoding="utf-8")
        for command in re.findall(r'ExeCommand="([^"]+)"', xml):
            assert not re.search(r"\.(exe|msi)\b[^\"]*?/(install|quiet|passive)", command, re.I), (
                f"{path.name} runs an installer from a CustomAction: {command!r}. Inside an "
                f"MSI transaction that returns 1618 and is silently ignored."
            )


def test_no_fragment_comment_contains_a_double_hyphen():
    """Costs a millisecond, saves an eight-minute build.

    XML forbids `--` inside a comment and candle rejects the ENTIRE source file with CNDL0104.
    Tauri swallows candle's stderr, so the failure surfaces only as "failed to run candle.exe"
    with no reason given. This bit once already.
    """
    fragments = [p for p in _wix_fragments() if p.is_file()]
    if not fragments:
        pytest.skip("this config ships no WiX fragments, so there is no comment to check")
    for path in fragments:
        for match in re.finditer(r"<!--(.*?)-->", path.read_text(encoding="utf-8"), re.DOTALL):
            assert "--" not in match.group(1), (
                f"{path.name} has a comment containing '--': invalid XML, and candle will "
                f"reject the whole file with CNDL0104 without Tauri showing you why"
            )


def test_first_run_setup_registers_the_model_ids_the_router_will_actually_route_to():
    """A cross-language drift guard.

    `bootstrap.rs` decides which Ollama tags a fresh install registers; the Python router
    decides which ids it is willing to route to. Nothing connected the two, and they had
    drifted: bootstrap.rs pinned determinex-engineer-v10-dsl / -observer-v5-dsl / -sentinel-v3,
    and the first two are listed in the router's STALE_MODEL_IDS. So first-run setup registered
    precisely the tags the router refuses, returning ROUTE_BLOCKED_STALE_MODEL_ID. Setup
    reported success and the machine still could not work.

    Imported from the router rather than restated, because a copied list is what drifts.
    """
    from scripts.models.model_router import CURRENT_MODEL_IDS, STALE_MODEL_IDS

    src = (TAURI_DIR / "src" / "bootstrap.rs").read_text(encoding="utf-8")
    tags = set(re.findall(r'const (?:ENGINEER|OBSERVER|SENTINEL)_TAG: &str = "([^"]+)"', src))

    assert len(tags) == 3, f"expected three role tags in bootstrap.rs, found {sorted(tags)}"
    stale = tags & set(STALE_MODEL_IDS)
    assert not stale, (
        f"bootstrap.rs registers superseded model id(s) {sorted(stale)}; the router blocks "
        f"these with ROUTE_BLOCKED_STALE_MODEL_ID, so first-run setup would succeed and the "
        f"install would still be unable to route work"
    )
    assert tags == set(CURRENT_MODEL_IDS), (
        f"bootstrap.rs tags {sorted(tags)} != router CURRENT_MODEL_IDS {sorted(CURRENT_MODEL_IDS)}"
    )


def test_first_run_setup_looks_for_each_gguf_under_its_own_version_directory():
    """The tag and the on-disk path have to move together. Bumping one and not the other gives
    a 'GGUF not found' skip that looks like the user never trained the models."""
    src = (TAURI_DIR / "src" / "bootstrap.rs").read_text(encoding="utf-8")
    paths = re.findall(r'"(versions/[^"]+\.gguf)"', src)
    assert len(paths) == 3, f"expected three GGUF paths, found {paths}"
    for path in paths:
        stem = Path(path).stem
        role_dir, version_dir = path.split("/")[1:3]
        assert stem.endswith(version_dir), (
            f"{path}: file {stem!r} does not match its version directory {version_dir!r}"
        )
        assert role_dir in stem, f"{path}: file {stem!r} is not the {role_dir!r} model"


def test_the_installer_conveys_the_agpl_license_text():
    """AGPL-3.0-or-later requires a copy of the licence to accompany the program.

    The release gate verified only the SOURCE side: that a LICENSE file exists with AGPLv3 text
    and that four metadata files declare AGPL-3.0. Nothing checked the DISTRIBUTED BINARY, and
    it conveyed no licence text whatsoever -- `bundle.resources` shipped none,
    `bundle.licenseFile`, `wix.licensePath` and `nsis.license` were all unset. So a publicly
    distributed installer of an AGPL program carried no licence, while the legal gate reported
    passed.
    """
    resources = _resources()
    assert any(Path(r).name == "LICENSE" for r in resources), (
        "bundle.resources ships no LICENSE; an AGPL binary distribution must convey the licence"
    )
    shipped = TAURI_DIR / "LICENSE"
    assert shipped.is_file(), f"{shipped} is declared in bundle.resources but missing"
    # Bare filename so it lands beside the exe where someone will actually find it, rather than
    # under the _up_\_up_\ path a "../../LICENSE" declaration would produce.
    assert any(r == "LICENSE" for r in resources), (
        "LICENSE must be declared as a bare filename so it installs next to the executable"
    )


def test_every_shipped_license_copy_matches_the_repository_license():
    """Copies exist because each packaging tool resolves paths relative to its own directory:
    Tauri from src-tauri/, vsce from the extension directory. Several copies of a licence that
    disagree is worse than one, so they are pinned byte-for-byte."""
    root_license = (ROOT / "LICENSE").read_bytes()
    for rel in ("frontend/src-tauri/LICENSE", "frontend/vscode-extension/LICENSE"):
        path = ROOT / rel
        assert path.is_file(), f"{rel} is missing; that artifact would convey no licence"
        assert path.read_bytes() == root_license, (
            f"{rel} differs from the repository LICENSE; re-copy it so the distributed licence "
            f"matches the one the project actually publishes"
        )


def test_the_vscode_extension_conveys_a_license_and_names_a_real_repository():
    """Second distributable, same gap. The built determinex-0.1.0.vsix contained exactly five
    entries -- manifest, content types, readme, package.json, extension.js -- and no licence, so
    the extension for an AGPL project conveyed none. vsce includes a LICENSE file automatically
    when one sits in the extension directory, and there was none.

    `repository` was also absent, which leaves the marketplace/Open VSX listing with no link back
    to the source and makes `vsce package` warn.
    """
    pkg = json.loads(
        (ROOT / "frontend" / "vscode-extension" / "package.json").read_text(encoding="utf-8")
    )
    assert (ROOT / "frontend" / "vscode-extension" / "LICENSE").is_file(), (
        "no LICENSE in the extension directory, so vsce will not include one in the .vsix"
    )
    assert str(pkg.get("license", "")).startswith("AGPL-3.0"), pkg.get("license")

    repository = pkg.get("repository")
    url = repository.get("url") if isinstance(repository, dict) else str(repository or "")
    assert url, "extension package.json declares no repository"
    assert "determinex/determinex" not in url, (
        f"repository points at the nonexistent determinex/determinex org: {url}"
    )
    assert "github.com" in url, url


def test_shipped_crate_metadata_does_not_point_at_a_nonexistent_repository():
    """`repository` was https://github.com/determinex/determinex, which does not exist -- `gh repo
    view` answers "Could not resolve to a Repository". It ships in the crate metadata of a public
    release, i.e. it was a dead link in the field people click."""
    cargo = (TAURI_DIR / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^repository\s*=\s*"([^"]+)"', cargo, re.MULTILINE)
    assert match, "Cargo.toml declares no repository"
    url = match.group(1)
    assert "determinex/determinex" not in url, (
        f"repository points at the nonexistent determinex/determinex org: {url}"
    )
    assert url.startswith("https://github.com/"), url


def test_the_app_can_update_itself():
    """Added 2026-07-29. There was no update path of any kind.

    Pushing a fix rebuilt the download artifacts but never touched an installed app, so a user
    stayed on the version they first installed until they manually re-ran an installer. That
    property is one-way: a build shipped WITHOUT the updater can never learn to update itself,
    so the first published cohort would have been on manual reinstalls permanently. Hence this
    has to hold for the FIRST public build, not a later one.

    Every piece is checked because missing any ONE of them yields a build that looks fine and
    silently never updates: no plugin, no registration, no public key (so signatures cannot be
    verified), no endpoint (so nothing is checked), or no updater artifacts (so there is
    nothing to serve).
    """
    cargo = (TAURI_DIR / "Cargo.toml").read_text(encoding="utf-8")
    assert "tauri-plugin-updater" in cargo, "updater plugin is not a dependency"

    lib = (TAURI_DIR / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "tauri_plugin_updater" in lib, "updater plugin is never registered on the app"

    config = _config()
    updater = config.get("plugins", {}).get("updater", {})
    pubkey = str(updater.get("pubkey") or "")
    assert pubkey.strip(), (
        "plugins.updater.pubkey is empty; without it the app cannot verify an update signature "
        "and every update is rejected"
    )
    endpoints = updater.get("endpoints") or []
    assert endpoints, "plugins.updater.endpoints is empty; nothing would ever be checked"
    for endpoint in endpoints:
        assert endpoint.startswith("https://"), f"update endpoint must be https: {endpoint}"

    assert config.get("bundle", {}).get("createUpdaterArtifacts") is True, (
        "createUpdaterArtifacts is off, so the build emits no signed update archive and the "
        "endpoint above would have nothing to serve"
    )

    caps = json.loads((TAURI_DIR / "capabilities" / "default.json").read_text(encoding="utf-8"))
    permissions = caps.get("permissions", [])
    assert any("updater" in p for p in permissions), (
        "no updater permission in the default capability; the frontend check() call would be "
        "denied at runtime"
    )
    assert any("process" in p for p in permissions), (
        "no process permission; the app could install an update but not relaunch into it"
    )


def test_the_updater_public_key_is_a_well_formed_minisign_key():
    """A truncated or mangled key is not a loud failure -- signature verification just refuses
    every update forever, which presents as "updates never work" with nothing in a log to
    explain it. The structure is cheap to check: base64 of a comment line plus a key line whose
    payload is 2 bytes of algorithm id + 8 bytes of key id + a 32-byte ed25519 key.
    """
    import base64
    import binascii

    pubkey = _config()["plugins"]["updater"]["pubkey"]
    try:
        raw = base64.b64decode(pubkey, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise AssertionError(f"updater pubkey is not valid base64 of text: {exc}") from exc

    lines = [line for line in raw.strip().splitlines() if line.strip()]
    assert len(lines) >= 2, f"expected a comment line and a key line, got {lines}"
    key_bytes = base64.b64decode(lines[-1], validate=True)
    assert len(key_bytes) == 42, (
        f"minisign public key payload is {len(key_bytes)} bytes, expected 42; this key cannot "
        f"verify any update signature"
    )
    assert key_bytes[:2] == b"Ed", (
        f"unexpected signature algorithm {key_bytes[:2]!r}; tauri's updater expects ed25519"
    )


def test_release_ci_supplies_the_updater_signing_key():
    """createUpdaterArtifacts makes signing mandatory. If CI has no key the release build fails
    outright, which is the correct outcome but only helpful if the secret is actually wired."""
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "TAURI_SIGNING_PRIVATE_KEY" in workflow, (
        "release.yml does not pass TAURI_SIGNING_PRIVATE_KEY, so a tagged release cannot "
        "produce a signed update artifact"
    )


def test_the_setup_wizard_does_not_claim_to_register_models_it_cannot_obtain():
    """The wizard announced "Registering Determinex model swarm with Ollama..." over a call
    that pulls base qwen models and registers the fine-tuned models only if their GGUFs already
    happen to be on disk. On a fresh machine they never are, so it claimed work it had not
    done and the install reached "System Ready" unable to route to two of four roles."""
    wizard = (ROOT / "frontend" / "src" / "components" / "SetupWizard.tsx").read_text(
        encoding="utf-8"
    )
    assert 'setInstallPhase("Registering Determinex model swarm with Ollama...")' not in wizard, (
        "the wizard is announcing model-swarm registration again over a call that does not do it"
    )
    # And it must actually offer the real path.
    assert "check_determinex_models" in wizard, "the wizard never probes model coverage"
    assert "install_determinex_models" in wizard, (
        "the wizard reports missing models but offers no way to get them"
    )


def _built_msis() -> list[Path]:
    found: list[Path] = []
    for base in (
        Path("T:/determinex-target/release/bundle/msi"),
        TAURI_DIR / "target" / "release" / "bundle" / "msi",
        ROOT / ".tmp" / "determinex-download-bundles" / "installers",
    ):
        if base.is_dir():
            found.extend(sorted(base.glob("*.msi")))
    return found


def test_a_built_msi_has_a_signed_update_artifact_beside_it():
    """Configuration being right does not prove the bundler signed anything.

    An installed app rejects an update whose signature does not verify against the embedded public
    key, so a missing `.sig` means the update endpoint serves something every client refuses --
    silently, from the user's point of view. Skips when nothing is built.

    WHAT V2 ACTUALLY EMITS (corrected 2026-07-30, after this went green for the first time)
    ---------------------------------------------------------------------------------------
    This test used to demand a `*.zip` as well, and stayed red for days partly because of it. With
    `createUpdaterArtifacts: true` the Windows artifact is the **installer itself plus a detached
    `.sig`** -- no archive. The zip belongs to the legacy `"v1Compatible"` mode, which the config
    schema describes as "Generates legacy zipped v1 compatible updaters", and the plugin's
    `install_inner` accepts either (`if infer::archive::is_zip(bytes)`), which is why a doc comment
    listing `.msi.zip` misled the original version of this check.

    So the requirement is the `.sig`, and demanding a zip asserted a shape this configuration is not
    supposed to produce -- a test failing for a reason unrelated to the real defect, which is worse
    than no test because it hides the moment the real defect is fixed.
    """
    msis = _built_msis()
    if not msis:
        pytest.skip("no built MSI on disk; run the Tauri build to exercise this")

    # Only check alongside a real bundler output directory. The staged download-bundle copy
    # deliberately carries installers only.
    bundle_msis = [m for m in msis if m.parent.name == "msi"]
    if not bundle_msis:
        pytest.skip("no bundler msi/ output directory present")

    for msi in bundle_msis:
        # Per-installer, not per-directory: a `.sig` for some *other* file in the same folder must
        # not satisfy the check for this one.
        sig = msi.with_name(msi.name + ".sig")
        assert sig.is_file(), (
            f"no {sig.name} beside {msi.name}. The bundler silently skips updater generation when "
            f"TAURI_SIGNING_PRIVATE_KEY_PASSWORD is undefined -- and on Windows an EMPTY password "
            f"cannot be defined at all, so a passwordless updater key can never be signed with. "
            f"See docs/release/UPDATER_ARTIFACTS.md."
        )
        assert sig.stat().st_size > 0, f"{sig.name} is empty"

        # A minisign signature is base64 with an 'untrusted comment:' header. Checking the shape
        # catches a truncated or placeholder file, which an existence check alone would pass.
        decoded = base64.b64decode(sig.read_text(encoding="utf-8").strip(), validate=False)
        assert decoded.startswith(b"untrusted comment:"), (
            f"{sig.name} does not decode to a minisign signature; an installed build would reject "
            f"the update it accompanies"
        )


def test_a_built_msi_contains_the_agpl_license():
    """Config declaring it is not the same as the artifact carrying it.

    Caught live 2026-07-30: `test_the_installer_conveys_the_agpl_license_text` passed (the config
    declares LICENSE and the file exists on disk) while the built MSI contained no LICENSE at all,
    because the build that produced it started before the resource was added. Config-level and
    artifact-level checks are independent, and for a licence-conveyance obligation the artifact is
    the one that matters.
    """
    msis = _built_msis()
    if not msis:
        pytest.skip("no built MSI on disk; run the Tauri build to exercise this")
    for msi in msis:
        blob = msi.read_bytes()
        assert b"LICENSE" in blob or b"L\x00I\x00C\x00E\x00N\x00S\x00E" in blob, (
            f"{msi.name} ships no LICENSE. AGPL-3.0-or-later requires a copy of the licence to "
            f"accompany the program."
        )


def test_a_built_msi_contains_the_crt_runtime():
    """The check that cannot be faked: read the MSI itself.

    An MSI keeps file names in a string pool, so a raw byte scan is a dependency-free way to
    tell whether a payload survived bundling. Skips when nothing has been built.
    """
    msis = _built_msis()
    if not msis:
        pytest.skip("no built MSI on disk; run the Tauri build to exercise this")

    for msi in msis:
        blob = msi.read_bytes()
        for dll in ("vcruntime140.dll", "msvcp140.dll", "msvcp140_1.dll"):
            present = (
                dll.encode("ascii") in blob
                or dll.encode("utf-16-le") in blob
                or dll.upper().encode("ascii") in blob
            )
            assert present, (
                f"{msi.name} does not contain {dll}. The installed app will fail to start on "
                f"a clean host with 0xC0000135 (STATUS_DLL_NOT_FOUND)."
            )


# ── The staged bundle must BE the build you verified ─────────────────────────────────────────────

_BUNDLER_DIRS = (
    Path("T:/determinex-target/release/bundle"),
    TAURI_DIR / "target" / "release" / "bundle",
)
_STAGED_DIR = ROOT / ".tmp" / "determinex-download-bundles" / "installers"


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundler_artifact(name: str) -> Path | None:
    for base in _BUNDLER_DIRS:
        for sub in ("msi", "nsis"):
            candidate = base / sub / name
            if candidate.is_file():
                return candidate
    return None


def _staged_installer_dir() -> Path | None:
    """Where the CURRENT download manifest says its installers live.

    This used to be a hardcoded `.tmp/determinex-download-bundles/installers`. That path is a
    leftover from an older staging convention: `package_download_bundle.py` writes a TIMESTAMPED
    bundle directory and records it as `bundle_dir` in the manifest, and it does not refresh the
    flat one. So the flat directory silently kept a build from a previous day -- measured
    2026-07-31, it held the Jul 30 installers (`d1f369ef…`) while the current build was
    `2942b161…`, and this test reported a mismatch that was entirely its own stale lookup.

    Following the manifest is the same rule the release gates use
    (`determinex_release_gates.newest_download_manifest_path`), so the test now anchors on the
    artifacts the gates actually attest to rather than on a directory nobody writes any more.
    """
    try:
        from scripts.release import determinex_release_gates
    except Exception:
        determinex_release_gates = None  # type: ignore[assignment]

    if determinex_release_gates is not None:
        manifest_path = determinex_release_gates.newest_download_manifest_path(ROOT)
        if manifest_path is not None:
            import json

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
            bundle_dir = str(manifest.get("bundle_dir") or "").strip()
            if bundle_dir:
                candidate = Path(bundle_dir)
                if not candidate.is_absolute():
                    candidate = ROOT / candidate
                installers = candidate / "installers"
                if installers.is_dir():
                    return installers

    # Fall back to the newest timestamped bundle on disk, then the legacy flat directory, so a
    # checkout without a manifest still gets a meaningful comparison instead of a silent skip.
    root = ROOT / ".tmp" / "determinex-download-bundles"
    if root.is_dir():
        timestamped = sorted(
            (p for p in root.glob("determinex-*/installers") if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if timestamped:
            return timestamped[0]
    return _STAGED_DIR if _STAGED_DIR.is_dir() else None


def test_the_staged_installers_are_the_current_build():
    """Publishing a staged artifact that is not the build you just made ships the wrong thing.

    WHY THIS EXISTS
    ---------------
    Found live 2026-07-30. The updater fix replaced the signing keypair, so `plugins.updater.pubkey`
    changed and the app was rebuilt -- the public key is compiled INTO the binary. The staged bundle
    under .tmp/determinex-download-bundles/installers was not re-staged, so it still held installers
    carrying the OLD pubkey.

    Every release gate was green, because gate freshness anchors on the staged artifacts' own mtimes
    and those had not moved. But the staged installers can never accept an update signed with the new
    key, and the freshly built ones have no clean-host verification. So there was, at that moment, no
    publishable artifact set -- and nothing said so.

    Verified at the time: the fresh `determinex.exe` contains the new pubkey and not the old one, and
    both staged installers differ by sha256 from the freshly built ones.

    Deliberately not "fixed" by re-staging. Re-staging is correct but it moves the freshness anchor and
    invalidates real clean-host evidence that cost a VM run, so the two have to be sequenced together
    by whoever can do the VM run. This test exists to stop that being forgotten.

    Skips when there is no bundler output to compare against, since a clean checkout has none.
    """
    staged_dir = _staged_installer_dir()
    if staged_dir is None:
        pytest.skip("no staged download bundle on disk")
    staged = sorted(p for p in staged_dir.iterdir() if p.suffix.lower() in {".msi", ".exe"})
    if not staged:
        pytest.skip("staged bundle contains no Windows installers")

    compared = 0
    mismatched: list[str] = []
    for artifact in staged:
        built = _bundler_artifact(artifact.name)
        if built is None:
            continue
        compared += 1
        if _sha256(artifact) != _sha256(built):
            mismatched.append(artifact.name)

    if not compared:
        pytest.skip("no bundler output for the staged installers; nothing to compare")

    assert not mismatched, (
        f"{mismatched} in the staged download bundle differ from the freshly built installers, so the "
        f"bundle the gates attest to is NOT the build that would ship. This happened for real when the "
        f"updater keypair changed: the staged installers embedded the previous public key and could "
        f"never have accepted an update. Re-stage with package_download_bundle.py AND re-run the "
        f"clean-host verification together — re-staging alone moves the freshness anchor and "
        f"invalidates the existing clean-host evidence."
    )
