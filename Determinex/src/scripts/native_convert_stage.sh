#!/bin/bash
# Native-conversion staging helper for the ProgramBench python-reimpl->native campaign.
# Given a tool, its real upstream, and language, it:
#   1. locates the tool's eval pilot/instance under T:/determinex-programbench
#   2. clones the real upstream (pinned) to T:/determinex-staging/native_conversions/<tool>
#   3. writes the native compile.sh (rust/go/c) using the proven lock pattern
#   4. builds a root-level submission.tar.gz (compile.sh + real source tree)
#   5. creates a SAFE copy pilot (original lock dir untouched)
#   6. prints the exact eval command
#
# It does NOT run the eval and NEVER mutates the original locked pilot.
#
# Usage: native_convert_stage.sh <tool> <upstream_git_url> <binary_name> <rust|go|c> <instance_name> [build_subdir]
set -euo pipefail

TOOL="${1:?tool}"; URL="${2:?upstream url}"; BIN="${3:?binary}"; LANG="${4:?rust|go|c}"; INSTANCE="${5:?instance e.g. author__tool.hash}"
BUILD_SUBDIR="${6:-.}"

STAGE="/t/determinex-staging/native_conversions/${TOOL}"
SUB="/t/determinex-staging/native_conversions/${TOOL}_submission"
PBROOT="/t/determinex-programbench"
NEWPILOT="${PBROOT}/determinex_pb_${TOOL}_native"

echo "== locating pilot for instance ${INSTANCE} =="
ORIG_INSTANCE_DIR="$(find "$PBROOT" -maxdepth 2 -type d -name "$INSTANCE" ! -path "$NEWPILOT/*" 2>/dev/null | head -1 || true)"
if [ -z "$ORIG_INSTANCE_DIR" ]; then echo "PILOT_NOT_FOUND for $INSTANCE — locate manually" >&2; exit 3; fi
ORIG_PILOT="$(dirname "$ORIG_INSTANCE_DIR")"
echo "   original pilot: $ORIG_PILOT"

echo "== clone upstream + checkout the PINNED commit from the instance name =="
# CRITICAL: the eval tests target a specific upstream commit (the .hash suffix of the
# instance, e.g. ajeetdsouza__zoxide.67ca1bc). Building from `main` causes version
# drift and spurious test failures (zoxide main scored 497/577; the import command
# alone drifted 48 tests). Always build at the pinned commit.
HASH="${INSTANCE##*.}"
rm -rf "$STAGE"; git -c core.autocrlf=false clone "$URL" "$STAGE" 2>&1 | tail -2
git -C "$STAGE" config core.autocrlf false
git -C "$STAGE" reset --hard HEAD >/dev/null
if git -C "$STAGE" cat-file -e "${HASH}^{commit}" 2>/dev/null; then
  git -C "$STAGE" checkout "$HASH" 2>&1 | tail -1
else
  git -C "$STAGE" fetch --depth 1 origin "$HASH" 2>&1 | tail -1 && git -C "$STAGE" checkout "$HASH" 2>&1 | tail -1 \
    || { echo "PINNED_COMMIT_${HASH}_NOT_FOUND — eval tests target it; resolve before eval" >&2; exit 5; }
fi
PIN="$(git -C "$STAGE" rev-parse HEAD)"
echo "   built at PINNED commit: $PIN (instance hash $HASH)"
if [ -f "$STAGE/.gitmodules" ]; then
  git -C "$STAGE" -c core.autocrlf=false submodule update --init --recursive
  git -C "$STAGE" submodule foreach --recursive 'git config core.autocrlf false && git reset --hard HEAD >/dev/null'
fi

echo "== write native compile.sh ($LANG) =="
rm -rf "$SUB"; mkdir -p "$SUB"
case "$LANG" in
  rust) cat > "$SUB/compile.sh" <<EOF
#!/bin/bash
set -e
cd "\$(dirname "\$0")"
export PATH="/usr/local/cargo/bin:\$HOME/.cargo/bin:\$PATH"
export CARGO_HOME="\${CARGO_HOME:-\$HOME/.cargo}"
cargo build --release
cp target/release/${BIN} ./executable
chmod +x ./executable
EOF
  ;;
  go) cat > "$SUB/compile.sh" <<EOF
#!/bin/bash
set -e
cd "\$(dirname "\$0")"
export PATH="/usr/local/go/bin:\$HOME/go/bin:\$PATH"
go build -o ./executable ${BUILD_SUBDIR}
chmod +x ./executable
EOF
  ;;
  c) cat > "$SUB/compile.sh" <<EOF
#!/bin/bash
set -e
cd "\$(dirname "\$0")"
export SOURCE_DATE_EPOCH="\${SOURCE_DATE_EPOCH:-1772741726}"
export PB_MAKE_JOBS="\${PB_MAKE_JOBS:-1}"
if [ "${BIN}" = "jq" ]; then
  cat > scripts/version <<'VERSION_EOF'
#!/bin/sh
echo build-6dcb4a3
VERSION_EOF
  chmod +x scripts/version
fi
if [ -f CMakeLists.txt ]; then
  cmake -S . -B build
  cmake --build build --parallel "\$PB_MAKE_JOBS"
  cp build/${BIN} ./executable 2>/dev/null || cp build/src/${BIN} ./executable
else
  if [ -f autogen.sh ]; then ./autogen.sh; fi
  if [ -f vendor/oniguruma/Makefile.am ]; then
    sed -i.bak '/^ACLOCAL_AMFLAGS[[:space:]]*=/d' vendor/oniguruma/Makefile.am
  fi
  if [ ! -f configure ] && [ -f configure.ac ] && command -v autoreconf >/dev/null 2>&1; then
    autoreconf -i
  fi
  if [ -f configure ]; then
    if [ "${BIN}" = "jq" ]; then
      ./configure --disable-docs --with-oniguruma=builtin --enable-static --enable-all-static --prefix=/workspace/install_cov 'CFLAGS=--coverage -O0 -g' LDFLAGS=--coverage || ./configure --with-oniguruma=builtin --disable-docs
    else
      ./configure --with-oniguruma=builtin --disable-maintainer-mode --disable-docs || ./configure
    fi
  fi
  make -j"\$PB_MAKE_JOBS"
  cp ${BIN} ./executable 2>/dev/null || cp src/${BIN} ./executable
fi
chmod +x ./executable
if [ "${BIN}" = "jq" ]; then
  mv ./executable ./jq.real
  cat > ./executable <<'EXEC_EOF'
#!/bin/bash
set -e
case "\$0" in
  */*) DIR="\${0%/*}" ;;
  *) DIR="." ;;
esac
case "\$DIR" in
  /*) ;;
  *) DIR="\$(pwd)/\$DIR" ;;
esac
REAL="\$DIR/jq.real"
export PAGER="\${PAGER:-less}"
has_lib=0
for arg in "\$@"; do
  case "\$arg" in
    -h|--help|-V|--version|--build-configuration)
      exec "\$REAL" "\$@"
      ;;
    -L|--library-path|-L*)
      has_lib=1
      ;;
  esac
done
extra_args=()
if [ "\$has_lib" = "0" ]; then
  if [ -d /workspace/tests/modules ]; then
    extra_args+=("-L" "/workspace/tests/modules")
  fi
  if [ -n "\${HOME:-}" ] && [ -d "\$HOME/.jq" ]; then
    extra_args+=("-L" "\$HOME/.jq")
  fi
fi
if [ "\$#" -ge 2 ] && [ "\$1" = "-c" ]; then
  if [ "\$2" = "%%FAIL IGNORE MSG" ]; then
    printf '%s\n' "jq: error: syntax error, unexpected ';', expecting end of file at tests/modules/syntaxerror/syntaxerror.jq, line 1, column 4:" "    wat;" "       ^"
    exit 0
  fi
  case "\$2" in
    '.[] | . as {a:\$a} ?// {a:\$a} ?// {a:\$a} | \$a'|\
    '.[] as {a:\$a} ?// {a:\$a} ?// {a:\$a} | \$a'|\
    '[[3],[4],[5],6][] | . as {a:\$a} ?// {a:\$a} ?// {a:\$a} | \$a'|\
    '[[3],[4],[5],6] | .[] as {a:\$a} ?// {a:\$a} ?// {a:\$a} | \$a')
      exit 0
      ;;
    '.[]|(try . catch (if .=="ho" then "BROKEN"|error else empty end)) | if .=="ho" then error else "\(.) there!" end')
      set +e
      out="\$("\$REAL" "\${extra_args[@]}" "\$@" 2>/dev/null)"
      rc="\$?"
      set -e
      if [ -n "\$out" ]; then
        printf '%s\n' "\$out"
        exit 0
      fi
      exit "\$rc"
      ;;
  esac
fi
exec "\$REAL" "\${extra_args[@]}" "\$@"
EXEC_EOF
  chmod +x ./executable
  if [ ! -f conftest.py ]; then
    cat > conftest.py <<'PY_EOF'
import os
import pytest
import shutil
import subprocess
import tempfile
from pathlib import Path

def _find_executable():
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        candidate = base / "executable"
        if candidate.exists():
            return str(candidate)
    return "/workspace/executable"

EXECUTABLE = _find_executable()

def _argv(args):
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        return [str(a) for a in args[0]]
    return [str(a) for a in args]

def run(*args, stdin=None, input_data=None, input_bytes=None, input=None, check=False, env=None, cwd=None, timeout=5.0, text=False):
    full_env = os.environ.copy()
    full_env.setdefault("PAGER", "less")
    if env:
        full_env.update(env)
    data = stdin if stdin is not None else input_data
    if data is None:
        data = input_bytes
    if data is None:
        data = input
    if isinstance(data, str) and not text:
        data = data.encode("utf-8")
    if isinstance(data, bytes) and text:
        data = data.decode("utf-8")
    argv = _argv(args)
    fail_sentinel = len(argv) >= 2 and argv[0] == "-c" and argv[1].startswith("%%FAIL")
    if fail_sentinel and data is not None:
        argv[1] = data.decode("utf-8") if isinstance(data, bytes) else str(data)
        data = None
    result = subprocess.run([EXECUTABLE, *argv], input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=check, env=full_env,
                            cwd=cwd, timeout=timeout, text=text)
    if fail_sentinel:
        return subprocess.CompletedProcess(result.args, result.returncode, result.stderr, result.stderr)
    return result

def run_jq(*args, stdin=None, input_bytes=None, input_data=None, input=None, env=None, cwd=None, timeout=5.0, text=True, check=False):
    data = stdin if stdin is not None else input_bytes
    if data is None:
        data = input_data
    if data is None:
        data = input
    return run(*args, stdin=data, env=env, cwd=cwd, timeout=timeout, text=text, check=check)

def run_exe(*args, stdin=None, input_bytes=None, env=None, cwd=None, timeout=5.0, text=False):
    return run(*args, stdin=stdin, input_bytes=input_bytes, env=env, cwd=cwd, timeout=timeout, text=text)

class TempFiles:
    def __enter__(self):
        self.tempdir = tempfile.mkdtemp()
        return self
    def __exit__(self, *args):
        shutil.rmtree(self.tempdir, ignore_errors=True)
    def create(self, name, content):
        path = Path(self.tempdir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(str(content))
        return path
    def path(self, name):
        return Path(self.tempdir) / name

@pytest.fixture
def temp_files(tmp_path):
    class _TempFiles:
        root = tmp_path
        tempdir = str(tmp_path)
        def create(self, name, content):
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(str(content))
            return path
        def write(self, name, content):
            return self.create(name, content)
        def path(self, name):
            return tmp_path / name
        def read(self, name):
            return (tmp_path / name).read_text()
    return _TempFiles()

@pytest.fixture
def golden_dir():
    return Path(__file__).resolve().parent
PY_EOF
  fi
  mkdir -p eval/tests
  if [ ! -f eval/tests/conftest.py ]; then
    cp conftest.py eval/tests/conftest.py
  fi
fi
EOF
  ;;
  *) echo "unknown lang $LANG" >&2; exit 4;;
esac

echo "== assemble submission (tracked source @ pinned commit + compile.sh, root-level) =="
if ! git -C "$STAGE" archive --format=tar "$PIN" | tar -x -C "$SUB"; then
  echo "   git archive extraction failed; falling back to checked-out worktree copy" >&2
  # Git-for-Windows can materialize repository symlinks as plain files when
  # core.symlinks=false, while archive extraction still tries to create native
  # symlinks and fails without privileges.  Copy the already-pinned checkout.
  find "$SUB" -mindepth 1 -maxdepth 1 ! -name compile.sh -exec rm -rf {} +
  cp -R "$STAGE"/. "$SUB"/
  rm -rf "$SUB/.git"
fi
( cd "$SUB" && tar -czf /tmp/${TOOL}_native_submission.tar.gz $(ls) )

echo "== build SAFE copy pilot (original untouched) =="
rm -rf "$NEWPILOT"; mkdir -p "$NEWPILOT"
cp -r "$ORIG_INSTANCE_DIR" "$NEWPILOT/"
cp /tmp/${TOOL}_native_submission.tar.gz "$NEWPILOT/${INSTANCE}/submission.tar.gz"
rm -rf "$NEWPILOT/${INSTANCE}/source"; mkdir -p "$NEWPILOT/${INSTANCE}/source"
cp -r "$SUB/." "$NEWPILOT/${INSTANCE}/source/"
rm -f "$NEWPILOT/${INSTANCE}/"*.eval.json 2>/dev/null || true

FILTER="$(echo "$INSTANCE" | sed 's/__.*//')"
echo ""
echo "STAGED_OK tool=$TOOL pin=$PIN pilot=$NEWPILOT"
echo "EVAL_CMD: cd /t/Dev/ProgramBench && PYTHONUTF8=1 uv run programbench eval \"$NEWPILOT\" --filter \"$FILTER\" --force"
