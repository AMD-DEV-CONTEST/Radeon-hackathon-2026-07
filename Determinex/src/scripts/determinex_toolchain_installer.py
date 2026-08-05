#!/usr/bin/env python3
"""
determinex_toolchain_installer.py -- opt-in "enable this toolchain" flow
=======================================================================
The oracle pool (determinex_oracle.py) never lies about what's missing --
Oracle.available() + OracleUnavailable's install_hint tell you exactly what
to install. This module is the other half Ryan asked for: "toolchains...
should be added for the user if the user asks for it, like an
enablization" -- an explicit, user-triggered action that actually runs the
install, then RE-CHECKS the real oracle (never trusts the installer's own
exit code as proof) so the reported result is ground truth, not a guess.

Determinex does NOT vendor every language toolchain inside the app itself
(gcc/rustc/cobc/... would be gigabytes, licensing-entangled, and platform-
specific) -- exactly like any other polyglot IDE, it finds or fetches the
user's own toolchain instead of shipping one per language. What Determinex
DOES ship self-contained is its own product's toolchain (the bundled Python
engine + the Tauri-packaged desktop binary, which needs no per-language
oracle to run at all) -- this module is only for the OPTIONAL,
per-target-language oracle toolchains a user opts into.

    python scripts/determinex_toolchain_installer.py install cobol
    python scripts/determinex_toolchain_installer.py list
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from determinex_oracle import get_oracle  # noqa: E402


@dataclass
class ToolchainInstallResult:
    language: str
    already_available: bool  # was it available BEFORE we tried
    attempted: bool  # did we actually run an installer
    installer: str  # "winget" | "portable-zip" | "choco" | ""
    command: str  # the exact command(s) run, for transparency
    succeeded: bool  # re-checked oracle.available() AFTER install -- never trusted blindly
    output: str = ""
    notes: list = field(default_factory=list)


# Best-effort winget package IDs for the optional per-language oracle
# toolchains. Windows-first (this box); winget is preferred over choco
# because it rarely needs admin elevation. IDs marked "(verified live)"
# were confirmed present via `winget search`/`winget install`, or were
# already installed on this development machine, during the 2026-07-22
# session that built this module -- others are the standard published
# package ID for that toolchain, unverified on this particular box.
_WINGET_IDS: dict[str, str] = {
    "c": "BrechtSanders.WinLibs.POSIX.UCRT",  # verified live: already on this box's PATH
    "cpp": "BrechtSanders.WinLibs.POSIX.UCRT",  # same MinGW toolchain provides g++
    "rust": "Rustlang.Rustup",
    "go": "GoLang.Go",
    "jvm": "EclipseAdoptium.Temurin.21.JDK",
    "swift": "Swift.Toolchain",
    "csharp": "Microsoft.DotNet.SDK.8",
    "dotnet": "Microsoft.DotNet.SDK.8",
    "ruby": "RubyInstallerTeam.Ruby.3.3",
    "php": "PHP.PHP.8.3",
    "basic": "FreeBASIC.FreeBASIC",  # verified live: installed this session
    "duckdb": "DuckDB.cli",  # verified live: installed this session
    "riscv-et-soc1": "Docker.DockerDesktop",
    "et-soc1": "Docker.DockerDesktop",
    "erbium": "Docker.DockerDesktop",
    # mariadb/mongodb oracles are Docker-backed (ephemeral container per verify
    # run, no local service) -- Docker Desktop is the only real dependency,
    # already covered by the riscv-et-soc1/et-soc1/erbium entry above.
}
# Packages installed off C: (per-language override of winget's default
# install location) -- Ryan: "put what you need on T to save for now on
# space". Only languages with a real, confirmed-working --location flag are
# listed here; most winget packages (MSI-backed installers especially)
# don't support relocation and are left on their default drive. FreeBASIC
# (basic) is deliberately NOT here -- it was already installed to its
# default location (C:\Program Files (x86)\FreeBASIC) earlier this same
# session, before this T:-drive convention was set; redirecting it now
# would just create a second, conflicting copy.
_WINGET_LOCATIONS: dict[str, str] = {
    "duckdb": "T:/determinex-tools/duckdb",
}
# tauri needs BOTH cargo (rust) and node -- installed as a pair, not one ID.
_WINGET_ID_LISTS: dict[str, list[str]] = {
    "tauri": ["Rustlang.Rustup", "OpenJS.NodeJS.LTS"],
}
# GnuCOBOL has no winget package; Chocolatey ships it, but Chocolatey's own
# machine-wide lib directory needs admin write access -- confirmed live
# this session (`Access to the path 'C:\\ProgramData\\chocolatey\\lib-bad'
# is denied`) on a non-elevated shell. Kept as a fallback mapping (checked
# only if _PORTABLE_ZIP has no entry for the language, or gets one removed
# later) so install_toolchain() still reports the failure honestly (a
# needs_admin note) instead of silently failing -- same "never lie" contract
# as the oracles. cobol's entry here is currently shadowed by _PORTABLE_ZIP
# below, which needs no admin at all.
_CHOCO_IDS: dict[str, str] = {
    "cobol": "gnucobol",
}

# Portable (no-installer) archives, tried BEFORE choco -- no admin needed at
# all, unlike Chocolatey's machine-wide lib directory. GnuCOBOL's canonical
# community-maintained Windows binaries (linked directly from the official
# GnuCOBOL/SourceForge project pages) ship this way: a 7-Zip archive you
# extract anywhere, no installer, no elevation.
#
# Confirmed live 2026-07-25: extracting this to T:/determinex-tools/gnucobol
# and putting bin/ on PATH was NOT enough -- cobc failed with
# "configuration error: /mingw64/share/gnucobol/config\\default.conf: No
# such file or directory". Root cause: this build assumes it's launched from
# an MSYS2 shell that already sourced the bundled set_env.cmd, which sets
# COB_CONFIG_DIR/COB_COPY_DIR/COB_LIBRARY_PATH/LOCALEDIR relative to its own
# install dir; a bare PATH entry only gets you the binary, not a working
# compiler. Fixed by persisting those same vars (see env_subdirs below)
# as User environment variables pointing at the portable install's own
# config/copy/extras/locale siblings -- re-verified with a real .cob file
# compiling clean after the fix, failing with the exact error above before it.
_PORTABLE_ZIP: dict[str, dict] = {
    "cobol": {
        "url": "https://www.arnoldtrembley.com/GC32M-BDB-x64.7z",
        "install_dir": "T:/determinex-tools/gnucobol",
        "probe_relpath": "bin/cobc.exe",
        "env_subdirs": {
            "COB_CONFIG_DIR": "config",
            "COB_COPY_DIR": "copy",
            "COB_LIBRARY_PATH": "extras",
            "LOCALEDIR": "locale",
        },
    },
}


def _persist_user_env_var(name: str, value: str) -> None:
    """Persist a User-scope environment variable via the registry (not `setx`,
    which silently truncates PATH-like values over 1024 chars and does NOT
    expand %VAR% references the way a naive `setx PATH %PATH%;x` call might
    imply) and broadcast WM_SETTINGCHANGE so freshly-started processes pick
    it up without a reboot -- existing shells still won't see it, same
    documented caveat as every other PATH-touching install in this module."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)
    import ctypes

    HWND_BROADCAST, WM_SETTINGCHANGE = 0xFFFF, 0x1A
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
    )


def _append_user_path(new_dir: str) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            current, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""
    if new_dir.lower() in current.lower():
        return
    updated = f"{current};{new_dir}" if current else new_dir
    _persist_user_env_var("Path", updated)


def _install_portable_zip(spec: dict, timeout: int = 600) -> str:
    """Download + extract a portable (no-installer, no-admin) archive with
    7-Zip, put its binary on PATH, and persist whatever sibling env vars
    (see env_subdirs) the toolchain needs to actually run -- being on PATH
    is necessary but, for GnuCOBOL's MinGW build, not sufficient."""
    install_dir = Path(spec["install_dir"])
    install_dir.mkdir(parents=True, exist_ok=True)
    archive_path = install_dir / spec["url"].rsplit("/", 1)[-1]
    urllib.request.urlretrieve(spec["url"], archive_path)  # noqa: S310 -- fixed, hardcoded URL

    seven_zip = Path("C:/Program Files/7-Zip/7z.exe")
    output = ""
    if not seven_zip.exists():
        output += _winget_install("7zip.7zip")
    cp = subprocess.run(
        [str(seven_zip), "x", str(archive_path), f"-o{install_dir}", "-y"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output += cp.stdout + cp.stderr

    probe = install_dir / spec["probe_relpath"]
    if probe.exists():
        _append_user_path(str(probe.parent))
        main_dir = probe.parent.parent
        for var, subdir in spec.get("env_subdirs", {}).items():
            full = main_dir / subdir
            if full.exists():
                _persist_user_env_var(var, str(full))
    return output


def _winget_install(pkg_id: str, location: str | None = None, timeout: int = 600) -> str:
    cmd = [
        "winget",
        "install",
        "--id",
        pkg_id,
        "-e",
        "--accept-source-agreements",
        "--accept-package-agreements",
    ]
    if location:
        cmd += ["--location", location]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return cp.stdout + cp.stderr


def install_toolchain(language: str) -> ToolchainInstallResult:
    """Best-effort, ground-truth-checked toolchain install for one oracle
    language. Never reports succeeded=True on the installer's exit code
    alone -- always re-runs the real Oracle.available() probe afterward,
    since a PATH change frequently doesn't take effect in the CURRENT
    process/shell even when the install itself worked."""
    oracle = get_oracle(
        language
    )  # raises KeyError for an unknown language -- same as every other caller
    was_available = oracle.available()
    if was_available:
        return ToolchainInstallResult(
            language, True, False, "", "", True, notes=["already available -- nothing to install"]
        )

    if platform.system() != "Windows":
        return ToolchainInstallResult(
            language,
            False,
            False,
            "",
            "",
            False,
            notes=[
                f"no installer wired for platform {platform.system()!r} yet -- "
                f"install manually: {oracle.install_hint}"
            ],
        )

    ids = _WINGET_ID_LISTS.get(language) or (
        [_WINGET_IDS[language]] if language in _WINGET_IDS else []
    )
    if ids:
        location = _WINGET_LOCATIONS.get(language)
        output = "\n".join(_winget_install(pkg_id, location=location) for pkg_id in ids)
        now_available = get_oracle(language).available()
        notes = (
            []
            if now_available
            else [
                "installer ran but the toolchain still isn't resolvable on PATH in this "
                "process -- a NEW terminal/session is usually required for a PATH change "
                "to take effect; re-check after restarting the app/shell"
            ]
        )
        return ToolchainInstallResult(
            language,
            False,
            True,
            "winget",
            " && ".join(f"winget install --id {i} -e" for i in ids),
            now_available,
            output[-4000:],
            notes,
        )

    zip_spec = _PORTABLE_ZIP.get(language)
    if zip_spec:
        output = _install_portable_zip(zip_spec)
        now_available = get_oracle(language).available()
        notes = (
            []
            if now_available
            else [
                "portable archive extracted but the toolchain still isn't resolvable "
                "on PATH in this process -- a NEW terminal/session is usually required "
                "for a PATH/env-var change to take effect; re-check after restarting "
                "the app/shell"
            ]
        )
        return ToolchainInstallResult(
            language,
            False,
            True,
            "portable-zip",
            f"extract {zip_spec['url']}",
            now_available,
            output[-4000:],
            notes,
        )

    choco_id = _CHOCO_IDS.get(language)
    if choco_id:
        cmd = ["choco", "install", choco_id, "-y"]
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out = cp.stdout + cp.stderr
        needs_admin = "Access to the path" in out and "denied" in out
        now_available = get_oracle(language).available()
        notes = []
        if needs_admin:
            notes.append(
                f"needs an elevated (Run as Administrator) terminal -- Chocolatey requires "
                f"admin write access to its machine-wide lib directory; re-run "
                f"`choco install {choco_id} -y` from an admin PowerShell"
            )
        return ToolchainInstallResult(
            language, False, True, "choco", " ".join(cmd), now_available, out[-4000:], notes
        )

    return ToolchainInstallResult(
        language,
        False,
        False,
        "",
        "",
        False,
        notes=[
            f"no installer mapping for {language!r} yet -- install manually: {oracle.install_hint}"
        ],
    )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex oracle toolchain enablement")
    sub = ap.add_subparsers(dest="cmd", required=True)
    inst = sub.add_parser("install", help="install the toolchain for one oracle language")
    inst.add_argument("language")
    sub.add_parser("list", help="show available()/unavailable() for every registered oracle")
    args = ap.parse_args()

    if args.cmd == "list":
        from determinex_oracle import available_oracles

        print(json.dumps(available_oracles(), indent=2))
        return 0

    r = install_toolchain(args.language)
    print(json.dumps(asdict(r), indent=2))
    return 0 if r.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
