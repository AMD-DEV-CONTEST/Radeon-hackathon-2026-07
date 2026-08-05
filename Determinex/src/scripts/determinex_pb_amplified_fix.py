#!/usr/bin/env python3
"""determinex_pb_amplified_fix.py -- verified-search fix-generation for ProgramBench.

Stage 1 of the autonomous loop: when the DETERMINISTIC autofix techniques
(determinex_pb_autofix: bidir/hermetic/droppriv/tui/go-toolchain/build-fix) don't lock
a tool, the remaining tail is BEHAVIORAL -- a per-tool build/output puzzle no fixed
technique encodes (the atlas/ov class). This is where the Correctness Amplifier earns
its keep: sample K candidate fixes from a model, verify EACH against the sound oracle,
keep the first that locks. A weak model with per-try success p, sampled K times against
a sound oracle, locks with 1-(1-p)^K -> any p>0 is driven toward a lock.

It is NOT a new search engine -- it composes the existing primitive:
  * determinex_verified_search.VerifiedSearch  (best-of-K + feedback + loop-break + adjudicate)
  * a generate(prompt,temp)->candidate compile.sh   (any model; router/providers live)
  * an oracle verify(candidate)->.passed/.failures   (PB eval on the candidate; sound)

The oracle MUST be sound (a passing OracleResult only from a real from-source build --
see determinex_pb_provenance_guard). Garbage oracle in => confident garbage out. `solved`
is never claimed without a passing eval. Live wiring (model + Hetzner eval w/ repack)
is injected; the loop logic is model- and transport-agnostic and unit-tested with mocks.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from determinex_verified_search import SearchResult, VerifiedSearch  # noqa: E402

GenerateFn = Callable[[str, float], str]
# An eval fn runs the oracle on a CANDIDATE compile.sh and returns a PB-eval-shaped dict
# ({"test_results": [{"status","name","extra":{"text"}}, ...]}). Live: repack+Hetzner eval.
EvalFn = Callable[[str], dict]


@dataclass
class _Failure:  # duck-types determinex_oracle.Failure (.name/.test_id/.text)
    test_id: str
    name: str
    text: str = ""


@dataclass
class FixOracleResult:  # duck-types determinex_verified_search.OracleLike
    passed: bool  # True ONLY for a full lock (passed==total, sound oracle)
    failures: list = field(default_factory=list)
    passed_n: int = 0
    total: int = 0


def adapt_eval(eval_data: dict) -> FixOracleResult:
    """Turn a PB eval dict into the verified-search OracleLike. A candidate 'passes'
    only when it is a real lock: passed==total with total>0 (not_run/skipped/failed all
    count against -- the official metric). Failures carry the traceback for feedback."""
    tr = eval_data.get("test_results") or []
    c = Counter(x.get("status") for x in tr)
    total = len(tr)
    passed_n = c.get("passed", 0)
    fails = []
    for x in tr:
        if x.get("status") in ("passed",):
            continue
        ex = x.get("extra")
        txt = ex.get("text", "") if isinstance(ex, dict) else ""
        fails.append(
            _Failure(
                test_id=x.get("test_id", "") or x.get("name", ""),
                name=x.get("name", "") or x.get("test_id", ""),
                text=txt or "",
            )
        )
    is_lock = total > 0 and passed_n == total
    return FixOracleResult(passed=is_lock, failures=fails[:25], passed_n=passed_n, total=total)


def _build_knowledge_playbook(failures_text: str = "") -> list[str]:
    """The accumulated build-fail class knowledge (build_knowledge.class_patterns) as a SYMPTOM->FIX
    playbook, so the model fixes using what the system ALREADY KNOWS (toolchain / build-target /
    cargo-offline / source-gap / slow-build) instead of guessing -- the 'right the first time'
    grounding. Pulled live so it grows as the corpus learns. Best-effort (empty on any error).
    `failures_text` ranks the LEARNED/absorbed classes by relevance so the matching ones surface."""
    try:
        import json as _json

        kn = _json.loads(
            (
                Path(__file__).resolve().parent.parent / "corpus/programbench/build_knowledge.json"
            ).read_text(encoding="utf-8")
        )
        cp = kn.get("class_patterns", {})
    except Exception:
        return []
    keys = [
        "go_x_toolchain",
        "go_toolchain_bogus_future_version",
        "go_build_target",
        "rust_dangling_target_source_gap",
        "source_gap_upstream_fetch",
        "cc_build_deps",
        "whale_native_build_deps",
        "tarball_source_drift",
        # behavioral near-lock-tail classes: an output/format mismatch the model can fix in
        # compile.sh/conftest (the score-mover -- these convert near-locks to locks).
        "file_mode_goldens",
        "stdout_stderr_routing",
        "dead_datetime_anchor_conftest_2026_06_23",
        "conftest_char_iteration_filter",
        "repl_banner_history_perbranch",
        "nr_tests_json_eval_prefix",
    ]
    out = [
        "KNOWN BUILD + BEHAVIORAL FAILURE CLASSES (the system's accumulated knowledge -- match the",
        "symptom and apply the known fix; do NOT guess a different approach when one matches):",
    ]
    for k in keys:
        v = cp.get(k)
        if isinstance(v, dict):
            sym = str(v.get("symptom") or v.get("detect") or "")[:170]
            fix = str(v.get("fix") or "")[:210]
            if fix:
                out.append(f"  * {k}: WHEN {sym}  ->  FIX {fix}")
        elif isinstance(v, str) and v.strip():  # some classes are a single prose description
            out.append(f"  * {k}: {v.strip()[:320]}")
    out += [
        "  * slow_build_timeout: builds clean LOCALLY but ALL tests not_run on the box -> the build"
        " TIMED OUT (deps compiled from scratch). Warm/vendor deps (cargo fetch; go mod download)"
        " so the build finishes fast; keep --release; never wrap the build in a short timeout.",
        "",
    ]
    # LEARNED classes -- (symptom -> fix) pairs from TWO sources, and the split matters:
    # learn_class() writes verified=True for oracle-confirmed flywheel solves, while
    # determinex_pb_absorb writes verified=False for classes extracted from prose. As of
    # 2026-07-28 that is 5 verified against 267 absorbed, so describing this list as "the
    # system's own verified solves" -- which this comment used to -- is off by two orders
    # of magnitude.
    #
    # Mixing them is still sound, and deliberately so: the oracle gates the next use, so a
    # wrong hint costs a wasted attempt and can never produce a false pass. But the model
    # should be able to WEIGHT them, so each line below is tagged with its provenance
    # instead of presenting a prose guess and a proven fix identically.
    learned = kn.get("learned_classes", {})
    if isinstance(learned, dict) and learned:
        import re as _re

        ftoks = set(_re.findall(r"[a-z0-9_]+", failures_text.lower())) if failures_text else set()

        def _score(v) -> int:
            if not isinstance(v, dict):
                return -1
            if not ftoks:
                return 0
            dt = set(_re.findall(r"[a-z0-9_]+", str(v.get("detect", "")).lower()))
            return len(ftoks & dt)

        ranked = sorted(
            learned.items(),
            key=lambda kv: (_score(kv[1]), str(kv[1].get("learned", ""))),
            reverse=True,
        )
        # when we have failure text, surface the RELEVANT matches (top 20); else the most-recent 12.
        shown = [(k, v) for k, v in ranked if _score(v) > 0][:20] if ftoks else ranked[:12]
        if not shown:
            shown = ranked[:8]
        n_ver = sum(1 for _k, _v in shown if isinstance(_v, dict) and _v.get("verified"))
        out.append(
            f"LEARNED CLASSES ({n_ver} of {len(shown)} shown are oracle-VERIFIED fixes from this "
            "system's own solves; the rest are unverified hints absorbed from prose. Prefer a "
            "VERIFIED class when both match. Apply when the symptom matches; the oracle still "
            "judges the result):"
        )
        for k, v in shown:
            if not isinstance(v, dict):
                continue
            det = str(v.get("detect") or v.get("symptom") or "")[:140]
            fix = str(v.get("fix") or "").replace("\n", " ; ")[:240]
            if det and fix:
                mark = "VERIFIED" if v.get("verified") else "unverified-prose"
                out.append(f"  * [{mark}] {v.get('source_tool', k)}: WHEN {det}  ->  FIX {fix}")
        out.append("")
    return out


def _normalize_signature(text: str, slug: str = "") -> str:
    """Generalize a failure text into a reusable SYMPTOM signature: keep the salient error line,
    strip tool-/path-/number-/hash-specific tokens so it matches SIMILAR tools, not just this one."""
    import re as _re

    base = slug.split("__")[-1].split(".")[0] if slug else ""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    salient = [
        ln
        for ln in lines
        if _re.search(
            r"error|fatal|not found|cannot find|failed|requires|no such|undefined|mismatch|missing",
            ln,
            _re.I,
        )
    ]
    s = (salient[0] if salient else (lines[0] if lines else "")).strip()
    if base:
        s = s.replace(base, "<tool>")
    s = _re.sub(r"/[\w./+-]+", "<path>", s)  # absolute paths
    s = _re.sub(r"\b[0-9a-f]{7,40}\b", "<hex>", s)  # commit hashes / addresses
    s = _re.sub(r"\b\d+\b", "<n>", s)  # line numbers / counts
    s = _re.sub(r"\s+", " ", s).strip()
    return s[:200]


def _fix_diff(before: str, after: str, slug: str = "") -> list[str]:
    """The generalizable FIX = the shell lines the solve ADDED to compile.sh, tool-name-stripped."""
    base = slug.split("__")[-1].split(".")[0] if slug else ""
    before_set = set((before or "").splitlines())
    out = []
    for ln in (after or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or ln in before_set:
            continue
        out.append((ln.replace(base, "<tool>") if base else ln).rstrip())
    return out[:20]


def learn_class(
    slug: str, failures_text: str, before_sh: str, after_sh: str, knowledge_path: Path | None = None
) -> dict:
    """THE FLYWHEEL: when a VERIFIED fix improved a tool via a NOVEL compile.sh change, distill it
    into a learned class (symptom -> the exact fix that worked) and append to
    build_knowledge.learned_classes, so the grounded fixer applies it FIRST-shot on the next tool
    with that symptom. Sound: the fix is oracle-verified and the next use is oracle-gated, so a
    learned class can only HELP (a wrong hint fails verification, no harm). Dedup by signature hash;
    bounded to 60. Returns {learned, key|why}."""
    import hashlib as _hl
    import json as _json
    import time as _t

    kp = knowledge_path or (
        Path(__file__).resolve().parent.parent / "corpus/programbench/build_knowledge.json"
    )
    diff = _fix_diff(before_sh, after_sh, slug)
    if not diff:
        return {"learned": False, "why": "no-diff"}
    sig = _normalize_signature(failures_text, slug)
    if not sig or len(sig) < 12:
        return {"learned": False, "why": "weak-signature"}
    fixtext = "\n".join(diff)
    key = "learned_" + _hl.sha256((sig + "||" + fixtext).encode("utf-8")).hexdigest()[:10]
    try:
        kn = _json.loads(kp.read_text(encoding="utf-8"))
    except Exception as e:
        return {"learned": False, "why": f"kn-read: {e}"}
    lc = kn.setdefault("learned_classes", {})
    if not isinstance(lc, dict):
        return {"learned": False, "why": "bad-registry"}
    is_new = key not in lc
    if is_new:
        lc[key] = {
            "detect": sig,
            "symptom": sig,
            "fix": fixtext[:800],
            "source_tool": slug,
            "verified": True,
            "learned": _t.strftime("%Y-%m-%d"),
            "uses": 0,
        }
        if len(lc) > 60:  # bound build_knowledge growth (drop oldest)
            # verified (oracle-confirmed flywheel) entries are NEVER dropped ahead of an
            # unverified one, regardless of date -- mirrors determinex_pb_absorb._bound_and_write.
            # Learned entries in this registry are all verified=True by construction (this function
            # is the only writer of `verified: True`), so in practice this only ever drops by date;
            # the sort key stays defensive in case a future writer ever mixes in verified=False rows.
            drop_order = sorted(
                lc, key=lambda x: (bool(lc[x].get("verified")), str(lc[x].get("learned", "")))
            )
            for k in drop_order[: len(lc) - 60]:
                lc.pop(k, None)
    else:  # seen before -> bump the use count
        lc[key]["uses"] = int(lc[key].get("uses", 0)) + 1
    try:
        kp.write_text(_json.dumps(kn, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as e:
        return {"learned": False, "why": f"kn-write: {e}"}
    return {"learned": is_new, "key": key, "signature": sig, "uses": lc[key].get("uses", 0)}


def build_fix_prompt(slug: str, compile_sh: str, failures: list) -> str:
    """The model's task: emit a CORRECTED compile.sh (from-source build only, no
    answer-key fallback) that makes the failing tests pass. Failures give the why.
    Grounded in the accumulated build-class knowledge so the FIRST candidate is informed."""
    lines = [
        f"You are fixing the ProgramBench build for `{slug}`. The tool is built FROM SOURCE",
        "by compile.sh inside its reference image; tests then run against the built binary.",
        "Output ONLY the full corrected compile.sh (no prose, no fences). It MUST build from",
        "source (never copy/fallback to a shipped prebuilt binary -- that is disqualified).",
        "",
        "LEGITIMATE FIXES ONLY -- the following are DISQUALIFIED (auto-rejected, not a solve):",
        "  - rewriting/substituting the binary's OUTPUT in a conftest to match the golden",
        "  - branching on the test name (PYTEST_CURRENT_TEST) to return per-test output",
        "  - capping/ignoring test collection (del items[N:], collect_ignore of real tests)",
        "  - embedding the expected/golden bytes. Fix the ROOT CAUSE: a build flag, toolchain",
        "  version, locale/timezone/clock, SIMD/scalar codepath, or an ENV the reference used.",
        "",
    ]
    _ftext = "\n".join(
        (getattr(f, "name", "") or "") + ": " + (getattr(f, "text", "") or "")
        for f in (failures or [])
    )[:3000]
    lines += _build_knowledge_playbook(_ftext)
    lines += [
        "Current compile.sh:",
        "----",
        compile_sh.strip(),
        "----",
        "",
        "Failing tests (fix the root cause -- often a build flag / toolchain / output format):",
    ]
    for f in (failures or [])[:12]:
        name = getattr(f, "name", "") or getattr(f, "test_id", "?")
        txt = (getattr(f, "text", "") or "")[:240].replace("\n", " ")
        lines.append(f"  - {name}: {txt}")
    return "\n".join(lines)


def clean_candidate(text: str) -> str:
    """Output-contract enforcement: extract a runnable shell script from raw model output.
    Small models wrap code in markdown fences (```sh ... ```) and add prose despite being
    told not to -- a fenced candidate makes compile.sh start with '```sh' => malformed build
    => the eval fast-fails (the observed pipr ~0s). Strip fences + any prose before the
    shebang/first real shell line so the candidate is a valid compile.sh."""
    if not text:
        return text
    t = text.strip()
    # pull the contents of the FIRST fenced block if present (```sh ... ``` or ``` ... ```)
    if "```" in t:
        import re

        m = re.search(r"```(?:sh|bash|shell)?\s*\n(.*?)```", t, re.DOTALL)
        if m:
            t = m.group(1)
        else:  # unterminated fence -> drop the fence marker line
            t = re.sub(r"^```[a-zA-Z]*\s*\n?", "", t).replace("```", "")
    t = t.strip()
    # drop any leading prose before the first shell line (shebang / set / export / a command)
    lines = t.split("\n")
    for i, ln in enumerate(lines):
        s = ln.strip()
        if (
            s.startswith("#!")
            or s.startswith(("set ", "export ", "cd ", "if ", "for "))
            or "=" in s.split(" ")[0]
        ):
            t = "\n".join(lines[i:])
            break
    if not t.lstrip().startswith("#!"):  # ensure a shebang so `sh compile.sh` is well-formed
        t = "#!/bin/sh\n" + t.lstrip()
    return t.strip() + "\n"


def amplified_fix(
    slug: str,
    compile_sh: str,
    failures: list,
    generate: GenerateFn,
    eval_fn: EvalFn,
    k: int = 6,
    rounds: int = 2,
) -> SearchResult:
    """Best-of-K verified fix search. `generate(prompt,temp)->candidate compile.sh`;
    `eval_fn(candidate)->PB eval dict`. Returns a SearchResult whose .solved is True
    ONLY when the oracle confirmed a full lock; otherwise the Adjudicator's next_moves.
    Model output is sanitized (clean_candidate) so fenced/prose-wrapped replies still yield
    a valid compile.sh -- the candidate stored & verified is the cleaned script."""

    def clean_generate(prompt: str, temperature: float) -> str:
        return clean_candidate(generate(prompt, temperature))

    def verify(candidate: str) -> FixOracleResult:
        # LEGITIMACY GATE (before the eval -- cheap, and the WHOLE point of doing Phase 2
        # right): a model maximizing oracle-pass will happily GAME -- rewrite the binary's
        # output to match goldens, route on the test name, cap collection. pb_override_scan
        # catches exactly those (red_literal_output_substitution / collection_cap /
        # collect_ignore / modifyitems / golden_fixture_write). Reject a RED candidate as a
        # NON-solve so verified-search never "clears a ceiling" by gaming.
        try:
            from pb_override_scan import classify_compile_sh

            verdict, reasons = classify_compile_sh(candidate)
            if str(verdict).upper().startswith("RED") or any(
                g in " ".join(map(str, reasons or [])).lower()
                for g in (
                    "output_substitution",
                    "collection_cap",
                    "collect_ignore",
                    "modifyitems",
                    "golden_fixture_write",
                    "pytest_current_test",
                )
            ):
                return FixOracleResult(
                    passed=False,
                    failures=[
                        _Failure(
                            "gaming",
                            "illegitimate-fix",
                            f"compile.sh RED (gaming): {(reasons or [])[:3]}",
                        )
                    ],
                )
        except Exception:
            pass
        try:
            data = eval_fn(candidate)
        except Exception as e:  # an eval error is not a solve
            return FixOracleResult(passed=False, failures=[_Failure("eval", "eval-error", str(e))])
        return adapt_eval(data or {})

    prompt = build_fix_prompt(slug, compile_sh, failures)
    return VerifiedSearch(verify, k=k, rounds=rounds).solve(clean_generate, prompt)


# ---- live wiring helpers (opt-in; injected so the core stays model/transport agnostic) ----
def make_hetzner_eval_fn(slug: str, base_tarball: Path, workdir: Path | None = None) -> EvalFn:
    """Live oracle: write a candidate compile.sh into a repack of base_tarball, run the
    Hetzner eval (reuses pb_eval_unified.run_hetzner_eval -- the sound, provenance-checked
    harness), return its eval dict. Each call is a real build+test (expensive, authoritative)."""
    import shutil
    import tarfile
    import tempfile

    import pb_eval_unified as U

    def eval_fn(candidate_compile_sh: str) -> dict:
        wd = Path(workdir or tempfile.mkdtemp(prefix="pbfix_"))
        cand_tar = wd / "candidate.tar.gz"
        # repack base tarball, swapping in the candidate compile.sh (drop any shipped ELF too)
        with tarfile.open(base_tarball, "r:gz") as src, tarfile.open(cand_tar, "w:gz") as dst:
            for m in src.getmembers():
                low = m.name.lower()
                if low.endswith("compile.sh"):
                    continue  # replace below
                if m.isfile() and m.size > 2_000_000:
                    ef = src.extractfile(m)
                    if ef is not None and ef.read(4) == b"\x7fELF":
                        continue  # never ship an answer-key binary into the candidate
                dst.addfile(m, src.extractfile(m) if m.isfile() else None)
            info = tarfile.TarInfo("./compile.sh")
            data = candidate_compile_sh.encode("utf-8")
            info.size = len(data)
            info.mode = 0o755
            import io

            dst.addfile(info, io.BytesIO(data))
        # ON the eval box use LOCAL docker (run_hetzner_eval would SSH to our own IP and fail);
        # only SSH to Hetzner when driving remotely (Windows). Lets the amplified fix run in the
        # box-resident autodrive.
        _runner = U.run_local_eval if Path("/root/ProgramBench").is_dir() else U.run_hetzner_eval
        data = _runner(slug, cand_tar)
        shutil.rmtree(wd, ignore_errors=True)
        return data or {}

    return eval_fn


if __name__ == "__main__":  # tiny self-demo with a mock weak model + sound oracle
    import random

    GOLDEN = "#!/bin/sh\nexport GOTOOLCHAIN=auto\ngo build -o /usr/local/bin/x .\n"

    def mock_oracle(candidate: str) -> dict:
        ok = "GOTOOLCHAIN=auto" in candidate  # the one correct fix
        n = 100
        return {
            "test_results": [
                {"status": "passed" if ok else "failed", "name": f"t{i}"} for i in range(n)
            ]
        }

    def weak_model(prompt: str, temp: float) -> str:  # right ~20% of the time
        return GOLDEN if random.random() < 0.2 else "#!/bin/sh\ngo build .\n"

    r = amplified_fix("demo__tool", "#!/bin/sh\ngo build .\n", [], weak_model, mock_oracle, k=15)
    print(f"solved={r.solved} samples={r.total_samples} proof={r.proof[:60]}")
    raise SystemExit(0 if r.solved else 1)
