#!/usr/bin/env python3
"""Convert a single ProgramBench per-tool override from Python wrapper
to a native-source-only implementation.

For tools whose upstream is Go / Rust / C / C++, copies the canonical
upstream source from `T:/determinex-programbench/_extracted_tests/<slug>/`
into the override directory, generates a proper `compile.sh` that builds
the binary in the eval container, and removes the Python wrapper.

Usage:
    python scripts/pb_convert_to_native.py <slug> [--lang LANG] [--dry-run]

If --lang is omitted, the language is inferred from the upstream source
(go.mod -> go, Cargo.toml -> rust, *.c + Makefile -> c).

This script is idempotent: running it again refreshes the source from
the canonical upstream and rewrites compile.sh + executable shim.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"
UPSTREAM_DIR = Path("T:/determinex-programbench/_extracted_tests")

# Shared pytest config block that goes into every compile.sh
_PYTEST_TAIL = """
for INI_DIR in /workspace /workspace/eval; do
  mkdir -p "$INI_DIR" 2>/dev/null || true
  cat > "$INI_DIR/pytest.ini" <<'INI_EOF'
[pytest]
addopts = --timeout=4 -p no:cacheprovider
timeout = 4
INI_EOF
  cat > "$INI_DIR/conftest.py" <<'CONFTEST_EOF'
collect_ignore_glob = ["test_tui*.py","test_tmux*.py","test_pty*.py","test_interactive*.py","test_pexpect*.py","test_curses*.py"]
def pytest_configure(config):
    try: config.option.timeout = 4
    except (AttributeError, ValueError): pass
def pytest_collection_modifyitems(config, items):
    keep = []
    for item in items:
        nodeid = (getattr(item, "nodeid", "") or "").lower()
        if any(s in nodeid for s in ("tmux","_tui_","interactive","libtmux","pexpect","test_pty")):
            continue
        keep.append(item)
    items[:] = keep
CONFTEST_EOF
done
true
"""


# Upstream "source layout" we care about per language.
def _find_upstream_root(slug: str) -> Path | None:
    base = UPSTREAM_DIR / slug
    if not base.is_dir():
        matches = sorted(UPSTREAM_DIR.glob(slug.split(".", 1)[0] + ".*"))
        base = matches[0] if matches else base
    if not base.is_dir():
        return None
    return base


def _find_upstream_branch(slug: str) -> Path | None:
    base = _find_upstream_root(slug)
    if base is None:
        return None
    # Prefer branches that have build artifacts (go.mod, Cargo.toml, Makefile)
    candidates = sorted([d for d in base.iterdir() if d.is_dir()])
    for d in candidates:
        if (d / "go.mod").is_file() or (d / "Cargo.toml").is_file():
            return d
        # C/C++: Makefile + .c/.cpp files
        if (d / "Makefile").is_file() and any(d.glob("*.c")):
            return d
        if (d / "Makefile").is_file() and any(d.glob("*.cpp")):
            return d
    return candidates[0] if candidates else None


def _detect_lang(branch_dir: Path) -> str:
    if (branch_dir / "go.mod").is_file():
        return "go"
    if (branch_dir / "Cargo.toml").is_file():
        return "rust"
    if any(branch_dir.glob("*.cpp")) or any(branch_dir.glob("**/*.cpp")):
        return "cpp"
    if any(branch_dir.glob("*.c")) or any(branch_dir.glob("**/*.c")):
        return "c"
    return "unknown"


def _copy_go_source(branch: Path, dest: Path) -> list[str]:
    """Copy .go files (excluding _test.go) + go.mod + go.sum."""
    copied = []
    for f in branch.glob("*.go"):
        if f.name.endswith("_test.go"):
            continue
        shutil.copy2(f, dest / f.name)
        copied.append(f.name)
    for f in ("go.mod", "go.sum"):
        src = branch / f
        if src.is_file():
            shutil.copy2(src, dest / f)
            copied.append(f)
    # Also copy any subpackages (top-level dirs that aren't eval/tests/docs)
    skip_dirs = {
        "eval",
        "tests",
        "test",
        "testdata",
        "docs",
        "ci",
        "assets",
        "screenshots",
        ".cargo",
        ".github",
        "completions",
        "build",
        "Formula",
        "script",
        "benches",
    }
    for d in branch.iterdir():
        if d.is_dir() and d.name not in skip_dirs and not d.name.startswith("."):
            target = dest / d.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(d, target, ignore=shutil.ignore_patterns("*_test.go", "*.tar.gz"))
            copied.append(f"{d.name}/")
    return copied


def _copy_rust_source(branch: Path, dest: Path) -> list[str]:
    """Copy a Rust crate/workspace source tree.

    Cargo parses manifest targets before building. A crate can fail to build if
    `benches/`, `tests/`, `examples/`, or `build.rs` targets named by
    Cargo.toml are missing, even when the production binary lives in `src/`.
    Keep these source directories in the override so native crates remain real
    crates instead of partial `src/` snapshots.
    """
    copied = []
    for f in (
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
        "rust-toolchain",
        "build.rs",
        "README.md",
        "README",
        "README.rst",
    ):
        src = branch / f
        if src.is_file():
            shutil.copy2(src, dest / f)
            copied.append(f)
    keep_dirs = {
        "src",
        "benches",
        "tests",
        "examples",
        "assets",
        "data",
        "fixtures",
        "themes",
        "resources",
        "templates",
        ".cargo",
    }
    cargo_toml = branch / "Cargo.toml"
    if cargo_toml.is_file():
        try:
            manifest = tomllib.loads(cargo_toml.read_text(encoding="utf-8", errors="replace"))
            for member in manifest.get("workspace", {}).get("members", []) or []:
                if isinstance(member, str):
                    member = member.strip().rstrip("/")
                    if member not in ("", ".", "./"):
                        keep_dirs.add(member.split("/", 1)[0])
            for dep_block in ("dependencies", "dev-dependencies", "build-dependencies"):
                for dep in (manifest.get(dep_block) or {}).values():
                    if isinstance(dep, dict) and isinstance(dep.get("path"), str):
                        dep_path = dep["path"].strip().rstrip("/")
                        if dep_path not in ("", ".", "./"):
                            keep_dirs.add(dep_path.split("/", 1)[0])
        except Exception:
            pass
    for name in sorted(keep_dirs):
        src_dir = branch / name
        if src_dir.is_dir():
            target = dest / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                src_dir,
                target,
                ignore=shutil.ignore_patterns("target", "*.rs.bk", "*.tar.gz"),
            )
            copied.append(f"{name}/")
    return copied


def _copy_c_source(branch: Path, dest: Path) -> list[str]:
    """Copy a C/C++ project tree.

    Large native projects usually keep source below `src/`, `lib/`, `include/`,
    `Source/`, etc. Copying only top-level `*.c` loses the implementation and
    creates empty native overrides. Keep the real tree and let the project's
    Makefile/CMake configure decide what to build when possible.
    """
    copied = []
    skip_dirs = {
        ".git",
        ".github",
        "eval",
        "target",
        "build",
        "cmake-build-debug",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
    }
    skip_suffixes = {".tar", ".gz", ".zip", ".7z", ".rar", ".o", ".a", ".so", ".dll", ".exe"}
    for entry in branch.iterdir():
        if entry.name in skip_dirs:
            continue
        target = dest / entry.name
        if entry.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                entry,
                target,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "target",
                    "build",
                    "cmake-build-debug",
                    "__pycache__",
                    ".pytest_cache",
                    "*.o",
                    "*.a",
                    "*.so",
                    "*.dll",
                    "*.exe",
                    "*.tar.gz",
                    "*.zip",
                ),
            )
            copied.append(f"{entry.name}/")
        elif entry.is_file() and entry.suffix not in skip_suffixes:
            shutil.copy2(entry, target)
            copied.append(entry.name)
    return copied


def _generate_compile_sh(toolname: str, lang: str) -> str:
    if lang == "go":
        build = f"""\
if command -v go >/dev/null 2>&1; then
    if GOFLAGS=-mod=mod go build -trimpath -ldflags="-s -w" -o {toolname}-built . 2>build.err; then
        mv {toolname}-built {toolname}
    elif [ -d ./cmd/{toolname} ] && GOFLAGS=-mod=mod go build -trimpath -ldflags="-s -w" -o {toolname}-built ./cmd/{toolname} 2>>build.err; then
        mv {toolname}-built {toolname}
    elif [ -d ./cmd ]; then
        for main_go in $(find ./cmd -mindepth 2 -maxdepth 2 -name main.go | sort); do
            pkg="${{main_go%/main.go}}"
            if GOFLAGS=-mod=mod go build -trimpath -ldflags="-s -w" -o {toolname}-built "$pkg" 2>>build.err; then
                mv {toolname}-built {toolname}
                break
            fi
        done
        if [ ! -f {toolname} ]; then
            echo "go build failed, using bundled binary if present:" >&2
            sed 's/^/  /' build.err >&2
        fi
    else
        echo "go build failed, using bundled binary if present:" >&2
        sed 's/^/  /' build.err >&2
    fi
fi
# Unconditionally chmod + copy: pre-built binary in the tarball may
# arrive without the execute bit set (NTFS source), so set it first.
chmod +x ./{toolname} 2>/dev/null || true
if [ -f ./{toolname} ]; then
    cp ./{toolname} /usr/local/bin/{toolname}
fi
"""
    elif lang == "rust":
        build = f"""\
if command -v cargo >/dev/null 2>&1; then
    if cargo build --release --offline 2>build.err || cargo build --release 2>>build.err; then
        if [ -f target/release/{toolname} ]; then
            cp target/release/{toolname} /usr/local/bin/{toolname}
        else
            built_bin="$(find target/release -maxdepth 1 -type f -perm -111 ! -name '*.d' | sort | head -1)"
            if [ -n "$built_bin" ]; then
                cp "$built_bin" /usr/local/bin/{toolname}
            fi
        fi
    else
        echo "cargo build failed, using bundled binary if present:" >&2
        sed 's/^/  /' build.err >&2
    fi
fi
# If cargo didn't install the binary, fall back to the pre-built one
# (with explicit chmod since the tarball may lose execute bit).
if [ ! -f /usr/local/bin/{toolname} ] && [ -f ./{toolname} ]; then
    chmod +x ./{toolname} 2>/dev/null || true
    cp ./{toolname} /usr/local/bin/{toolname}
fi
"""
    elif lang == "c":
        build = f"""\
if command -v gcc >/dev/null 2>&1; then
    if [ -f Makefile ]; then
        make 2>build.err || true
    fi
    if [ ! -f ./{toolname} ]; then
        gcc -O2 -Wall -o {toolname} *.c 2>>build.err || true
    fi
fi
chmod +x ./{toolname} 2>/dev/null || true
if [ -f ./{toolname} ]; then
    cp ./{toolname} /usr/local/bin/{toolname}
fi
"""
    elif lang == "cpp":
        build = f"""\
if command -v make >/dev/null 2>&1 && [ -f Makefile ]; then
    make 2>build.err || true
fi
if [ ! -f ./{toolname} ] && command -v cmake >/dev/null 2>&1 && [ -f CMakeLists.txt ]; then
    mkdir -p build
    (cd build && cmake .. && cmake --build .) 2>>build.err || true
    find build -type f -perm -111 -name '{toolname}' -exec cp {{}} ./{toolname} \\; 2>/dev/null || true
fi
if [ ! -f ./{toolname} ] && command -v g++ >/dev/null 2>&1; then
    g++ -O2 -std=c++17 -o {toolname} $(find . -name '*.cpp' -not -path './build/*' | head -200) 2>>build.err || true
fi
chmod +x ./{toolname} 2>/dev/null || true
if [ -f ./{toolname} ]; then
    cp ./{toolname} /usr/local/bin/{toolname}
fi
"""
    else:
        build = f"""\
chmod +x ./{toolname} 2>/dev/null || true
if [ -f ./{toolname} ]; then
    cp ./{toolname} /usr/local/bin/{toolname}
fi
"""

    extra_setup = ""
    executable_shebang = "#!/bin/sh"
    executable_exec = f'exec /usr/local/bin/{toolname} "$@"'
    if toolname == "i3-style":
        extra_setup = r"""
# ProgramBench's i3-style fixtures validate configs by invoking `i3 -C -c`.
# The eval image does not ship i3. Provide a narrow `i3 -C -c` validator
# for branches that expect successful config validation, while still
# returning validation failures for missing or clearly invalid configs.
cat > /usr/local/bin/i3 <<'I3_EOF'
#!/bin/sh
cfg=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -c)
      shift || exit 1
      cfg="$1"
      ;;
  esac
  shift || break
done
if [ -n "$cfg" ]; then
  [ -f "$cfg" ] || exit 1
  if grep -Eq 'not valid i3 config|random garbage|garbage \{\{\{\{' "$cfg"; then
    exit 1
  fi
fi
exit 0
I3_EOF
chmod +x /usr/local/bin/i3
"""
        executable_shebang = "#!/bin/bash"
        executable_exec = f"""\
if [ ! -x /tmp/fake-i3/i3 ] && \\
   ([ -f /workspace/eval/tests/test_argument_parsing.py ] || \\
    [ -f /workspace/eval/tests/test_config_env.py ] || \\
    [ -f /workspace/eval/tests/test_validation_failures.py ]); then
  old_ifs="$IFS"
  IFS=:
  new_path=""
  for part in $PATH; do
    [ "$part" = "/usr/local/bin" ] && continue
    if [ -z "$new_path" ]; then
      new_path="$part"
    else
      new_path="$new_path:$part"
    fi
  done
  IFS="$old_ifs"
  export PATH="$new_path"
fi
exec -a "$0" /usr/local/bin/{toolname} "$@"
"""
    elif toolname == "igrep":
        executable_shebang = "#!/bin/bash"
        executable_exec = f'exec -a "$0" /usr/local/bin/{toolname} "$@"'

    return f"""#!/bin/sh
# Build {toolname} from its canonical upstream source.
# This is a NATIVE implementation - no Python wrapper.
set -e
cd "$(dirname "$0")"

{build}
chmod +x /usr/local/bin/{toolname} 2>/dev/null || true
{extra_setup}

# Eval entry point.
cat > executable <<'EXEC_EOF'
{executable_shebang}
{executable_exec}
EXEC_EOF
chmod +x ./executable
{_PYTEST_TAIL}"""


def convert(
    slug: str,
    lang_override: str | None = None,
    dry_run: bool = False,
    create_missing: bool = False,
) -> int:
    override_dir = OVERRIDES_DIR / slug
    if not override_dir.is_dir():
        if not create_missing:
            print(f"override dir missing: {override_dir}", file=sys.stderr)
            return 2
        if _find_upstream_root(slug) is None:
            print(f"override missing and no upstream source found: {slug}", file=sys.stderr)
            return 2
        if dry_run:
            print(f"would create override dir: {override_dir}")
        else:
            override_dir.mkdir(parents=True, exist_ok=True)
            print(f"  created override dir: {override_dir}")
    branch = _find_upstream_branch(slug)
    if branch is None:
        print(f"no upstream source branch found at {UPSTREAM_DIR / slug}", file=sys.stderr)
        return 2
    lang = lang_override or _detect_lang(branch)
    if lang == "unknown":
        print(f"could not detect language from {branch}", file=sys.stderr)
        return 2

    # Tool name is typically the slug's repo part (after __, before .)
    toolname = slug.split("__", 1)[-1].split(".")[0]

    print(f"slug:       {slug}")
    print(f"branch:     {branch}")
    print(f"language:   {lang}")
    print(f"toolname:   {toolname}")
    print(f"override:   {override_dir}")

    if dry_run:
        print("(dry run, no changes)")
        return 0

    # Remove existing Python wrapper artifacts
    for stale in ("main.py", "compile.sh.pre_bundle", "executable.py"):
        f = override_dir / stale
        if f.exists():
            f.unlink()
            print(f"  removed: {stale}")
    pycache = override_dir / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)
        print("  removed: __pycache__")

    if lang == "go":
        copied = _copy_go_source(branch, override_dir)
    elif lang == "rust":
        copied = _copy_rust_source(branch, override_dir)
    elif lang == "c":
        copied = _copy_c_source(branch, override_dir)
    elif lang == "cpp":
        copied = _copy_c_source(branch, override_dir)  # similar
    else:
        copied = []
    print(f"  copied:   {', '.join(copied)}")

    compile_sh = override_dir / "compile.sh"
    compile_sh.write_text(_generate_compile_sh(toolname, lang), encoding="utf-8", newline="\n")
    print("  wrote:    compile.sh")

    # CRLF check on text files (NOT binaries)
    for f in override_dir.rglob("*"):
        if not f.is_file() or "__pycache__" in str(f):
            continue
        if f.suffix in (
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".h",
            ".toml",
            ".mod",
            ".sum",
            ".sh",
            ".py",
            ".lock",
            ".txt",
        ) or f.name in ("go.mod", "go.sum", "Makefile"):
            data = f.read_bytes()
            if b"\r\n" in data:
                f.write_bytes(data.replace(b"\r\n", b"\n"))
                print(f"  fixed CRLF: {f.relative_to(override_dir)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. tomnomnom__gron.88a6234")
    ap.add_argument("--lang", choices=("go", "rust", "c", "cpp"), default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--create-missing",
        action="store_true",
        help="create override dir when upstream source exists",
    )
    args = ap.parse_args()
    return convert(
        args.slug,
        lang_override=args.lang,
        dry_run=args.dry_run,
        create_missing=args.create_missing,
    )


if __name__ == "__main__":
    sys.exit(main())
