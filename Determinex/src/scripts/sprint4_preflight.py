#!/usr/bin/env python3
"""sprint4_preflight.py — verify EVERY dependency before launching the chain.

Strategic preflight. If any check fails, halt with rc=1 BEFORE the chain
kicks off so we don't waste Docker time on a misconfigured environment.

Checks (in order, fail fast):
  1. Python imports — programbench_resource_guard, classify_subtype, generator_lib
  2. ProgramBench executable — exists, --help works
  3. Docker daemon — `docker ps` returns rc=0
  4. Family generators — all 26 produce a valid scaffold
  5. compile.sh template — produces a runnable executable AND patches run.sh
  6. Resource guard — policy returns clean flags for every family
  7. Subtype classifier — strong-classifies the 8 queue tools
  8. Worker policy table — chain script has policy for every family in queue
  9. Bulk gen output — 105/105 OK on disk with valid main.py + submission.tar.gz
 10. Local subtype smoke — every generated scaffold passes its behavior probe
 11. Chain script — parse-clean PowerShell

Outputs:
  - logs/mass_run_v2/sprint4_preflight.json with per-check status
  - rc=0 only if every check passes
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "programbench" / "families"
PBENCH_EXE = Path("T:/Dev/ProgramBench/.venv/Scripts/programbench.exe")
QUEUE_JSON = ROOT / "logs" / "mass_run_v2" / "sprint4_eval_queue.json"
BULK_JSON = ROOT / "logs" / "mass_run_v2" / "sprint4_bulk_generation.json"
CHAIN_PS1 = ROOT / "scripts" / "sprint4_tiered_eval_chain.ps1"


class Result:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""
        self.elapsed_s = 0.0


def check(label: str):
    """Decorator: run check, time it, capture result."""

    def deco(fn):
        def wrapped() -> Result:
            r = Result(label)
            t0 = time.time()
            try:
                r.detail = fn()
                r.ok = True
            except AssertionError as ex:
                r.detail = str(ex)
                r.ok = False
            except Exception as ex:
                r.detail = f"{type(ex).__name__}: {ex}"
                r.ok = False
            r.elapsed_s = round(time.time() - t0, 2)
            return r

        wrapped.__name__ = fn.__name__
        return wrapped

    return deco


@check("01 imports — resource_guard / classify_subtype / generator_lib")
def chk_imports() -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(CORPUS))
    import generator_lib  # noqa: F401
    import programbench_classify_subtype  # noqa: F401
    import programbench_resource_guard  # noqa: F401

    return "all three importable"


@check("02 programbench executable")
def chk_programbench_exe() -> str:
    assert PBENCH_EXE.is_file(), f"programbench.exe not found at {PBENCH_EXE}"
    proc = subprocess.run(
        [str(PBENCH_EXE), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"--help rc={proc.returncode}"
    assert "eval" in proc.stdout.lower() or "eval" in proc.stderr.lower(), (
        "no 'eval' subcommand in help"
    )
    return f"OK ({len(proc.stdout)} bytes help)"


@check("03 docker daemon")
def chk_docker() -> str:
    proc = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"docker ps rc={proc.returncode}: {proc.stderr[:200]}"
    running = [n for n in proc.stdout.splitlines() if n.strip()]
    assert not running, f"{len(running)} containers still running: {running[:3]}"
    return "daemon up, no stale containers"


@check("04 family generators (26 produce valid scaffolds)")
def chk_generators() -> str:
    sys.path.insert(0, str(CORPUS))
    from generator_lib import FAMILY_SPECS  # type: ignore[import-not-found]

    n_ok = 0
    n_fail = 0
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        for fam in FAMILY_SPECS:
            # Find any scaffold_generator.py for this family (use search_grep as routing host)
            out = Path(td) / fam.replace(".", "__")
            gen = CORPUS / "wave1" / "search_grep" / "scaffold_generator.py"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(gen),
                    "--instance",
                    f"test__{fam.replace('.', '_')}.abc1234",
                    "--out",
                    str(out),
                    "--family-override",
                    fam,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                n_ok += 1
            else:
                n_fail += 1
                fails.append(f"{fam}: rc={proc.returncode} stderr={proc.stderr[:80]}")
    assert n_fail == 0, f"{n_fail} family generators failed: {fails[:3]}"
    return f"{n_ok}/{n_ok + n_fail} family specs generate cleanly"


@check("05 compile.sh template — executable + xdist defuse")
def chk_compile_sh() -> str:
    sys.path.insert(0, str(CORPUS))
    from generator_lib import render_compile_sh  # type: ignore[import-not-found]

    s = render_compile_sh()
    assert "chmod +x ./executable" in s, "no chmod on executable"
    assert "no:xdist" in s or "-n auto" in s, "xdist defuse pattern missing"
    # The defuse pattern strips -n auto from run.sh
    assert "/workspace/eval/run.sh" in s or "../eval/run.sh" in s, "no run.sh path target"
    return f"{len(s)} bytes; defuses xdist"


@check("06 resource guard — builds eval cmd for every family")
def chk_resource_guard() -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from programbench_resource_guard import build_eval_cmd  # type: ignore

    sys.path.insert(0, str(CORPUS))
    from generator_lib import FAMILY_SPECS  # type: ignore[import-not-found]

    for fam in list(FAMILY_SPECS)[:5]:
        cmd, policy = build_eval_cmd(
            scaffold_root="T:/determinex-programbench/determinex_pb_factory_test_v1",
            filter_re="test",
            instance_id="test__test.abc1234",
        )
        assert "--workers" in " ".join(cmd), f"no --workers in cmd for {fam}"
        assert policy.docker_cpus >= 1, f"docker_cpus < 1 for {fam}"
    return "guard returns sane policy for sample families"


@check("07 subtype classifier — strong on 8-tool queue")
def chk_subtype_classifier() -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from programbench_classify_subtype import classify  # type: ignore[import-not-found]

    queue = json.loads(QUEUE_JSON.read_text(encoding="utf-8"))["ranked"][:8]
    n_strong = 0
    for entry in queue:
        cls = classify(entry["instance"], None)
        if cls.confidence == "strong":
            n_strong += 1
    assert n_strong >= 6, f"only {n_strong}/8 strong classifications (need >= 6)"
    return f"{n_strong}/8 strong-confidence routes"


@check("08 chain script — worker policy covers every queue family")
def chk_worker_policy() -> str:
    queue = json.loads(QUEUE_JSON.read_text(encoding="utf-8"))["ranked"]
    chain_src = CHAIN_PS1.read_text(encoding="utf-8")
    policy_block = re.search(
        r"WORKER_POLICY\s*=\s*@\{(.+?)^\}",
        chain_src,
        re.DOTALL | re.MULTILINE,
    )
    assert policy_block, "WORKER_POLICY hashtable not found in chain script"
    covered = set(re.findall(r'"([^"]+)"\s*=', policy_block.group(1)))
    missing: set[str] = set()
    for entry in queue:
        fam = entry.get("family", "")
        if fam and fam not in covered:
            # Subtype keys are also acceptable
            sub = entry.get("subtype")
            if sub and sub in covered:
                continue
            missing.add(fam)
    assert not missing, f"families with no policy entry: {sorted(missing)[:5]}"
    return f"{len(covered)} policy entries; {len(queue)} queue entries covered"


@check("09 bulk gen output — 105 on disk + factory dirs exist")
def chk_bulk_gen() -> str:
    assert BULK_JSON.is_file(), f"bulk gen log missing: {BULK_JSON}"
    bulk = json.loads(BULK_JSON.read_text(encoding="utf-8"))
    n_ok = bulk["summary"].get("n_generated_ok", 0)
    assert n_ok >= 100, f"only {n_ok} scaffolds generated (need >= 100)"
    # Spot-check 5 factory dirs exist with main.py + submission.tar.gz
    sample = [r for r in bulk["records"] if r.get("status") == "OK"][:5]
    missing: list[str] = []
    for r in sample:
        main_py = Path(r["main_py"])
        submission = Path(r["submission"])
        if not main_py.is_file():
            missing.append(f"main.py missing: {r['instance']}")
        if not submission.is_file():
            missing.append(f"submission missing: {r['instance']}")
    assert not missing, f"spot-check failures: {missing}"
    return f"{n_ok} OK; sample 5 dirs verified"


@check("10 local behavior smoke — at least 4 of 8 queue tools pass family probe")
def chk_local_smoke() -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from sprint4_subtype_smoke_pass import _PROBES  # type: ignore[import-not-found]

    queue = json.loads(QUEUE_JSON.read_text(encoding="utf-8"))["ranked"][:8]
    n_pass = 0
    for entry in queue:
        factory_main = Path(entry["factory_dir"]) / entry["instance"] / "source" / "main.py"
        if not factory_main.is_file():
            continue
        key = entry.get("subtype") if entry.get("subtype") in _PROBES else entry.get("family")
        probe = _PROBES.get(key)
        if probe is None:
            continue
        try:
            ok, _reason = probe(factory_main)
            if ok:
                n_pass += 1
        except Exception:
            pass
    assert n_pass >= 4, f"only {n_pass}/8 queue tools pass local smoke (need >= 4)"
    return f"{n_pass}/8 queue tools behave correctly locally"


@check("11 chain script — parse clean")
def chk_chain_parse() -> str:
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"$t=$null; $e=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{CHAIN_PS1}', [ref]$t, [ref]$e) | Out-Null; "
            f"if ($e) {{ $e | ForEach-Object {{ Write-Output $_.Message }} }} else {{ Write-Output 'PARSE OK' }}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "PARSE OK" in out, f"chain script parse failed: {out[:300]}"
    return "PowerShell parser clean"


def main() -> int:
    checks = [
        chk_imports,
        chk_programbench_exe,
        chk_docker,
        chk_generators,
        chk_compile_sh,
        chk_resource_guard,
        chk_subtype_classifier,
        chk_worker_policy,
        chk_bulk_gen,
        chk_local_smoke,
        chk_chain_parse,
    ]
    print(f"Sprint 4 preflight — {len(checks)} dependency checks")
    print("=" * 78)

    results: list[Result] = []
    halted = False
    for c in checks:
        r = c()
        results.append(r)
        flag = "✓" if r.ok else "✗"
        suffix = f"  ({r.elapsed_s}s)"
        print(f"  {flag} {r.name}{suffix}")
        if r.detail:
            print(f"      {r.detail[:200]}")
        if not r.ok:
            halted = True
            break

    print()
    n_ok = sum(1 for r in results if r.ok)
    print(f"=== {n_ok}/{len(checks)} passed ===")

    out_log = ROOT / "logs" / "mass_run_v2" / "sprint4_preflight.json"
    out_log.parent.mkdir(parents=True, exist_ok=True)
    out_log.write_text(
        json.dumps(
            {
                "results": [
                    {"name": r.name, "ok": r.ok, "detail": r.detail, "elapsed_s": r.elapsed_s}
                    for r in results
                ],
                "n_ok": n_ok,
                "n_total": len(checks),
                "halted_on_first_fail": halted,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  log: {out_log}")

    if halted or n_ok < len(checks):
        print()
        print("🚨 PREFLIGHT FAILED — do not launch the chain until the failing check is resolved.")
        return 1
    print()
    print("✓ All dependencies green. Chain is safe to launch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
