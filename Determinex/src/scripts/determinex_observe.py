#!/usr/bin/env python3
"""
determinex_observe.py -- binary-observation -> SOUND oracle (the reimplementation front end)
=========================================================================================
ProgramBench is reverse-engineering: you may RUN the reference binary (execute-only)
but never read it. This module runs the reference binary on a battery of probes, records
the EXACT observed (stdout, stderr, returncode) per probe, and turns those observations
into a sound oracle: a candidate reimplementation PASSES only if it reproduces the
observed behavior on every probe. We assert ONLY what we actually observed -- never an
un-probed case -- so the oracle is sound (no slop). This is the missing front end that
lets `determinex_verified_search` amplify a from-scratch reimplementation.

  observe_in_image(image, exe, probes)  -> [Observation]   (runs reference in the task image)
  build_probes(help_text, inputs)       -> [Probe]         (universal + doc-mined + inputs)
  make_verify(observations, runner)     -> verify(code)->OracleResult  (sound)

Soundness contract (load-bearing): a candidate is `solved` ONLY with a passing
OracleResult. Garbage oracle in -> confident garbage out; we only ever assert observed
deterministic I/O. Volatile fields (paths/pids/timestamps) are out of scope for the MVP --
probes are chosen to be deterministic.
"""

from __future__ import annotations

import dataclasses
import re
import shlex
import subprocess
import tempfile
from pathlib import Path


@dataclasses.dataclass
class Probe:
    """One observable invocation. `argv` excludes the program name; `stdin` is bytes-or-None;
    `files` maps a filename -> content to materialize in the cwd before running.
    `serve` maps a URL path -> content; when set, the oracle PROVISIONS a loopback HTTP server
    serving it (the system has Docker loopback + can run http.server) so URL-fetching tools can
    be probed for real. Use the `{URL}` token in argv -> it resolves to http://127.0.0.1:PORT."""

    name: str
    argv: list[str]
    stdin: str | None = None
    files: dict[str, str] = dataclasses.field(default_factory=dict)
    serve: dict[str, str] = dataclasses.field(default_factory=dict)
    # BINARY/domain file inputs: filename -> base64(content). Materialized byte-exact in BOTH the
    # reference container and the candidate run, so a tool whose real input is a binary/format
    # file (ELF, image, archive, source) gets a FAITHFUL, content-controlled probe. JSON-safe.
    bin_files: dict[str, str] = dataclasses.field(default_factory=dict)
    # ENVIRONMENT: env vars the test sets (NO_COLOR, HEXYL_COLOR_*, COLUMNS, ...). Many tools'
    # output is env-sensitive; without replaying these the reference observation is WRONG.
    env: dict[str, str] = dataclasses.field(default_factory=dict)


# Loopback port the oracle provisions an HTTP server on for URL-fetch probes. Works even under
# docker --network none (loopback interface is always present) and on the host for verify.
_SERVE_PORT = 8731


@dataclasses.dataclass
class Observation:
    probe: Probe
    stdout: str
    stderr: str
    returncode: int
    # ASSERTION-AWARE ORACLE (2026-07-03): when this probe came from an OFFICIAL test
    # whose grading is CONTAINS / rc-only (not exact stdout), carry that here so the
    # oracle checks what the test ACTUALLY checks -- not stricter. `None` = exact match
    # against the observed reference bytes (the sound default for fuzz-discovered probes
    # that have no official test defining a looser criterion). Shape:
    #   {"expect_in": [str, ...], "expect_rc": int|None, "expect_stdout": str|None}
    # The reimpl was demanding byte-exact reproduction of clap error banners the official
    # test only substring-matched -> every tool plateaued on its ~15 hardest error cases.
    assertion: dict | None = None


def _stdin_bytes(value: str | None) -> bytes | None:
    if value is None:
        return None
    return value.encode("utf-8", errors="surrogateescape")


def _decode_stream(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _completed_text(proc: subprocess.CompletedProcess) -> tuple[str, str]:
    return _decode_stream(proc.stdout), _decode_stream(proc.stderr)


def aligned_diff(expected: str, got: str, max_lines: int = 24) -> str:
    """Make the oracle and model 'talk': show the candidate's own lines aligned to the
    EXPECTED lines so the per-line transformation is explicit (YOU: <x>  ==>  EXPECT: <y>).
    A small model that has the right STRUCTURE but wrong SURFACE SYNTAX can learn the
    transformation rule from the correspondence far more reliably than reproducing a
    format spec from scratch. Uses difflib to align, so insert/delete/replace are visible."""
    import re as _re

    exp = expected.splitlines()
    g = got.splitlines()

    def toks(s: str) -> set:
        return set(_re.findall(r"[A-Za-z0-9_]+", s))

    used: set[int] = set()
    rows: list[str] = []
    for el in exp:
        # find the candidate line that shares the most tokens (content-anchored, so we
        # never mispair by position when the candidate is missing/extra lines)
        et = toks(el)
        best_i, best_score = -1, 0.0
        for i, gl in enumerate(g):
            if i in used:
                continue
            gt = toks(gl)
            if not et and not gt:
                sc = 1.0
            else:
                inter = len(et & gt)
                sc = inter / max(1, len(et | gt))
            if sc > best_score:
                best_score, best_i = sc, i
        if best_i >= 0 and best_score >= 0.34:
            used.add(best_i)
            if g[best_i] == el:
                rows.append(f"  ok   | {el}")
            else:
                rows.append(f"  FIX  | YOUR {g[best_i]!r}  ==> MUST BE {el!r}")
        else:
            rows.append(f"  ADD  | (you are missing this line)  ==> {el!r}")
        if len(rows) >= max_lines:
            rows.append("  ... (more)")
            break
    extra = [g[i] for i in range(len(g)) if i not in used]
    for e in extra[:4]:
        rows.append(f"  DROP | YOUR {e!r}  ==> (should not be output)")
    return "\n".join(rows)


@dataclasses.dataclass
class Failure:
    """Rich, ACTIONABLE failure so the verified-search feedback loop can teach the model:
    carries the input + the EXPECTED observed output, not just 'differs'. VerifiedSearch
    reads .name and .text."""

    name: str
    text: str
    test_id: str = ""


@dataclasses.dataclass
class OracleResult:
    passed: bool
    failures: list = dataclasses.field(default_factory=list)  # list[Failure]
    n_total: int = 0
    n_pass: int = 0
    # score = fraction of EXPECTED output lines reproduced, summed over probes with
    # non-empty expected output (GENUINE behavior). Empty-output/error probes contribute
    # 0 lines, so a do-nothing candidate scores ~0 — the search gradient points at real
    # behavior, not at trivially matching empties. This is the SELECTION signal.
    score: float = 0.0
    n_genuine: int = 0  # probes with non-empty expected stdout
    n_genuine_pass: int = 0  # genuine probes reproduced byte-exact (the HONEST headline)


# --------------------------------------------------------------------------- probes
_UNIVERSAL = [
    Probe("help_long", ["--help"]),
    Probe("help_short", ["-h"]),
    Probe("version_long", ["--version"]),
    Probe("version_short", ["-V"]),
    Probe("no_args", []),
]

_FLAG_RE = None


def mine_flags(help_text: str) -> list[str]:
    """Pull long flags (--foo) out of help text, deduped, excluding help/version."""
    import re

    global _FLAG_RE
    if _FLAG_RE is None:
        _FLAG_RE = re.compile(r"(?<![\w-])--[a-zA-Z][a-zA-Z0-9-]+")
    seen, out = set(), []
    for m in _FLAG_RE.findall(help_text or ""):
        if m in ("--help", "--version") or m in seen:
            continue
        seen.add(m)
        out.append(m)
    return out


# Generic input battery for AUTO probe-generation: the system discovers what input format
# a tool accepts by trying these against the reference binary and keeping the ones that
# produce real output. Replaces hand-crafted per-tool probes -> the system self-builds its
# oracle (the scale unlock). Covers JSON (the common PB case) + CSV/TSV/text/numbers.
_GENERIC_BATTERY: dict[str, str] = {
    "json_obj": '{"a":1,"b":[true,"x"],"c":{"d":2}}',
    "json_array": "[1,2,3]",
    "json_arr_objs": '[{"a":1},{"b":2}]',
    "json_deep": '{"a":{"b":{"c":[1,[2,3]]}}}',
    "json_types": '{"s":"hi","i":42,"neg":-7,"f":1.5,"t":true,"ff":false,"n":null}',
    "json_empty": '{"o":{},"a":[]}',
    "json_speckeys": '{"a-b":1,"a.b":2,"a b":3,"123":4}',
    "csv": "name,age\nalice,30\nbob,25\n",
    "tsv": "name\tage\nalice\t30\n",
    "text": "hello world\nfoo bar\nbaz qux\n",
    "numbers": "3\n1\n4\n1\n5\n",
}


# Edge / malformed / boundary inputs: these drive the EXIT-CODE and ERROR-PATH coverage that
# the happy-path generic battery misses (malformed JSON -> exit 3, etc.). A probe is kept when
# the reference does something DISTINCT (real stdout OR a distinct non-zero exit) -- so the
# oracle asserts error behavior, not just success behavior.
_EDGE_BATTERY: dict[str, str] = {
    "empty": "",
    "whitespace": "   \n\t\n  ",
    "json_malformed": '{"a":1,',
    "json_trailing_garbage": '{"a":1}garbage',
    "json_bare_string": '"hello"',
    "json_bare_number": "42",
    "json_bare_bool": "true",
    "json_bare_null": "null",
    "json_unicode": '{"emoji":"\U0001f600","accent":"café","tabbed":"a\tb"}',
    "json_num_reprs": '{"exp":1.2e10,"negzero":-0,"big":12345678901234567890,"frac":0.5}',
    "json_deep_array": "[[[[1]]]]",
    "json_dup_keys": '{"a":1,"a":2}',
    "text_no_trailing_nl": "no trailing newline",
    "text_blank_lines": "a\n\n\nb\n",
    # CSV-domain edges: unicode/emoji display width, quote/comma/newline parsing, empty + ragged
    # cells -- the behavior surface of a table/CSV tool that the JSON-shaped battery misses.
    "csv_unicode": "名前,年齢\n中文,30\nab,5\n",
    "csv_emoji": "a,b\n\U0001f600x,y\nz,w\n",
    "csv_quoted_comma": 'a,b\n"x,y",z\n1,2\n',
    "csv_quoted_newline": 'a,b\n"x\ny",z\n1,2\n',
    "csv_quoted_quote": 'a,b\n"he said ""hi""",z\n1,2\n',
    "csv_empty_cells": "a,b,c\n,,\n1,,3\n",
    "csv_trailing_comma": "a,b,c\n1,2,\n4,5,6\n",
    "csv_wide_mix": "x,y\nééé,1\n中文字,2\n",
}


# File extension per battery key so file-arg discovery works for tools that dispatch on
# extension (.json/.csv/.tsv) rather than content sniffing.
def _ext_for(name: str) -> str:
    if name.startswith("json"):
        return ".json"
    if name == "csv":
        return ".csv"
    if name == "tsv":
        return ".tsv"
    return ".txt"


def _informative(o: Observation) -> bool:
    """Keep a probe as oracle signal if the reference produced real stdout OR exhibited a
    distinct non-zero exit (error-path behavior worth asserting). 124 is our timeout sentinel."""
    if o.returncode == 124:
        return False
    return bool(o.stdout.strip()) or o.returncode != 0


def auto_inputs(image: str, exe: str, *, max_keep: int = 22, timeout: int = 20) -> list[Probe]:
    """AUTO-build a faithful oracle with NO hand-crafted probes. Per tool:
      1. DISCOVER format+channel: try every generic+edge body via BOTH stdin and a file arg.
      2. KEEP only informative probes (real stdout, or a distinct error exit -> exit-code cov).
      3. NONDETERMINISM GUARD: re-run each kept probe; drop any whose reference output isn't
         stable (timestamps/pids/random) -- baking a volatile run makes the probe unsatisfiable.
      4. DEDUP by (stdout, returncode) signature: every kept probe must ADD discrimination,
         not duplicate an existing behavior.
    This is the line between 'a human wrote gron's battery' and 'the system self-builds it'."""
    cand: list[Probe] = []
    for batt in (_GENERIC_BATTERY, _EDGE_BATTERY):
        for name, body in batt.items():
            ext = _ext_for(name)
            cand.append(Probe(f"stdin_{name}", [], stdin=body))
            cand.append(Probe(f"file_{name}", [f"{name}{ext}"], files={f"{name}{ext}": body}))
    # DOMAIN faithfulness: real harvested files (ELF/config) for binary/format tools. These now go
    # through the SAME determinism + informative validation as the battery -- previously they were
    # appended UNVALIDATED, baking spurious/nondeterministic captures into the oracle (e.g. csview
    # showing a one-off exit=1 on /etc/hostname that the live reference actually renders exit 0).
    harvest_names: set = set()
    try:
        for hp in harvest_real_inputs(image, exe):
            harvest_names.add(hp.name)
            cand.append(hp)
    except Exception:
        pass
    obs1 = observe_in_image(image, exe, cand, timeout=timeout)
    informative = [o for o in obs1 if _informative(o)]
    # determinism re-run, only on the informative subset (halves the cost)
    obs2 = observe_in_image(image, exe, [o.probe for o in informative], timeout=timeout)
    second = {o.probe.name: o for o in obs2}
    kept: list[Probe] = []
    seen_sig: set = set()
    n_battery = 0
    for o in informative:
        o2 = second.get(o.probe.name)
        if o2 is None or o2.stdout != o.stdout or o2.returncode != o.returncode:
            continue  # nondeterministic reference -> not a sound probe (drops spurious harvests)
        sig = (o.stdout, o.returncode)
        if sig in seen_sig:
            continue  # adds no discrimination
        # harvested real-file probes are domain-critical -> kept beyond the battery cap, but
        # only after passing the same determinism + informative gate.
        is_harvest = o.probe.name in harvest_names
        if not is_harvest:
            if n_battery >= max_keep:
                continue
            n_battery += 1
        seen_sig.add(sig)
        kept.append(o.probe)
    return kept


def discrimination_estimate(observations: list[Observation], *, runner=None) -> dict:
    """How FAITHFUL is this oracle? Run a set of trivially-WRONG mutant candidates; a good
    oracle rejects all of them. Returns {rejected, total, ratio} -- a number for the
    local<->official gap we were flying blind on. ratio<1.0 means a do-nothing/echo program
    can slip through -> the oracle needs more discriminating probes before we trust a pass."""
    if runner is None:
        runner = _run_candidate_py
    mutants = {
        "do_nothing": "import sys\n",
        "echo_stdin": "import sys\nsys.stdout.write(sys.stdin.read())\n",
        "print_empty_line": "print()\n",
        "always_exit0": "import sys\nsys.exit(0)\n",
        "fixed_string": "print('x')\n",
    }
    verify = make_verify(observations, runner=runner)
    rejected = 0
    for code in mutants.values():
        if not verify(code).passed:
            rejected += 1
    return {
        "rejected": rejected,
        "total": len(mutants),
        "ratio": rejected / len(mutants) if mutants else 1.0,
    }


def propose_probes(
    help_text: str, docs: str, sample_inputs: list[Probe], generate, n: int = 40
) -> list[Probe]:
    """COMPREHENSIVE EXPLORATION (the frontier-agent half, made cheap + then verified): ask the
    (cheap) model to read the tool's --help/docs and propose N DIVERSE invocations exercising
    distinct behaviors -- crucially FLAG VALUES (e.g. `--style rounded`, `--header-align center`)
    and flag combinations that a fixed battery misses. Each becomes a probe fed the representative
    input. We then OBSERVE the reference on them (ground truth) and verified-search proves the
    candidate matches -- coverage like an explorer, correctness like only a compiler oracle gives."""
    sample = sample_inputs[0] if sample_inputs else None
    body = (
        sample.stdin
        if sample and sample.stdin
        else (next(iter(sample.files.values())) if sample and sample.files else "a,b\n1,2\n")
    )
    prompt = (
        "You are exhaustively exploring a CLI tool to map ALL its behaviors. The tool's --help:\n"
        f"{help_text[:1800]}\n\nDocs excerpt:\n{docs[:1200]}\n\n"
        f"The input below is piped on STDIN:\n{body[:300]}\n\n"
        f"List {n} DIVERSE invocations (flags only, after the program name) that exercise DISTINCT "
        "behaviors. USE FLAG VALUES (e.g. `--style rounded`, `--style ascii2`, `--header-align "
        "center`, `--delimiter ;`), FLAG COMBINATIONS, and boundary flags. One invocation per "
        "line, ONLY the flag tokens (e.g. `--style rounded` or `--number --tsv`). No prose."
    )
    try:
        out = generate(prompt, 0.4)
    except Exception:
        return []
    probes: list[Probe] = []
    seen: set = set()
    for line in (out or "").splitlines():
        line = line.strip().lstrip("$").strip().strip("`").strip()
        if line.lower().startswith("executable"):
            line = line[len("executable") :].strip()
        if not line or line.startswith("#") or " " not in line and not line.startswith("-"):
            if not line.startswith("-"):
                continue
        try:
            argv = shlex.split(line)
        except Exception:
            continue
        # models sometimes echo the program name despite explicit instructions not to
        # (e.g. "gron -u" instead of "-u") -- Probe.argv must exclude it (see Probe docstring)
        # or the reference binary treats it as a positional arg (a bogus input filename) and
        # every downstream station scores 0.00 trying to match a nonsense filesystem error.
        while argv and not argv[0].startswith("-"):
            argv.pop(0)
        if not argv or not any(a.startswith("-") for a in argv):
            continue
        key = tuple(argv)
        if key in seen:
            continue
        seen.add(key)
        probes.append(Probe(f"explore_{len(probes)}", argv, stdin=body))
        if len(probes) >= n:
            break
    return probes


def harvest_real_inputs(
    image: str, exe: str, *, max_files: int = 5, max_bytes: int = 40000, timeout: int = 60
) -> list[Probe]:
    """DOMAIN faithfulness: a tool whose real input is a binary/format file (ELF, image, archive,
    source) can't be probed by the generic JSON/text battery. Harvest a few small REAL files from
    the image (a small ELF binary, configs, the tool's own executable) and feed their EXACT bytes
    (content-controlled, base64) as file-arg probes -- so the reference and the candidate both see
    identical real-domain input. This is the fix for the elfcat-class optimism gap (8 thin probes
    -> real ELF parsing). Legitimate: reads the image filesystem, never the held-out tests."""
    import base64 as _b64

    # candidate real files: small binaries (ELF), text/config, and the tool's own executable.
    script = (
        "for f in /bin/true /usr/bin/true /bin/echo /etc/hostname /etc/os-release "
        "/etc/passwd " + shlex.quote(exe) + " $(ls -S /bin/* /usr/bin/* 2>/dev/null | tail -5); do "
        '[ -f "$f" ] || continue; '
        f'sz=$(wc -c < "$f" 2>/dev/null || echo 0); '
        f'if [ "$sz" -gt 0 ] && [ "$sz" -le {max_bytes} ]; then '
        'echo "===F:$(basename "$f"):$sz"; base64 "$f" 2>/dev/null | tr -d \'\\n\'; echo; fi; done'
    )
    try:
        r = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "sh",
                image,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return []
    probes: list[Probe] = []
    lines = (r.stdout or "").splitlines()
    seen_b64: set = set()
    i = 0
    while i < len(lines) and len(probes) < max_files:
        if lines[i].startswith("===F:") and i + 1 < len(lines):
            name = lines[i][5:].split(":")[0] or "f"
            b64 = lines[i + 1].strip()
            try:
                if b64 and len(b64) > 8 and b64 not in seen_b64 and _b64.b64decode(b64):
                    seen_b64.add(b64)
                    fn = f"in_{name}"
                    probes.append(Probe(f"real_{name}", [fn], bin_files={fn: b64}))
            except Exception:
                pass
            i += 2
        else:
            i += 1
    return probes


def flag_value_map(help_text: str) -> dict[str, list[str]]:
    """Parse --help into {flag: [values]} per OPTION BLOCK (clap/argparse layout: an indented
    header line `  -s, --style <STYLE>` followed by indented description lines until the next
    option). Returns, for each flag:
      * [values]  -- an enumerable value flag (`[possible values: a, b, c]`, wraps allowed)
      * []        -- a boolean flag (no `<VALUE>` placeholder in its header)
    Value-taking flags with UNKNOWN values (e.g. `--delimiter <DELIMITER>`, no enum) are OMITTED
    (a bare probe would error; the model proposer covers those). This scopes possible-values to
    the RIGHT flag and survives line-wrapped value lists -- so `--style {none..grid}` and
    `--*-align {left,center,right}` are probed SYSTEMATICALLY, not by guesswork."""
    import re

    lines = (help_text or "").splitlines()
    hdr_re = re.compile(r"^\s+(?:-\w,\s*)?(--[a-zA-Z][\w-]+)")
    blocks: list[tuple[str, str, str]] = []  # (flag, header_line, block_text)
    cur_flag = None
    cur: list[str] = []
    for ln in lines:
        m = hdr_re.match(ln)
        if m:
            if cur_flag:
                blocks.append((cur_flag, cur[0], "\n".join(cur)))
            cur_flag, cur = m.group(1), [ln]
        elif cur_flag is not None and (ln.strip() == "" or ln.startswith(" ")):
            cur.append(ln)  # indented continuation = this flag's description
        elif cur_flag is not None:
            blocks.append((cur_flag, cur[0], "\n".join(cur)))
            cur_flag, cur = None, []
    if cur_flag:
        blocks.append((cur_flag, cur[0], "\n".join(cur)))
    out: dict[str, list[str]] = {}
    for flag, header, block in blocks:
        if flag in ("--help", "--version"):
            continue
        m = re.search(r"possible values?:?\s*([^\]]+)\]", block, re.I | re.S)
        if m:
            seen: set[str] = set()
            vals = []
            for v in re.split(r"[,\s|]+", m.group(1)):
                v = v.strip().strip("\"'`").rstrip(".")
                if (
                    v
                    and re.fullmatch(r"[A-Za-z0-9][\w-]*", v)
                    and v.lower() not in ("default", "values")
                    and v not in seen
                ):
                    seen.add(v)
                    vals.append(v)
            out[flag] = vals[:10]
        elif "<" not in header and "=" not in header:
            out[flag] = []  # boolean flag
        # else: value-taking with unknown values -> omit (model proposer covers it)
    return out


def _representative_inputs(inputs: list[Probe], n: int = 3) -> list[Probe]:
    """Pick up to n distinct, non-empty input probes to pair flags against -- prefer FILE-arg
    probes (most CLIs take a file) with content, distinct by their file body / stdin."""
    file_ins = [p for p in inputs if p.files and any((c or "").strip() for c in p.files.values())]
    stdin_ins = [p for p in inputs if p.stdin and p.stdin.strip()]
    reps, seen = [], set()
    for p in file_ins + stdin_ins:
        sig = (tuple(sorted(p.files.items())), p.stdin)
        if sig in seen:
            continue
        seen.add(sig)
        reps.append(p)
        if len(reps) >= n:
            break
    return reps


def _heuristic_values(flag: str) -> list[str]:
    """For a value-taking flag whose values aren't enumerable from --help, guess sensible probe
    values by NAME so its behavior gets covered (numeric flags -> 0/2, delimiter -> ;). Keeps the
    auto-oracle from leaving padding/indent/delimiter/sniff as silent holes."""
    n = flag.lower()
    if any(
        w in n
        for w in (
            "pad",
            "indent",
            "width",
            "sniff",
            "limit",
            "depth",
            "count",
            "num",
            "rows",
            "cols",
            "size",
            "max",
            "min",
        )
    ):
        return ["0", "2"]
    if any(w in n for w in ("delim", "sep", "separator")):
        return [";"]
    return []  # non-numeric unknown -> leave to the model proposer


def _flag_probe(flag: str, value: str | None, rep: Probe | None) -> Probe:
    """Combine a flag (+optional value) with a representative input probe."""
    argv = [flag] + ([value] if value is not None else [])
    name = f"flag{flag}" + (f"={value}" if value is not None else "")
    if rep is None:
        return Probe(name, argv)
    return Probe(
        f"{name}|{rep.name}", argv + list(rep.argv), rep.stdin, dict(rep.files), dict(rep.serve)
    )


def build_probes(
    help_text: str = "",
    inputs: list[Probe] | None = None,
    max_flags: int = 24,
    max_total: int = 220,
) -> list[Probe]:
    """Universal probes + SYSTEMATIC flag-combinatorial coverage (each flag x each enumerated
    value x representative inputs, + bounded flag PAIRS for the two richest value-flags) + the
    caller's input probes. The flag x value x input grid is the behavior surface a fixed battery
    and model-guessing both miss -- it auto-covers e.g. --style {none..grid} x --*-align {l,c,r}
    x {plain,cjk,wide} inputs, captured byte-exact from the reference. The compiler oracle then
    verifies a candidate against ALL of it."""
    probes = list(_UNIVERSAL)
    inputs = inputs or []
    reps = _representative_inputs(inputs, n=3)
    fvmap = flag_value_map(help_text)
    flag_probes: list[Probe] = []
    for flag, values in list(fvmap.items())[:max_flags]:
        targets = reps or [None]
        if values:
            for v in values:
                for rep in targets:
                    flag_probes.append(_flag_probe(flag, v, rep))
        else:
            for rep in targets:
                flag_probes.append(_flag_probe(flag, None, rep))
    # VALUE-flags with UNKNOWN enum (padding/indent/delimiter/sniff/width): heuristic values by
    # flag name, so numeric/delimiter behaviors get probed too (else they are a silent oracle hole
    # = the optimism gap). ADDS coverage, never dilutes the core.
    known = set(fvmap)
    for flag in mine_flags(help_text)[:max_flags]:
        if flag in known:
            continue
        hv = _heuristic_values(flag)
        for v in hv:
            for rep in reps or [None]:
                flag_probes.append(_flag_probe(flag, v, rep))
    # CROSS-COMBOS: boolean flags combined with each other + with the first value-flag, on one
    # input -- official suites test flag interactions (e.g. --number --no-headers, style+number).
    bools = [f for f, v in fvmap.items() if not v][:4]
    vflag = next((f for f, v in fvmap.items() if v), None)
    if reps:
        rep = reps[0]
        for i in range(len(bools)):
            for j in range(i + 1, len(bools)):
                flag_probes.append(
                    Probe(
                        f"combo{bools[i]},{bools[j]}",
                        [bools[i], bools[j], *rep.argv],
                        rep.stdin,
                        dict(rep.files),
                    )
                )
            if vflag and fvmap[vflag]:
                v = fvmap[vflag][min(1, len(fvmap[vflag]) - 1)]
                flag_probes.append(
                    Probe(
                        f"combo{bools[i]},{vflag}={v}",
                        [bools[i], vflag, v, *rep.argv],
                        rep.stdin,
                        dict(rep.files),
                    )
                )
    # bounded flag PAIRS: cross the two richest value-flags (e.g. style x align) on one input
    vflags = [f for f, v in fvmap.items() if v][:2]
    if len(vflags) == 2 and reps:
        (f1, f2), rep = vflags, reps[0]
        for v1 in fvmap[f1][:4]:
            for v2 in fvmap[f2][:3]:
                flag_probes.append(
                    Probe(
                        f"pair{f1}={v1},{f2}={v2}",
                        [f1, v1, f2, v2, *rep.argv],
                        rep.stdin,
                        dict(rep.files),
                    )
                )
    budget = max(0, max_total - len(probes) - len(inputs))
    probes += flag_probes[:budget]
    probes.extend(inputs)
    # URL-fetch coverage: if the tool documents URL/http input, PROVISION a loopback server and
    # probe the fetch path for real (success) + the failure path (dead port -> error exit). This
    # turns the "url_fetch" tests from an un-probeable ceiling into ordinary oracle signal.
    if re.search(r"\b(url|https?://|fetch)\b", (help_text or ""), re.I):
        body = '{"a":1,"b":[true,"x"],"c":{"d":2}}'
        probes.append(Probe("url_fetch_obj", ["{URL}/data.json"], serve={"data.json": body}))
        probes.append(Probe("url_fetch_array", ["{URL}/arr.json"], serve={"arr.json": "[1,2,3]"}))
        probes.append(Probe("url_refused", ["http://127.0.0.1:9/none.json"]))
    return probes


# --------------------------------------------------------------------------- observe
def _probe_script(p: Probe, exe: str, d: str) -> str:
    """Shell script for one probe inside the (already-running) container: materialize TEXT files
    byte-exact (base64), provision a loopback HTTP server for serve probes, then run exe. Binary
    bin_files are NOT inlined here -- they are `docker cp`-ed in (binary-clean, no cmdline limit)."""
    setup = f"rm -rf {d}; mkdir -p {d}; cd {d}\n"
    for fn, content in p.files.items():
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        setup += f"printf %s {shlex.quote(b64)} | base64 -d > {shlex.quote(fn)}\n"
    teardown = ""
    argv = [a.replace("{URL}", f"http://127.0.0.1:{_SERVE_PORT}") for a in p.argv]
    if p.serve:
        setup += "mkdir -p srv\n"
        for fn, content in p.serve.items():
            b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
            setup += f"printf %s {shlex.quote(b64)} | base64 -d > srv/{shlex.quote(fn)}\n"
        setup += (
            f"(cd srv && python3 -m http.server {_SERVE_PORT} --bind 127.0.0.1 "
            ">/dev/null 2>&1 &) ; sleep 1\n"
        )
        teardown = "\npkill -f http.server 2>/dev/null; true"
    return setup + shlex.join([exe, *argv]) + teardown


import base64  # noqa: E402  (module-level for _probe_script)


def observe_in_image(
    image: str, exe: str, probes: list[Probe], *, timeout: int = 20
) -> list[Observation]:
    """Run the reference binary `exe` inside `image` for each probe; capture exact I/O.

    THROUGHPUT: a fresh `docker run` costs ~4s of pure startup on Docker Desktop/WSL2, and there
    are ~100 probes/tool -> ~7 min/oracle (the real cause of every stall this session). So we
    start ONE persistent container and `docker exec` each probe (~0.3s) -> ~15x faster, measured.
    -i forwards stdin (load-bearing: without it stdin probes get EMPTY input -> wrong oracle).
    bin_files go in via `docker cp` (binary-clean, no cmdline-length / no Windows mount hang)."""
    import tempfile as _tf
    import uuid

    obs: list[Observation] = []
    if not probes:
        return obs
    cname = f"determinex_obs_{uuid.uuid4().hex[:12]}"
    keep_alive = max(600, timeout * len(probes) + 120)
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            cname,
            "--network",
            "none",
            "--entrypoint",
            "sh",
            image,
            "-c",
            f"sleep {keep_alive}",
        ],
        capture_output=True,
        text=True,
    )
    persistent = started.returncode == 0
    try:
        for i, p in enumerate(probes):
            d = f"/tmp/p{i}"
            script = _probe_script(p, exe, d)
            if p.env:  # replay the test's env vars (color/width/etc) -- else ref output is wrong
                env_prefix = "".join(f"export {k}={shlex.quote(v)}; " for k, v in p.env.items())
                script = env_prefix + script
            tmpdir = None
            try:
                if persistent:
                    if p.bin_files:  # cp binary inputs into the live container's probe dir
                        subprocess.run(
                            ["docker", "exec", cname, "sh", "-c", f"mkdir -p {d}"],
                            capture_output=True,
                        )
                        tmpdir = Path(_tf.mkdtemp(prefix="citcp_"))
                        for fn, b64 in p.bin_files.items():
                            hf = tmpdir / fn
                            hf.write_bytes(base64.b64decode(b64))
                            subprocess.run(
                                ["docker", "cp", str(hf), f"{cname}:{d}/{fn}"], capture_output=True
                            )
                    ex = ["docker", "exec", "-i", cname, "sh", "-c", script]
                    r = subprocess.run(
                        ex,
                        input=_stdin_bytes(p.stdin),
                        capture_output=True,
                        text=False,
                        timeout=timeout,
                    )
                else:  # fallback: per-probe docker run (Linux, or if -d failed)
                    s2 = script
                    for fn, b64 in p.bin_files.items():
                        s2 = (
                            f"printf %s {shlex.quote(b64)} | base64 -d > {d}/{shlex.quote(fn)}\n"
                            + s2
                        )
                    run1 = [
                        "docker",
                        "run",
                        "--rm",
                        "-i",
                        "--network",
                        "none",
                        "--entrypoint",
                        "sh",
                        image,
                        "-c",
                        s2,
                    ]
                    r = subprocess.run(
                        run1,
                        input=_stdin_bytes(p.stdin),
                        capture_output=True,
                        text=False,
                        timeout=timeout,
                    )
                stdout, stderr = _completed_text(r)
                obs.append(Observation(p, stdout, stderr, r.returncode))
            except subprocess.TimeoutExpired:
                if persistent:  # kill the hung inner process, keep the container for the rest
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            cname,
                            "sh",
                            "-c",
                            "pkill -f /workspace/executable 2>/dev/null; true",
                        ],
                        capture_output=True,
                    )
                obs.append(Observation(p, "", "<timeout>", 124))
            finally:
                if tmpdir:
                    _shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        if persistent:
            subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
    return obs


def is_tui_binary(image: str, exe: str) -> bool:
    """Cheap, no-pty pre-check: does the reference binary link a terminal-UI library?
    Ncurses/curses linkage is the reliable signal a plain (non-pty) probe capture will
    see nothing useful ("Error opening terminal: unknown" or a hang) -- route it to
    observe_tui_snapshot() instead of wasting ordinary probes on it."""
    try:
        r = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "sh",
                image,
                "-c",
                f"ldd {shlex.quote(exe)} 2>/dev/null || true",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return bool(re.search(r"ncurses|curses|tinfo|termcap", r.stdout, re.IGNORECASE))
    except Exception:
        return False


def observe_tui_snapshot(
    image: str,
    exe: str,
    argv_variants: list[list[str]] | None = None,
    *,
    duration: float = 1.2,
    timeout: int = 20,
) -> list[Observation]:
    """Capture what a TUI (ncurses/curses) reference binary ACTUALLY renders.

    THE GAP THIS CLOSES: observe_in_image()'s docker-exec probes have no pty and never set
    TERM, so any ncurses tool fails terminal setup immediately ("Error opening terminal:
    unknown") -- the automated reimpl loop has been building TUI candidates blind, never
    having seen one real frame of rendered output (discovered 2026-07-02 while hand-driving
    tty-clock: a manual pty capture showed the reference draws block-digit segments via
    `\\x1b[42m`-style color escapes, none of which ever reached the model through the normal
    observation path). Uses a REAL pty (python's pty.fork(), not docker's own -t flag, which
    was unreliable for ncurses setupterm()) with TERM=xterm, runs the binary for `duration`
    seconds, then SIGTERMs it and returns whatever it wrote. The raw escape-sequence bytes
    are the observation -- do not strip them; that IS the reference behavior being captured.
    """
    obs: list[Observation] = []
    variants = argv_variants or [[]]
    for argv in variants:
        py = (
            "import pty, os, time, select, signal, sys\n"
            "argv = " + repr([exe] + argv) + "\n"
            "pid, fd = pty.fork()\n"
            "if pid == 0:\n"
            "    os.environ['TERM'] = 'xterm'\n"
            "    try:\n"
            "        os.execv(argv[0], argv)\n"
            "    except Exception:\n"
            "        os._exit(127)\n"
            "else:\n"
            f"    time.sleep({duration})\n"
            "    try:\n"
            "        os.kill(pid, signal.SIGTERM)\n"
            "    except Exception:\n"
            "        pass\n"
            "    data = b''\n"
            "    deadline = time.time() + 1.0\n"
            "    while time.time() < deadline:\n"
            "        r, _, _ = select.select([fd], [], [], 0.2)\n"
            "        if not r:\n"
            "            break\n"
            "        try:\n"
            "            chunk = os.read(fd, 65536)\n"
            "        except OSError:\n"
            "            break\n"
            "        if not chunk:\n"
            "            break\n"
            "        data += chunk\n"
            "    _, status = os.waitpid(pid, os.WNOHANG)\n"
            "    sys.stdout.buffer.write(data)\n"
        )
        try:
            r = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-e",
                    "TERM=xterm",
                    "--entrypoint",
                    "python3",
                    image,
                    "-c",
                    py,
                ],
                capture_output=True,
                timeout=timeout + int(duration) + 5,
            )
            stdout = r.stdout.decode("utf-8", errors="replace")
            stderr = r.stderr.decode("utf-8", errors="replace")
            p = Probe(f"tui-snapshot{'-' + '-'.join(argv) if argv else ''}", argv, None, {}, {})
            obs.append(Observation(p, stdout, stderr, r.returncode))
        except subprocess.TimeoutExpired:
            p = Probe(f"tui-snapshot{'-' + '-'.join(argv) if argv else ''}", argv, None, {}, {})
            obs.append(Observation(p, "", "<timeout>", 124))
    return obs


# --------------------------------------------------------------------------- verify
def _start_host_server(serve: dict[str, str], directory: str):
    """Provision a loopback HTTP server on the host (mirrors the in-container one) so URL-fetch
    candidates verify against identical bytes. Returns the server (call .shutdown())."""
    import functools
    import http.server
    import socketserver
    import threading

    for fn, content in serve.items():
        (Path(directory) / fn).write_text(content, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", _SERVE_PORT), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _run_candidate_py(code: str, p: Probe, *, timeout: int = 20) -> tuple[str, str, int]:
    """Write candidate Python to a temp dir, run `python3 main.py <argv>` on the probe.
    For URL-fetch probes (p.serve) a matching loopback server is provisioned first."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "main.py").write_text(code, encoding="utf-8")
        for fn, content in p.files.items():
            (d / fn).write_text(content, encoding="utf-8")
        import base64 as _b64

        for fn, b64 in p.bin_files.items():
            (d / fn).write_bytes(_b64.b64decode(b64))
        import sys

        argv = [a.replace("{URL}", f"http://127.0.0.1:{_SERVE_PORT}") for a in p.argv]
        srv = None
        try:
            if p.serve:
                srvdir = d / "srv"
                srvdir.mkdir(exist_ok=True)
                try:
                    srv = _start_host_server(p.serve, str(srvdir))
                except OSError:
                    srv = None  # port busy -> fall through; probe will reflect that
            cmd = [sys.executable, "main.py", *argv]
            # SECURITY (wild): candidate is model-generated -> NEVER raw subprocess. Route through
            # the sanctioned intake.hardened_runner (workspace-bounded cwd, scrubbed env, Docker
            # denied). allow_network only for serve/URL probes (loopback fetch). Falls back to a
            # bounded subprocess only if the runner isn't importable (dev), never silently.
            try:
                from intake.hardened_runner import run as _hrun

                res = _hrun(
                    cmd,
                    workspace=d,
                    cwd=d,
                    timeout=timeout,
                    extra_env={"PYTHONIOENCODING": "utf-8"},
                    stdin=p.stdin,
                    output_limit=None,
                    allow_network=bool(p.serve),
                )
                if res.timed_out:
                    return "", "<timeout>", 124
                return res.stdout, res.stderr, res.exit_code
            except ImportError:
                r = subprocess.run(
                    cmd, cwd=td, input=p.stdin, capture_output=True, text=True, timeout=timeout
                )
                return r.stdout, r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            return "", "<timeout>", 124
        except Exception as e:  # candidate may be syntactically broken
            return "", f"<candidate-error: {e}>", 1
        finally:
            if srv is not None:
                srv.shutdown()
                srv.server_close()


# --------------------------------------------------------------------------- NATIVE runner
# Determinex RULE: submissions are NATIVE (rebuild the tool in ITS language), never a Python
# lookalike. This engages Determinex's actual moat -- the COMPILER ORACLE: a candidate must
# COMPILE (deterministic ground truth, zero LLM judging) before it can run, and is then run as
# a real binary against the same observe-probes. This is also the only path to the C/C++/Haskell
# bottom tier. PB itself is language-agnostic; native is OUR stricter, legitimate standard.
import os as _os  # noqa: E402
import shutil as _shutil  # noqa: E402
import sys as _sys  # noqa: E402
import uuid as _uuid  # noqa: E402


def _compile_native(lang: str, code: str, d: Path) -> tuple[Path | None, str]:
    """Compile `code` in dir `d`; return (binary_path, compile_error). binary_path None on a
    compile failure (the compiler oracle REJECTS it -- like a contract, but ground-truth)."""
    binname = "main.exe" if _os.name == "nt" else "main"
    L = lang.lower()
    try:
        _cc = "cc" if _shutil.which("cc") else ("gcc" if _shutil.which("gcc") else "clang")
        _cxx = "c++" if _shutil.which("c++") else ("g++" if _shutil.which("g++") else "clang++")
        if L in ("c",):
            (d / "main.c").write_text(code, encoding="utf-8")
            cmd = [_cc, "-O2", "-o", binname, "main.c"]
        elif L in ("cpp", "c++"):
            (d / "main.cpp").write_text(code, encoding="utf-8")
            cmd = [_cxx, "-O2", "-std=c++17", "-o", binname, "main.cpp"]
        elif L in ("rust", "rs"):
            (d / "main.rs").write_text(code, encoding="utf-8")
            cmd = ["rustc", "--edition", "2021", "-O", "-o", binname, "main.rs"]
        elif L in ("go",):
            (d / "main.go").write_text(code, encoding="utf-8")
            subprocess.run(
                ["go", "mod", "init", "m"], cwd=d, capture_output=True, text=True, timeout=60
            )
            cmd = ["go", "build", "-o", binname, "."]
        elif L in ("haskell", "hs"):
            (d / "main.hs").write_text(code, encoding="utf-8")
            cmd = ["ghc", "-O2", "-o", binname, "main.hs"]
        else:
            return None, f"unsupported native lang '{lang}'"
        cp = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=180)
        if cp.returncode != 0:
            return None, (cp.stderr or cp.stdout or "compile failed")[:1200]
        return (d / binname), ""
    except FileNotFoundError as e:
        return None, f"toolchain missing: {e}"
    except subprocess.TimeoutExpired:
        return None, "compile-timeout"
    except Exception as e:
        return None, f"compile-exception: {e}"


def _kill_proc_group(p) -> None:
    import signal as _signal

    try:
        killpg = getattr(_os, "killpg", None)
        getpgid = getattr(_os, "getpgid", None)
        if killpg and getpgid:  # POSIX: kill the whole group so grandchildren die too
            killpg(getpgid(p.pid), getattr(_signal, "SIGKILL", 9))
        else:
            p.kill()
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _run_capture_safe(cmd, *, cwd, stdin, timeout):
    """Run a child with ZERO pipe-deadlock surface (corpus: eval_orphan_pipe_hang).

    stdin/stdout/stderr are FILES, never pipes -- so a child that forks a grandchild (or whose
    parent dies) can NEVER block us on a 64KB pipe buffer (the do_select / pipe_read hang that
    froze two csview runs for 20+ min each). The child gets its own session; on timeout the whole
    process GROUP is SIGKILLed so grandchildren die too. Returns (stdout, stderr, rc); rc=124 on
    timeout."""
    fin = tempfile.TemporaryFile()
    fout = tempfile.TemporaryFile()
    ferr = tempfile.TemporaryFile()
    try:
        if stdin:
            fin.write(stdin.encode("utf-8", "replace"))
            fin.seek(0)
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=fin,
            stdout=fout,
            stderr=ferr,
            start_new_session=(_os.name != "nt"),
        )
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_proc_group(p)
            try:
                p.wait(timeout=5)
            except Exception:
                pass
            rc = 124
        fout.seek(0)
        ferr.seek(0)
        return (fout.read().decode("utf-8", "replace"), ferr.read().decode("utf-8", "replace"), rc)
    finally:
        for f in (fin, fout, ferr):
            try:
                f.close()
            except Exception:
                pass


_native_cache: dict = {}  # code-hash -> (persistent_dir, binary_path|None, compile_err)


_BUILDER_IMAGES: dict[str, str] = {
    "go": "golang:1.23-alpine",
    "rust": "rust:1.82-slim",
    "c": "gcc:13",
    "cpp": "gcc:13",
    "c++": "gcc:13",
}

# Build flags that make the artifact runnable in the TASK image, which has no toolchain.
# Static linking is what makes that legal: the binary needs nothing from the runtime image.
_STATIC_BUILD: dict[str, list[str]] = {
    "go": ["go", "build", "-o", "cand", "."],
    "rust": ["sh", "-c", "rustc --edition 2021 -O -C target-feature=+crt-static -o cand main.rs"],
    "c": ["sh", "-c", "cc -O2 -static -o cand main.c"],
    "cpp": ["sh", "-c", "c++ -O2 -std=c++17 -static -o cand main.cpp"],
}
_SRC_NAME: dict[str, str] = {"go": "main.go", "rust": "main.rs", "c": "main.c", "cpp": "main.cpp"}


def _compile_native_in_container(lang: str, code: str, d: Path) -> tuple[Path | None, str]:
    """Build the candidate inside a toolchain container, --network=none, statically linked.

    Offline by construction: a candidate that reaches for a third-party module fails to build
    rather than silently fetching it, which is the rule PB submissions are held to anyway.
    """
    L = lang.lower()
    builder = _BUILDER_IMAGES.get(L)
    cmd = _STATIC_BUILD.get(L)
    if not builder or not cmd:
        return None, f"no containerized builder configured for '{lang}'"
    (d / _SRC_NAME[L]).write_text(code, encoding="utf-8")
    base = ["docker", "run", "--rm", "--network=none", "-v", f"{d}:/w", "-w", "/w"]
    try:
        if L == "go":
            subprocess.run(
                [*base, builder, "go", "mod", "init", "m"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            base = [
                *base[:2],
                "--rm",
                "--network=none",
                "-e",
                "CGO_ENABLED=0",
                "-v",
                f"{d}:/w",
                "-w",
                "/w",
            ]
        cp = subprocess.run([*base, builder, *cmd], capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None, "compile-timeout (container)"
    except FileNotFoundError:
        return None, "docker not available for containerized build"
    if cp.returncode != 0:
        return None, (cp.stderr or cp.stdout or "compile failed")[:1200]
    b = d / "cand"
    return (b, "") if b.exists() else (None, "binary missing after container build")


def assert_same_platform_as_reference(image: str | None, *, runner_is_containerized: bool) -> None:
    """PREFLIGHT (2026-07-31): refuse to grade a candidate against ground truth captured on a
    DIFFERENT platform.

    `observe_in_image` captures the reference by running the real binary inside a Linux task
    image. `_compile_native` + `make_native_runner` build and execute the candidate on the
    HOST. On a Windows or macOS host that compares a native host binary against Linux ground
    truth, and every platform-dependent behavior -- path separators, line endings, exit codes,
    TTY/ioctl, error text -- diverges for reasons that have nothing to do with the candidate.

    MEASURED 2026-07-31, gron, a known-good 1551-line legitimate reimplementation:
        host build+run on Windows ............  0/234   (0.0%)
        build+run in the Linux task image .... 21/25    (84.0%)
    Same candidate, same probes, same oracle. The only variable was the platform. The zero
    was indistinguishable from "the model cannot do this", which is exactly the failure this
    codebase keeps having to unlearn.

    On a Linux host the two happen to line up, which is why this survived: the project's own
    runners are Linux. It is still not a guarantee (host libc/env != image libc/env), so the
    containerized runner is correct everywhere and required off-Linux.
    """
    if not image or runner_is_containerized:
        return
    if _sys.platform.startswith("linux"):
        return
    raise RuntimeError(
        f"PLATFORM MISMATCH: reference behavior was observed inside {image!r} (Linux), but the "
        f"candidate would be built and run on this host ({_sys.platform}). Grading across "
        f"platforms produces false zeros that look like model incapacity. "
        f"Use make_native_runner(lang, image=...) so the candidate is built and run on the "
        f"same platform as the reference, or run on a Linux host."
    )


_BATCH_SEP = "\x1e@@DTX_REC@@\x1e"

# One shell driver runs the WHOLE probe battery inside a single container. Written with LF
# endings by the caller -- a CRLF script is a syntax error to /bin/sh, and this file is
# authored on Windows.
_BATCH_DRIVER = """#!/bin/sh
RES=/w/results.txt
: > "$RES"
for d in /w/p_*; do
    [ -d "$d" ] || continue
    cd "$d" || continue
    if [ -f ./__stdin ]; then
        /w/cand $(cat ./__argv) < ./__stdin > ./__out 2> ./__err
    else
        /w/cand $(cat ./__argv) < /dev/null > ./__out 2> ./__err
    fi
    rc=$?
    printf '%s\\n%s\\n' "$(basename "$d")" "$rc" >> "$RES"
    printf '%s' "__SEP__" >> "$RES"
    cat ./__out >> "$RES"; printf '%s' "__SEP__" >> "$RES"
    cat ./__err >> "$RES"; printf '%s' "__SEP__" >> "$RES"
done
echo DTX_BATCH_DONE
"""


def run_probes_batched(
    lang: str, code: str, probes: list, image: str, *, timeout: int = 1800
) -> tuple[list[tuple[str, str, int]], str]:
    """Run EVERY probe in one container invocation.

    The tool under test runs in ~5 ms; per-probe `docker run`/`exec` plus a Windows->WSL2
    bind-mount crossing cost ~1.3 s, i.e. 99.6% overhead, so a 234-probe oracle spent ~5 min
    per candidate. Staging all inputs once and running a single driver removes that whole
    term. Returns ([(stdout, stderr, rc), ...] aligned to `probes`, compile_error).
    """
    build = Path(tempfile.mkdtemp(prefix="dtx_bbuild_"))
    binary, cerr = _compile_native_in_container(lang, code, build)
    if binary is None:
        return [], cerr

    root = Path(tempfile.mkdtemp(prefix="dtx_batch_"))
    (root / "cand").write_bytes(binary.read_bytes())
    _os.chmod(root / "cand", 0o755)
    with open(root / "driver.sh", "w", encoding="utf-8", newline="\n") as f:
        f.write(_BATCH_DRIVER.replace("__SEP__", _BATCH_SEP))

    for i, p in enumerate(probes):
        d = root / f"p_{i:04d}"
        d.mkdir(parents=True, exist_ok=True)
        for fn, content in (getattr(p, "files", None) or {}).items():
            (d / fn).write_text(content, encoding="utf-8")
        import base64 as _b64

        for fn, b64 in (getattr(p, "bin_files", None) or {}).items():
            (d / fn).write_bytes(_b64.b64decode(b64))
        (d / "__argv").write_text(" ".join(getattr(p, "argv", None) or []), encoding="utf-8")
        if getattr(p, "stdin", None):
            (d / "__stdin").write_text(p.stdin, encoding="utf-8")

    # NO BIND MOUNT. Measured on Docker Desktop / WSL2: with `-v host:/w` the driver took
    # 256 s for 234 probes (~1.09 s each) even though the whole battery is ONE container run
    # and the tool itself runs in ~5 ms -- the cost is every file read crossing the
    # Windows->WSL2 boundary. Streaming the tree in as a tar and the results back out keeps
    # all I/O on the container's own filesystem.
    import io
    import tarfile

    buf = io.BytesIO()

    def _exec_bits(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        # Windows has no execute bit, so a tar built here arrives mode 0644 and every probe
        # fails with "permission denied" -- which looks exactly like a candidate that produces
        # no output. Set it explicitly for the things that must run.
        base = _os.path.basename(ti.name)
        if base in ("cand", "driver.sh") or ti.isdir():
            ti.mode = 0o755
        return ti

    with tarfile.open(fileobj=buf, mode="w") as tf:
        tf.add(str(root), arcname=".", filter=_exec_bits)
    buf.seek(0)
    try:
        cid = subprocess.run(
            [
                "docker",
                "create",
                "--network=none",
                "-w",
                "/w",
                "--entrypoint",
                "sh",
                image,
                "/w/driver.sh",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        ).stdout.strip()
        if not cid:
            return [], "docker create failed"
        subprocess.run(
            ["docker", "cp", "-", f"{cid}:/w"],
            input=buf.getvalue(),
            capture_output=True,
            timeout=600,
        )
        cp = subprocess.run(
            ["docker", "start", "-a", cid], capture_output=True, text=True, timeout=timeout
        )
        got = subprocess.run(
            ["docker", "cp", f"{cid}:/w/results.txt", "-"], capture_output=True, timeout=600
        )
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return [("", "<batch-timeout>", 124)] * len(probes), ""
    if "DTX_BATCH_DONE" not in (cp.stdout or ""):
        return [], f"batch driver failed: {(cp.stderr or cp.stdout)[:600]}"

    with tarfile.open(fileobj=io.BytesIO(got.stdout), mode="r") as tf:
        m = tf.next()
        f = tf.extractfile(m) if m else None
        raw = f.read().decode("utf-8", errors="replace") if f else ""
    parts = raw.split(_BATCH_SEP)
    by_name: dict[str, tuple[str, str, int]] = {}
    i = 0
    while i + 2 < len(parts):
        lines = [x for x in parts[i].splitlines() if x.strip()]
        if len(lines) >= 2:
            try:
                by_name[lines[-2]] = (parts[i + 1], parts[i + 2], int(lines[-1]))
            except ValueError:
                pass
        i += 3
    return [by_name.get(f"p_{j:04d}", ("", "<missing>", -1)) for j in range(len(probes))], ""


_warm: dict[str, tuple[str, Path]] = {}  # code-hash -> (container id, host root mounted at /w)


def _warm_container(image: str, key: str, *, allow_network: bool = False) -> str:
    """One long-lived container per CANDIDATE, so probes cost a `docker exec` (~50 ms) instead
    of a `docker run` (~1.5 s). With a 234-probe oracle and no early exit in make_verify, the
    per-run cost was ~6 min of pure startup per candidate.

    Returns "" if Docker is unavailable, so the caller falls back to `docker run`.
    """
    hit = _warm.get(key)
    if hit:
        return hit[0]
    root = Path(tempfile.mkdtemp(prefix=f"dtx_warm_{key[:10]}_"))
    net = [] if allow_network else ["--network=none"]
    try:
        cp = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                *net,
                "-v",
                f"{root}:/w",
                "-w",
                "/w",
                "--entrypoint",
                "sh",
                image,
                "-c",
                "sleep 86400",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception:
        return ""
    cid = (cp.stdout or "").strip()
    if cp.returncode != 0 or not cid:
        return ""
    _warm[key] = (cid, root)
    import atexit

    def _cleanup(c: str = cid) -> None:
        subprocess.run(["docker", "rm", "-f", c], capture_output=True, timeout=60)

    atexit.register(_cleanup)
    return cid


def _exec_probe(
    cid: str, src_dir: Path, binname: str, argv: list[str], stdin: str | None, timeout: int
) -> tuple[str, str, int]:
    """Run one probe inside the already-warm container. Each probe gets a fresh subdirectory
    so its input files cannot leak into the next one.

    The BINARY is copied once per candidate, not per probe. Copying it every time cost ~1.2 s
    for an 8 MB static Go binary and wiped out the warm container's whole advantage: measured
    1.54 s/probe with the copy vs ~0.30 s for a bare `docker exec` on this host.
    """
    root = next((r for c, r in _warm.values() if c == cid), None)
    if root is None:
        raise RuntimeError("warm container has no mounted root")
    shared_bin = root / binname
    if not shared_bin.exists():
        _shutil.copy2(src_dir / binname, shared_bin)
        _os.chmod(shared_bin, 0o755)
    sub = root / _uuid.uuid4().hex[:12]
    sub.mkdir(parents=True, exist_ok=True)
    for f in src_dir.iterdir():  # probe inputs only -- the binary already lives at /w
        if f.name != binname and f.is_file():
            _shutil.copy2(f, sub / f.name)
    cp = subprocess.run(
        ["docker", "exec", "-i", "-w", f"/w/{sub.name}", cid, f"/w/{binname}", *argv],
        input=(stdin or ""),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        _shutil.rmtree(sub, ignore_errors=True)
    except Exception:
        pass
    return cp.stdout, cp.stderr, cp.returncode


def make_native_runner(lang: str, *, timeout: int = 30, image: str | None = None):
    """A candidate runner that COMPILES the native source once (cached per code-hash) then runs
    the real binary on each probe -- pluggable into make_verify(runner=...). Compile failure =>
    the compiler oracle rejects the candidate (returns a nonzero rc with the compiler error as
    feedback), so verified search learns to fix it, exactly like a runtime failure."""
    import hashlib

    def runner(code: str, p: Probe, *, timeout: int = timeout) -> tuple[str, str, int]:
        h = hashlib.sha256((lang + "\x00" + (image or "host") + "\x00" + code).encode()).hexdigest()
        if h not in _native_cache:
            d = Path(tempfile.mkdtemp(prefix="determinex_native_"))
            # Build where the reference was observed. See assert_same_platform_as_reference:
            # a host build graded against in-image ground truth produced 0/234 for a candidate
            # that scores 84% when built and run in the image.
            binary, cerr = (
                _compile_native_in_container(lang, code, d)
                if image
                else _compile_native(lang, code, d)
            )
            _native_cache[h] = (d, binary, cerr)
        _d, binary, cerr = _native_cache[h]
        if binary is None:
            return "", f"<compile-error: {cerr}>", 1  # compiler oracle: reject, with feedback
        with tempfile.TemporaryDirectory() as rd:
            rdp = Path(rd)
            for fn, content in p.files.items():
                (rdp / fn).write_text(content, encoding="utf-8")
            import base64 as _b64

            for fn, b64 in p.bin_files.items():
                (rdp / fn).write_bytes(_b64.b64decode(b64))
            argv = [a.replace("{URL}", f"http://127.0.0.1:{_SERVE_PORT}") for a in p.argv]
            # copy the compiled binary INTO the workspace so the sandbox (workspace-bounded) can
            # execute it -- the candidate binary is untrusted model output, run sandboxed.
            local_bin = rdp / ("cand.exe" if _os.name == "nt" else "cand")
            try:
                _shutil.copy2(str(binary), str(local_bin))
                _os.chmod(str(local_bin), 0o755)
            except Exception:
                local_bin = binary
            srv = None
            try:
                if p.serve:
                    sd = rdp / "srv"
                    sd.mkdir(exist_ok=True)
                    try:
                        srv = _start_host_server(p.serve, str(sd))
                    except OSError:
                        srv = None
                if image:
                    # Run in the SAME image the reference was observed in, so libc, locale,
                    # TTY-ness and error text match.
                    #
                    # PERF (2026-07-31): `docker run` per probe costs ~1.5 s of container
                    # startup. make_verify has no early exit, so a 234-probe oracle spends
                    # ~6 min per candidate on startup alone -- 6-8 h for a k=32 x 2-round
                    # search, which makes the correct fix unusable. Keep ONE warm container
                    # per candidate (keyed by code hash) and `docker exec` each probe (~50 ms).
                    cid = _warm_container(image, h, allow_network=bool(p.serve))
                    if cid:
                        try:
                            return _exec_probe(cid, rdp, local_bin.name, argv, p.stdin, timeout)
                        except subprocess.TimeoutExpired:
                            return "", "<timeout>", 124
                    net = [] if p.serve else ["--network=none"]
                    dcmd = [
                        "docker",
                        "run",
                        "--rm",
                        "-i",
                        *net,
                        "-v",
                        f"{rdp}:/w",
                        "-w",
                        "/w",
                        image,
                        "/w/" + local_bin.name,
                        *argv,
                    ]
                    try:
                        cp = subprocess.run(
                            dcmd,
                            input=(p.stdin or ""),
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                        )
                        return cp.stdout, cp.stderr, cp.returncode
                    except subprocess.TimeoutExpired:
                        return "", "<timeout>", 124
                cmd = [str(local_bin), *argv]
                try:
                    from intake.hardened_runner import run as _hrun

                    res = _hrun(
                        cmd,
                        workspace=rdp,
                        cwd=rdp,
                        timeout=timeout,
                        stdin=p.stdin,
                        output_limit=None,
                        allow_network=bool(p.serve),
                    )
                    if res.timed_out:
                        return "", "<timeout>", 124
                    return res.stdout, res.stderr, res.exit_code
                except ImportError:
                    # No hardened_runner on this box -> file-capture (NO pipes) so a forking
                    # candidate or dead parent can't deadlock us on pipe_read (corpus:
                    # eval_orphan_pipe_hang). Kills the whole process group on timeout.
                    return _run_capture_safe(cmd, cwd=rd, stdin=p.stdin, timeout=timeout)
            except subprocess.TimeoutExpired:
                return "", "<timeout>", 124
            except Exception as e:
                return "", f"<run-error: {e}>", 1
            finally:
                if srv is not None:
                    srv.shutdown()
                    srv.server_close()

    return runner


def make_verify(
    observations: list[Observation],
    *,
    check_stderr: bool = False,
    runner=_run_candidate_py,
    batch: tuple[str, str] | None = None,
):
    """Return verify(code)->OracleResult: candidate must reproduce stdout (and rc) on every
    probe. stderr is checked only if check_stderr (stderr is often less stable). SOUND: only
    observed probes are asserted.

    `batch=(lang, image)` runs the WHOLE battery in one container instead of invoking `runner`
    per probe. There is no early exit here, so per-probe container + bind-mount overhead
    dominated everything: measured 1310 ms/probe (5.1 min/candidate) per-probe vs 239 ms/probe
    (56 s/candidate) batched, at identical accuracy (223/234 both ways). The tool itself runs
    in ~5 ms; the rest was transport.
    """

    def verify(code: str) -> OracleResult:
        failures: list[Failure] = []
        precomputed: list[tuple[str, str, int]] | None = None
        if batch:
            _lang, _image = batch
            precomputed, _cerr = run_probes_batched(
                _lang, code, [o.probe for o in observations], _image
            )
            if _cerr:
                # Compile failure: the compiler oracle rejects the candidate, with the error as
                # feedback -- same contract as the per-probe path.
                precomputed = [("", f"<compile-error: {_cerr}>", 1)] * len(observations)
        npass = 0
        n_genuine = n_genuine_pass = 0
        tot_exp_lines = matched_lines = 0
        for _idx, o in enumerate(observations):
            so, se, rc = precomputed[_idx] if precomputed is not None else runner(code, o.probe)

            # ASSERTION-AWARE PATH (2026-07-03): honor the official test's REAL criteria
            # (CONTAINS / rc-only) instead of demanding exact reproduction of the reference
            # bytes. Sound + faithful: this checks exactly what the official eval checks,
            # so a pass here is a pass there. Only fires when the probe carries an official
            # assertion; fuzz probes (assertion=None) keep the exact-match path below.
            if o.assertion is not None:
                a = o.assertion
                exp_rc = a.get("expect_rc")
                exp_stdout = a.get("expect_stdout")
                exp_in = a.get("expect_in") or []
                checks = 0
                hits = 0
                sub_ok = True
                if exp_rc is not None:
                    checks += 1
                    if rc == exp_rc:
                        hits += 1
                    else:
                        sub_ok = False
                if exp_stdout is not None:  # test demanded exact stdout
                    checks += 1
                    if so == exp_stdout:
                        hits += 1
                    else:
                        sub_ok = False
                for sub in exp_in:  # CONTAINS: check the SAME stream the reference emitted it in
                    checks += 1
                    if sub in o.stdout:
                        cand_stream = so
                    elif sub in o.stderr:
                        cand_stream = se
                    else:  # reference itself lacks it (shouldn't happen) -> accept either
                        cand_stream = so + "\n" + se
                    if sub in cand_stream:
                        hits += 1
                    else:
                        sub_ok = False
                tot_exp_lines += max(checks, 1)
                matched_lines += hits
                if sub_ok:
                    npass += 1
                    n_genuine += 1
                    n_genuine_pass += 1
                    continue
                n_genuine += 1
                argv = " ".join(o.probe.argv) or "(no args)"
                want = []
                if exp_rc is not None:
                    want.append(f"exit code == {exp_rc}")
                if exp_stdout is not None:
                    want.append(f"stdout EXACTLY:\n{exp_stdout[:400]}")
                if exp_in:
                    want.append(
                        "output must CONTAIN each of: " + ", ".join(repr(s) for s in exp_in)
                    )
                text = (
                    f"invocation: executable {argv}\n    the official test requires:\n      "
                    + "\n      ".join(want)
                    + f"\n    YOUR CODE produced exit={rc}, stdout={so[:200]!r}, "
                    f"stderr={se[:200]!r}"
                )
                failures.append(Failure(name=o.probe.name, text=text, test_id=o.probe.name))
                continue

            genuine = len(o.stdout) > 0
            if genuine:
                n_genuine += 1
                exp_lines = o.stdout.splitlines()
                got_lines = so.splitlines()
                tot_exp_lines += len(exp_lines)
                # ORDER-INDEPENDENT content match: count expected lines that have an exact
                # partner in the candidate's output (each partner used once). A single
                # ordering slip no longer misaligns every following line and collapses the
                # gradient to ~0 -- the closeness signal now tracks real content overlap.
                from collections import Counter as _Counter

                matched_lines += sum((_Counter(exp_lines) & _Counter(got_lines)).values())
            ok = (so == o.stdout) and (rc == o.returncode)
            # FAITHFULNESS (JOINT_AUDIT c): assert stderr on ERROR cases (non-zero exit with
            # diagnostic output) -- clap usage errors, parse errors with exact messages -- so
            # error-path behavior is part of the oracle, not a silent optimism-gap. Error stderr
            # is deterministic; success-case stderr (warnings/progress/timing) is often not, so
            # only error exits constrain it (unless check_stderr forces all).
            if check_stderr or (o.returncode != 0 and (o.stderr or "").strip()):
                ok = ok and (se == o.stderr)
            if ok:
                npass += 1
                if genuine:
                    n_genuine_pass += 1
                continue
            # ACTIONABLE feedback: show the exact invocation, input, EXPECTED output, and
            # what the candidate produced -- so the feedback round can correct it. This is
            # legitimate (observed reference behavior, not source).
            argv = " ".join(o.probe.argv) or "(no args)"
            inp = ""
            for fn, content in o.probe.files.items():
                inp += f"\n    file {fn}: {content[:200]}"
            if o.probe.stdin:
                inp += f"\n    stdin: {o.probe.stdin[:200]}"
            if genuine and so:
                # both produced output -> show the line-aligned transformation (make them talk)
                diff = aligned_diff(o.stdout, so)
                text = (
                    f"invocation: executable {argv}{inp}\n"
                    f"    exit: want {o.returncode}, got {rc}. Fix your output line-by-line "
                    f"(learn the transform YOU->EXPECT and apply it to every line):\n{diff}"
                )
            else:
                exp_out = o.stdout if len(o.stdout) <= 800 else o.stdout[:800] + "…"
                got_out = so if len(so) <= 300 else so[:300] + "…"
                text = (
                    f"invocation: executable {argv}{inp}\n"
                    f"    EXPECTED exit={o.returncode}, stdout:\n{exp_out}\n"
                    f"    YOUR CODE produced exit={rc}, stdout:\n{got_out}"
                )
            # STDERR (2026-07-02, found via cmatrix scoring 0.00 on 48/48 samples): `ok`
            # above already requires an EXACT stderr match whenever the exit is non-zero and
            # stderr is non-empty, but this failure text -- fed straight into the retry-round
            # feedback (VerifiedSearch._feedback_from reads Failure.text verbatim) -- never
            # said so. The model could never learn a stderr-only mismatch across rounds; it
            # was being scored against content it was never shown, in ANY round.
            if o.returncode != 0 and o.stderr.strip():
                exp_err = o.stderr if len(o.stderr) <= 500 else o.stderr[:500] + "…"
                got_err = se if len(se) <= 300 else se[:300] + "…"
                stderr_mismatch = exp_err.strip() != got_err.strip()
                text += (
                    f"\n    EXPECTED stderr (MUST MATCH EXACTLY -- part of the pass "
                    f"criteria{'  <- MISMATCH' if stderr_mismatch else ''}):\n{exp_err}\n"
                    f"    YOUR CODE's stderr:\n{got_err}"
                )
            failures.append(Failure(name=o.probe.name, text=text, test_id=o.probe.name))
        score = matched_lines / tot_exp_lines if tot_exp_lines else (1.0 if not failures else 0.0)
        return OracleResult(
            passed=not failures,
            failures=failures,
            n_total=len(observations),
            n_pass=npass,
            score=score,
            n_genuine=n_genuine,
            n_genuine_pass=n_genuine_pass,
        )

    return verify


def observations_to_examples(
    observations: list[Observation], max_n: int | None = None, max_len: int = 1200
) -> str:
    """Render observations as a prompt block the generator learns from. Shows the FULL
    input (argv + stdin + any file contents) AND the exact stdout/exit for EVERY probe by
    default (max_n=None). Showing the input contents is essential: without the file body the
    model can't map input->output and wrongly guesses stdin.

    STDERR (2026-07-02, found via 48/48-samples-score-0.00 on cmatrix): make_verify's pass
    criteria requires an EXACT stderr match whenever the exit is non-zero and stderr is
    non-empty (a very common CLI pattern -- usage/error text on failure), but this function
    never showed expected stderr at all. The model was being scored against content it could
    not see -- not a hard task, an unsolvable one as prompted. Affects every tool with a real
    stderr error path, not just ncurses tools."""
    lines = []
    for o in observations[:max_n] if max_n else observations:
        argv = " ".join(o.probe.argv) or "(no args)"
        parts = [f"$ executable {argv}"]
        for fn, content in o.probe.files.items():
            parts.append(f"  [file {fn}]:\n{content}")
        if o.probe.stdin:
            parts.append(f"  [stdin]:\n{o.probe.stdin}")
        out = o.stdout if len(o.stdout) <= max_len else o.stdout[:max_len] + "…<truncated>"
        parts.append(f"  -> exit={o.returncode}, stdout ({len(o.stdout)} bytes):\n{out}")
        if o.stderr.strip():
            err = o.stderr if len(o.stderr) <= max_len else o.stderr[:max_len] + "…<truncated>"
            note = (
                " (MUST MATCH EXACTLY -- this is part of the pass criteria)" if o.returncode else ""
            )
            parts.append(f"  -> stderr ({len(o.stderr)} bytes){note}:\n{err}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


# --------------------------------------------------------------------------- fuzz-diagnose
def _rand_json(rng, depth: int = 0) -> str:
    """A random JSON document (legitimate black-box fuzzing -- exactly how PB generates its own
    tests). Covers nesting, arrays, every scalar, unicode, special keys, edge numbers."""
    import json as _json

    scalars = [
        0,
        -0,
        1,
        -7,
        42,
        1.5,
        1.2e10,
        1e-5,
        True,
        False,
        None,
        "x",
        "a\tb",
        'q"q',
        "ünî",
        "",
        "key.dot",
        "with space",
        "true",
    ]
    if depth >= 3 or (depth > 0 and rng.random() < 0.4):
        return _json.dumps(rng.choice(scalars), ensure_ascii=False)
    if rng.random() < 0.5:  # array
        return "[" + ",".join(_rand_json(rng, depth + 1) for _ in range(rng.randint(0, 4))) + "]"
    keys = ["a", "b", "z", "1", "", "true", "null", "a.b", "a b", "Ünî", "k-v"]
    n = rng.randint(0, 4)
    items = [f"{_json.dumps(rng.choice(keys))}:{_rand_json(rng, depth + 1)}" for _ in range(n)]
    return "{" + ",".join(items) + "}"


def fuzz_diagnose(
    image: str,
    exe: str,
    candidate_code: str,
    *,
    n: int = 40,
    seed: int = 0,
    flags: list[str] | None = None,
    timeout: int = 20,
) -> list[Probe]:
    """AUTONOMOUS oracle-gap finder (removes the human from the diagnosis loop): generate N
    random black-box inputs, run BOTH the reference and the candidate, and return a Probe for
    every input where they DIVERGE. Those divergences are exactly the oracle's blind spots --
    adding them as probes makes the next verified-search FIX them. Legitimate: pure black-box
    fuzzing of the reference (no held-out-test access), the same method PB itself uses to make
    tests. Deterministic via seed so the corpus can persist + replay the battery."""
    import random

    rng = random.Random(seed)
    flag_opts = [[]] + [[f] for f in (flags or [])]
    cand_probes: list[Probe] = []
    for i in range(n):
        body = _rand_json(rng)
        fl = rng.choice(flag_opts) if flag_opts else []
        # alternate stdin vs file-arg so both channels get fuzzed
        if i % 2 == 0:
            cand_probes.append(Probe(f"fuzz{i}", list(fl), stdin=body))
        else:
            cand_probes.append(Probe(f"fuzz{i}", [*fl, f"f{i}.json"], files={f"f{i}.json": body}))
    ref = observe_in_image(image, exe, cand_probes, timeout=timeout)
    # second reference run -> drop nondeterministic inputs (don't bake a volatile divergence)
    ref2 = {o.probe.name: o for o in observe_in_image(image, exe, cand_probes, timeout=timeout)}
    diverged: list[Probe] = []
    seen_sig: set = set()
    for o in ref:
        o2 = ref2.get(o.probe.name)
        if o2 is None or o2.stdout != o.stdout or o2.returncode != o.returncode:
            continue  # nondeterministic reference -> not a sound probe
        so, _se, rc = _run_candidate_py(candidate_code, o.probe, timeout=timeout)
        if so == o.stdout and rc == o.returncode:
            continue  # candidate already matches -> oracle not blind here
        sig = (o.stdout, o.returncode)
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        diverged.append(o.probe)  # a real, deterministic oracle blind spot the candidate fails
    return diverged


if __name__ == "__main__":
    print(
        "determinex_observe: module ok; import observe_in_image/build_probes/make_verify/fuzz_diagnose"
    )
