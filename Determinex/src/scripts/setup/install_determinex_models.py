#!/usr/bin/env python3
"""Download the Determinex fine-tuned models and register them with Ollama.

WHY THIS EXISTS
---------------
Until 2026-07-29 a new user could not reach a working state, and this was the missing link.

`roles.rs` defaults a fresh install's builder and monitor to `determinex/engineer` and
`determinex/observer`, which resolve to `determinex-engineer-v11-dsl` and
`determinex-observer-v6-dsl`. Nothing could obtain them:

  * `model_puller.rs` pulls only the public qwen base models, and its comment pointed at
    GitHub Releases that hold no model GGUF (checked: rosetta-v1 has family_*.pt bridge
    weights, v0.1.0-clean-host-test has an MSI).
  * The HuggingFace repos holding the real weights were PRIVATE -- every README link 401'd.
  * `register_models.ps1` registers from disk and says "run the RunPod training pipeline
    first" if the GGUF is absent. There was no download step anywhere.
  * The shipped Modelfiles cannot bootstrap: `Modelfile.engineer` reads
    `FROM determinex-engineer-v11-dsl`, deriving from the model it would create.

So `work-readiness` reported "Missing local model coverage for 2 roles" and
`specGenerationBlockMessage` blocked spec generation, with no in-app path forward.

The repos are public as of 2026-07-29 (verified anonymously: HTTP 200 on the API, 206 on a
ranged GGUF fetch). This script closes the remaining gap: fetch, verify, register.

Usage::

    python scripts/setup/install_determinex_models.py --check      # what is missing
    python scripts/setup/install_determinex_models.py --dry-run    # plan, no downloads
    python scripts/setup/install_determinex_models.py              # do it
    python scripts/setup/install_determinex_models.py --role builder

Downloads resume, so an interrupted 7.7 GB fetch does not start over. Registration is
idempotent -- a model already in `ollama list` is skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HF_OWNER = "darthceltic85"


@dataclass(frozen=True)
class ModelSpec:
    role: str
    tag: str
    repo: str
    gguf: str
    num_ctx: int
    note: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{HF_OWNER}/{self.repo}/resolve/main/{self.gguf}"

    @property
    def api_url(self) -> str:
        return f"https://huggingface.co/api/models/{HF_OWNER}/{self.repo}"


# Tags must match model_router.CURRENT_MODEL_IDS and hive/ctx_config.py's role defaults, or
# a successful install still leaves the roles unsatisfied. tests/ pins that alignment.
MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        role="builder",
        tag="determinex-engineer-v11-dsl",
        repo="determinex-engineer",
        gguf="determinex-engineer-v11-dsl.gguf",
        num_ctx=4096,
        note="C1 Engineer, 1.5B Qwen2.5-Coder, DSL v11",
    ),
    ModelSpec(
        role="monitor",
        tag="determinex-observer-v6-dsl",
        repo="determinex-observer-llama-3.2",
        gguf="determinex-observer-v6-dsl.gguf",
        num_ctx=4096,
        note="C3 Observer, 3B Llama-3.2, DSL v6",
    ),
    ModelSpec(
        role="architect",
        tag="determinex-sentinel-v5-dsl",
        repo="determinex-sentinel",
        gguf="determinex-sentinel-v5-dsl.gguf",
        num_ctx=4096,
        note="C7 Sentinel, 7B Mistral, DSL v5",
    ),
)


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a command, decoding output as UTF-8 regardless of the console codepage.

    `text=True` alone decodes with the locale encoding, which on Windows is cp1252. Ollama
    emits progress with non-ASCII box/spinner characters, so this raised

        UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 641

    during a real `ollama create` -- observed 2026-07-29 on the end-to-end test. The command
    itself had succeeded; the crash was purely in decoding its output, which is the worst
    kind of failure to hand a user mid-install. errors="replace" means a stray byte degrades
    one character instead of aborting a 12 GB provisioning run.
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def ollama_available() -> bool:
    return shutil.which("ollama") is not None


def installed_tags() -> set[str]:
    """Tags already in Ollama. Empty set when Ollama is unreachable."""
    if not ollama_available():
        return set()
    try:
        proc = _run(["ollama", "list"])
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if proc.returncode != 0:
        return set()
    tags = set()
    for line in proc.stdout.splitlines()[1:]:
        name = line.split()[0] if line.split() else ""
        if name:
            tags.add(name.split(":")[0])
            tags.add(name)
    return tags


def remote_sha256(spec: ModelSpec) -> str | None:
    """The LFS sha256 HuggingFace records for the GGUF, or None if it cannot be obtained.

    Used to verify a multi-gigabyte download arrived intact. A truncated GGUF fails inside
    `ollama create` with a parse error that reads like a corrupt model rather than a bad
    transfer, which is a confusing place to land after a 7.7 GB wait.

    THE BUG THIS FIXES (2026-07-29, in my own first version). This queried
    /api/models/<repo> and looked for `lfs` on the sibling entry. That endpoint does NOT
    include lfs data -- siblings carry only `rfilename` -- so it always returned None and
    `verify()` fell through to its "no published checksum, skipping" branch. The check was a
    no-op on every real download, which is precisely the silently-passing guard this
    codebase keeps turning up. Caught by actually running a 1.65 GB download and noticing
    the digest printed as "(none)".

    Two sources, in order:
      1. /api/models/<repo>?blobs=true  -> siblings[].lfs.sha256
      2. the resolve endpoint's X-Linked-ETag header

    NOT the plain `etag` header: for these files that is the xetHash, a different digest
    entirely (verified -- 49c736f8... vs the real cca14e35...), so trusting it would fail
    every comparison and look like universal corruption.
    """
    try:
        with urllib.request.urlopen(f"{spec.api_url}?blobs=true", timeout=30) as resp:
            info = json.load(resp)
        for sibling in info.get("siblings", []):
            if sibling.get("rfilename") == spec.gguf:
                lfs = sibling.get("lfs") or {}
                digest = lfs.get("sha256") or lfs.get("oid")
                if isinstance(digest, str) and len(digest) == 64:
                    return digest
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        pass

    try:
        req = urllib.request.Request(spec.url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            linked = resp.headers.get("X-Linked-ETag") or ""
        digest = linked.strip().strip('"')
        if len(digest) == 64:
            return digest
    except (urllib.error.URLError, OSError):
        pass
    return None


def download(spec: ModelSpec, dest: Path, quiet: bool = False) -> Path:
    """Fetch the GGUF with resume support. Returns the local path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    existing = part.stat().st_size if part.is_file() else 0

    req = urllib.request.Request(spec.url, headers={"User-Agent": "determinex-installer"})
    if existing:
        # Resume: a 7.7 GB fetch that dies at 90% must not start over.
        req.add_header("Range", f"bytes={existing}-")

    with urllib.request.urlopen(req, timeout=60) as resp:
        if existing and resp.status != 206:
            # Server ignored the range; start clean rather than corrupt the file by
            # appending a second copy of the whole body to a partial one.
            existing = 0
            part.unlink(missing_ok=True)
        total = int(resp.headers.get("Content-Length") or 0) + existing
        mode = "ab" if existing else "wb"
        done = existing
        last_pct = -1
        with part.open(mode) as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if not quiet and total:
                    pct = int(done * 100 / total)
                    if pct != last_pct:
                        last_pct = pct
                        print(
                            f"    {spec.tag}: {pct}%  ({done / 1e9:.2f} / {total / 1e9:.2f} GB)",
                            flush=True,
                        )

    part.replace(dest)
    return dest


def verify(path: Path, expected: str | None, quiet: bool = False) -> bool:
    if not expected:
        if not quiet:
            print(f"    no published checksum for {path.name}; skipping verification")
        return True
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got == expected:
        if not quiet:
            print("    sha256 OK")
        return True
    print(f"    sha256 MISMATCH for {path.name}: expected {expected[:16]}..., got {got[:16]}...")
    return False


def register(spec: ModelSpec, gguf: Path, quiet: bool = False) -> bool:
    """`ollama create` from a generated Modelfile.

    Generated rather than using the repo's Modelfile.<role>, because those read
    `FROM determinex-<role>-vN-dsl` -- they are parameter overlays that assume the model
    already exists, so they cannot import a GGUF. Same approach register_models.ps1 takes.
    """
    if not ollama_available():
        print("    ollama not on PATH; cannot register")
        return False
    with tempfile.NamedTemporaryFile(
        "w", suffix=".Modelfile", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(f"FROM {gguf.as_posix()}\n")
        fh.write(f"PARAMETER num_ctx {spec.num_ctx}\n")
        fh.write("PARAMETER temperature 0\n")
        modelfile = Path(fh.name)
    try:
        proc = _run(["ollama", "create", spec.tag, "-f", str(modelfile)], timeout=1800)
    except subprocess.TimeoutExpired:
        print(f"    ollama create timed out for {spec.tag}")
        return False
    finally:
        modelfile.unlink(missing_ok=True)
    if proc.returncode != 0:
        print(f"    ollama create failed: {(proc.stderr or proc.stdout).strip()[:300]}")
        return False
    if not quiet:
        print(f"    registered {spec.tag}")
    return True


def user_data_models_dir() -> Path:
    """A durable per-user location for multi-gigabyte weights."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "Determinex" / "models"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "determinex" / "models"


def models_dir() -> Path:
    configured = os.environ.get("DETERMINEX_MODELS_DIR", "").strip()
    if configured:
        return Path(configured)
    # `.env` exists only in a source checkout. Consulting it is harmless elsewhere.
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("DETERMINEX_MODELS_DIR="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return Path(value)
    # ROOT comes from __file__, and inside the PyInstaller sidecar that is the onefile
    # EXTRACTION directory under %TEMP% -- so this fallback used to put several GB of weights
    # somewhere a temp cleaner or a reboot can remove, and resumable .part files with them.
    # Observed live: the shipped sidecar reported
    # "gguf storage : C:\\Users\\<user>\\AppData\\Local\\Temp\\.determinex-models".
    # A source checkout keeps the repo-local path, which is what developers expect.
    if getattr(sys, "frozen", False):
        return user_data_models_dir()
    return ROOT / ".determinex-models"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--check", action="store_true", help="report what is missing and exit")
    ap.add_argument("--dry-run", action="store_true", help="plan without downloading")
    ap.add_argument(
        "--role",
        choices=[m.role for m in MODELS],
        action="append",
        help="install only these roles (repeatable)",
    )
    ap.add_argument("--dest", type=Path, default=None, help="where to store GGUFs")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    wanted = [m for m in MODELS if not args.role or m.role in args.role]
    present = installed_tags()
    dest_root = args.dest or models_dir()

    print("Determinex model install")
    print(f"  ollama       : {'found' if ollama_available() else 'NOT FOUND on PATH'}")
    print(f"  gguf storage : {dest_root}")
    print()
    missing = [m for m in wanted if m.tag not in present]
    for spec in wanted:
        state = "installed" if spec.tag in present else "MISSING"
        print(f"  [{state:<9}] {spec.role:<9} {spec.tag}   {spec.note}")

    if args.check:
        print()
        print(f"  {len(missing)} of {len(wanted)} missing")
        return 1 if missing else 0

    if not missing:
        print("\nAll requested models are registered; nothing to do.")
        return 0

    if not ollama_available():
        print("\nOllama is required to register models. Install it first: https://ollama.com")
        return 2

    print()
    failures: list[str] = []
    for spec in missing:
        print(f"  {spec.tag}")
        gguf = dest_root / spec.repo / spec.gguf
        if args.dry_run:
            print(f"    would download {spec.url}")
            print(f"    would register from {gguf}")
            continue
        try:
            if gguf.is_file():
                print(f"    already downloaded: {gguf}")
            else:
                print(f"    downloading from {spec.url}")
                download(spec, gguf, quiet=args.quiet)
        except (urllib.error.URLError, OSError) as exc:
            print(f"    download failed: {exc}")
            failures.append(spec.tag)
            continue
        if not verify(gguf, remote_sha256(spec), quiet=args.quiet):
            failures.append(spec.tag)
            continue
        if not register(spec, gguf, quiet=args.quiet):
            failures.append(spec.tag)

    if args.dry_run:
        print("\nDry run complete; nothing was downloaded or registered.")
        return 0

    still_missing = [m.tag for m in wanted if m.tag not in installed_tags()]
    print()
    if still_missing:
        print(f"  STILL MISSING: {', '.join(still_missing)}")
        return 1
    print("  All requested models are registered. Restart Determinex to pick them up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
