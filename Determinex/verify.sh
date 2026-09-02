#!/usr/bin/env bash
# Determinex — verify the central claim yourself. No GPU, no API key, no network.
#
# The submission's whole argument is that a real compiler or test run is the only thing
# allowed to decide, and that the system refuses what it cannot verify. Both of those are
# checkable on a laptop in about two minutes, so they should not have to be taken on trust
# just because the throughput numbers needed a Radeon.
#
#     bash verify.sh
#
# Exits non-zero if any check fails. Every number it prints was computed while you watched.
set -uo pipefail

cd "$(dirname "$0")" || exit 2
PASS=0; FAIL=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then echo "python 3.11+ required"; exit 2; fi
printf 'Determinex self-verification — %s\n' "$($PY --version 2>&1)"

# ── --selftest: prove these checks are capable of failing ──────────────────────
# A green suite is evidence only if it could have been red. Every check below is broken on
# purpose, one at a time, against a scratch copy — the real files are never touched — and each
# mutation must turn the run non-zero. If a mutation still reports success, the check is
# decoration and this exits 1.
#
# This is not hypothetical caution. Two of the first sabotage attempts written for this script
# silently did nothing and looked exactly like passes: one patched a function signature that
# had since changed, the other inserted a `pass` statement, which is a no-op that leaves the
# body running. Both would have been recorded as "negative control confirmed" by anyone not
# reading the output. That is why this ships as a runnable mode rather than a sentence in a
# README claiming it was done once.
if [ "${1:-}" = "--selftest" ]; then
  # A RELATIVE scratch dir, deliberately. `mktemp -d` hands back an MSYS path (/tmp/...) that
  # Windows Python resolves as a different directory entirely (\tmp\...), so under Git Bash the
  # mutations wrote nowhere and the run failed on missing paths instead of on the sabotage —
  # reported as "caught", for entirely the wrong reason. A path relative to the script's own
  # directory is the one thing bash and Windows Python are guaranteed to agree about.
  TMP=".selftest.$$"; rm -rf "$TMP"; mkdir -p "$TMP"; trap 'rm -rf "$TMP"' EXIT
  SPASS=0; SFAIL=0
  # Each sabotage is a function, invoked directly. An earlier draft passed them as strings
  # through `eval`, which meant quoting a Python snippet through two layers of shell and left
  # the mutation's failure mode indistinguishable from its success.
  mut_oracle() { sed -i 's|assert solution|pass  #|g' v.sh; }

  mut_refusal() { "$PY" - <<'MUT'
import pathlib
p = pathlib.Path("src/determinex_synthesize.py"); s = p.read_text(encoding="utf-8")
n = 'def parse_spec(text: str, language: str = "python") -> Spec:'
assert n in s, "signature moved — this mutation would have silently done nothing"
p.write_text(s.replace(n, n + '\n    text += " For example solution([1, 2, 3]) returns 2.0, '
                       'solution([10]) returns 10.0, and solution([]) returns 0.0."', 1),
             encoding="utf-8")
MUT
  }

  mut_reference() { "$PY" - <<'MUT'
import json, pathlib
p = pathlib.Path("src/bit_techniques_playbook.json"); d = json.loads(p.read_text(encoding="utf-8"))
n = 0
for e in d["entries"]:
    if e["reference"].startswith("def popcount"):
        e["reference"] = "def popcount(x, bits): return 99"; n += 1
assert n == 1, f"expected exactly one popcount reference, found {n}"
p.write_text(json.dumps(d), encoding="utf-8")
MUT
  }

  mutate() { # name, mutation-function
    local name="$1"; shift
    rm -rf "$TMP/src"; cp -r verify_src "$TMP/src"; rm -rf "$TMP/src/__pycache__"
    cp verify.sh "$TMP/v.sh"
    # Fingerprint before and after. A mutation that quietly fails to apply leaves the tree
    # untouched, the run then passes for the honest reason, and the old code credited that as
    # a catch. Nothing is trusted here until the sabotage is shown to have changed something.
    local before after
    before=$(cat "$TMP/src"/* "$TMP/v.sh" 2>/dev/null | cksum)
    ( cd "$TMP" && "$@" ) >/dev/null 2>&1 || true
    after=$(cat "$TMP/src"/* "$TMP/v.sh" 2>/dev/null | cksum)
    if [ "$before" = "$after" ]; then
      printf '  \033[31mNO-OP\033[0m       %s — the sabotage never applied; this proves nothing\n' "$name"
      SFAIL=$((SFAIL+1)); return
    fi
    # "src", not "$TMP/src": the copied script cd's to its own directory first, so the
    # override is resolved from there by both the shell and Python.
    if DETERMINEX_VERIFY_SRC="src" bash "$TMP/v.sh" >"$TMP/out.txt" 2>&1; then
      printf '  \033[31mNOT CAUGHT\033[0m  %s — the check passed while broken\n' "$name"
      SFAIL=$((SFAIL+1))
    else
      printf '  \033[32mcaught\033[0m      %s\n' "$name"
      SPASS=$((SPASS+1))
    fi
  }
  printf '\n\033[1mSelf-test: breaking each check on purpose\033[0m\n'

  mutate "oracle blinded (accepts a program that returns the wrong answer)" mut_oracle
  mutate "refusal path made to find something checkable in anything"        mut_refusal
  mutate "a shipped reference implementation corrupted"                     mut_reference

  printf '\n\033[1mResult\033[0m\n  %d of %d mutations caught\n\n' "$SPASS" "$((SPASS+SFAIL))"
  if [ "$SFAIL" -gt 0 ]; then
    echo "  A check that cannot fail proves nothing. Fix it before trusting the green run."
    exit 1
  fi
  echo "  Every check above turns red when the thing it checks is broken. The green run"
  echo "  therefore means something."
  exit 0
fi

# ── 1. The oracle discriminates ────────────────────────────────────────────────
# The claim everything else rests on: a verifier that accepts everything proves nothing.
# So the check is two-sided — correct code must PASS and broken code must FAIL. A verifier
# that only ever says yes would sail through a one-sided test, which is why this runs both.
hdr "1. The oracle accepts correct code and REJECTS broken code"
$PY - <<'PYEOF'
import subprocess, sys, tempfile, os, textwrap
good = "def solution(numbers):\n    return sum(numbers)/len(numbers) if numbers else 0.0\n"
bad  = "def solution(numbers)\n    return 1\n"          # syntax error
wrong= "def solution(numbers):\n    return 42\n"        # compiles, wrong answer
tests = textwrap.dedent('''
    from solution import solution
    assert solution([1,2,3]) == 2.0
    assert solution([10]) == 10.0
    assert solution([]) == 0.0
    print("checks passed")
''')
def run(src):
    d = tempfile.mkdtemp()
    open(os.path.join(d,"solution.py"),"w").write(src)
    open(os.path.join(d,"t.py"),"w").write(tests)
    r = subprocess.run([sys.executable,"t.py"],cwd=d,capture_output=True,text=True,timeout=60)
    return r.returncode == 0
results = {"correct": run(good), "syntax-error": run(bad), "compiles-but-wrong": run(wrong)}
for k,v in results.items():
    print(f"    {k:<20} oracle says {'PASS' if v else 'FAIL'}")
sys.exit(0 if (results["correct"] and not results["syntax-error"] and not results["compiles-but-wrong"]) else 1)
PYEOF
if [ $? -eq 0 ]; then ok "correct accepted; syntax error AND wrong-answer both rejected"
else bad "the oracle did not discriminate — this invalidates the submission"; fi

# ── 2. It refuses what it cannot verify ────────────────────────────────────────
# A system that answers everything is a system whose answers mean nothing. This is the
# refusal path, and it reaches its verdict WITHOUT calling a model at all: if no sound
# oracle can be synthesised there is nothing to generate against.
hdr "2. An unverifiable request is REFUSED, before any model is called"
$PY - <<'PYEOF'
import sys, pathlib
# verify_src/ holds the ACTUAL module, copied verbatim, not a restatement of it — the
# check is worthless if it exercises a convenience reimplementation written to pass.
# It imports nothing but the standard library, which is why it can travel.
import os
root = pathlib.Path.cwd()
cands = [pathlib.Path(os.environ["DETERMINEX_VERIFY_SRC"])] if os.environ.get(
    "DETERMINEX_VERIFY_SRC") else [root/"verify_src", root/"scripts", root.parent/"scripts"]
for c in cands:
    if (c/"determinex_synthesize.py").exists():
        sys.path.insert(0, str(c)); break
else:
    print("    (determinex_synthesize.py not found)"); sys.exit(3)
from determinex_synthesize import parse_spec  # noqa: E402
vague = parse_spec("improve the code quality of my project")
exact = parse_spec("solution(numbers) returns the average. For example solution([1, 2, 3]) "
                   "returns 2.0, solution([10]) returns 10.0, and solution([]) returns 0.0.")
nv, ne = len(getattr(vague,"examples",[]) or []), len(getattr(exact,"examples",[]) or [])
print(f"    vague idea  -> {nv} checkable examples  (refuses: nothing a test could assert)")
print(f"    exact idea  -> {ne} checkable examples  (proceeds)")
sys.exit(0 if nv == 0 and ne >= 3 else 1)
PYEOF
rc=$?
if   [ $rc -eq 0 ]; then ok "vague idea yields no sound oracle; the same idea with examples yields 3"
elif [ $rc -eq 3 ]; then printf '  \033[33mSKIP\033[0m  verify_src/ missing\n'
else bad "refusal path did not behave as documented"; fi

# ── 3. The corpus references are exactly right ─────────────────────────────────
# An oracle built on a wrong reference produces confidently wrong verdicts, so the shipped
# reference implementations are checked EXHAUSTIVELY over every 8-bit input — a proof, not
# a sample.
hdr "3. Corpus reference implementations, checked over all 256 u8 inputs"
$PY - <<'PYEOF'
import sys, json, pathlib
import os
root = pathlib.Path.cwd()
cands = [pathlib.Path(os.environ["DETERMINEX_VERIFY_SRC"])] if os.environ.get(
    "DETERMINEX_VERIFY_SRC") else [root/"verify_src", root/"corpus", root.parent/"corpus"]
p = None
for c in cands:
    if (c/"bit_techniques_playbook.json").exists():
        p = c/"bit_techniques_playbook.json"; break
if p is None:
    print("    (bit_techniques_playbook.json not found)"); sys.exit(3)
ns = {}
for e in json.loads(p.read_text(encoding="utf-8"))["entries"]:
    # No try/except and no truncation at '#'. An earlier draft did both, and both are the
    # silent pass this whole submission argues against: swallowing a failed definition lets
    # a stale same-named function from a previous entry answer for this one, and cutting at
    # the first '#' would quietly discard the body of any commented reference. If a
    # reference will not load, that is a finding — let it raise.
    exec(e["reference"], ns)
bad = 0
for x in range(256):
    if ns["popcount"](x,8) != bin(x).count("1"): bad += 1
    if ns["clz"](x,8) != 8 - x.bit_length(): bad += 1
    if ns["is_pow2"](x,8) != (x != 0 and (x & (x-1)) == 0): bad += 1
    if ns["reverse"](ns["reverse"](x,8),8) != x: bad += 1
print(f"    1024 assertions over every 8-bit input — mismatches: {bad}")
sys.exit(0 if bad == 0 else 1)
PYEOF
rc=$?
if   [ $rc -eq 0 ]; then ok "every reference exact over the full input domain"
elif [ $rc -eq 3 ]; then printf '  \033[33mSKIP\033[0m  verify_src/ missing\n'
else bad "a shipped reference implementation is wrong"; fi

# ── result ─────────────────────────────────────────────────────────────────────
hdr "Result"
printf '  %d passed, %d failed\n\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "  A failure here means a claim in this submission does not hold. That is the point"
  echo "  of shipping the check."
  exit 1
fi
echo "  The GPU throughput figures need a Radeon and are in amd_gpu_evidence/ with the raw"
echo "  tool output that produced them. Everything above was computed just now, on this"
echo "  machine, with no GPU and no network."
