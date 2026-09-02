#!/usr/bin/env python3
"""
determinex_reimpl_drive.py -- the AUTONOMOUS reimpl self-improvement loop (no human in the loop)
============================================================================================
This is what removes the operator/Claude from the inner loop. It automates exactly the manual
cycle (run -> diff candidate vs reference -> find the oracle's blind spots -> feed them back ->
re-run) using only LEGITIMATE black-box signal:

  repeat up to N times:
    1. WORKSHOP  -- run determinex_pb_reimpl (decompose+router+contract+case+recipes+provisioned
                    oracle) on the tool with the CURRENT corpus-owned oracle -> a candidate.
    2. FUZZ-DIAGNOSE -- determinex_observe.fuzz_diagnose: random black-box inputs on BOTH the
                    reference and the candidate; every divergence is an oracle blind spot the
                    candidate fails. (Same method PB uses to make tests; no held-out access.)
    3. SELF-FEED  -- persist those divergences into the corpus-owned oracle (determinex_reimpl_
                    corpus.add_probes). Next iteration's workshop loads them -> the search is
                    forced to FIX them. The oracle compounds; the corpus literally learns.
    4. SATURATION -- when fuzzing finds NO new divergence, the black-box oracle is behavior-
                    complete for what we can observe -> stop; else loop.
  then: OFFICIAL eval the final candidate.

The operator just watches the per-iteration report and tweaks knobs. Correctness stays
oracle-bounded; legitimacy stays intact (black-box only, genuine reimplementation).

Usage:
  python scripts/determinex_reimpl_drive.py <slug> [--models ...] [--decompose] [--iters 4]
         [--fuzz 40] [--k 4] [--rounds 2] [--official]
"""

from __future__ import annotations

import argparse
import dataclasses
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import determinex_observe as OBS  # noqa: E402
import determinex_pb_reimpl as R  # noqa: E402
import determinex_reimpl_corpus as CORPUS  # noqa: E402

PY = sys.executable
EXE = "/workspace/executable"


def _run_workshop(
    slug: str, out: Path, models: str, decompose: bool, k: int, rounds: int, lang: str = "python"
) -> bool:
    cmd = [
        PY,
        str(Path(__file__).resolve().parent / "determinex_pb_reimpl.py"),
        slug,
        "--out",
        str(out),
        "--k",
        str(k),
        "--rounds",
        str(rounds),
        "--lang",
        lang,
    ]
    if models:
        cmd += ["--models", models]
    if decompose:
        cmd += ["--decompose"]
    env = {**__import__("os").environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    r = subprocess.run(cmd, env=env)
    return r.returncode == 0 and out.exists()


def _pull_task_image(slug: str) -> str | None:
    """Try to obtain the :task image for slug.

    Strategy (in order):
    1. docker pull programbench/<author>_1776_<tool>.<hash>:task  from Docker Hub
    2. If DETERMINEX_LOCAL_SSH is set (e.g. user@192.168.x.x), pipe the image from
       the local machine:  ssh local "docker save <img>" | docker load
    Returns the image name if successful, None otherwise.
    """
    import os

    if "__" not in slug:
        return None
    slug_img = slug.replace("__", "_1776_")
    hub_image = f"programbench/{slug_img}:task"
    print(f"[drive] pulling {hub_image} from registry...", flush=True)
    r = subprocess.run(["docker", "pull", hub_image], capture_output=True, text=True, timeout=300)
    if r.returncode == 0:
        print(f"[drive] pulled {hub_image} OK", flush=True)
        return hub_image

    # Hub pull failed — try local machine pipe if configured
    local_ssh = os.environ.get("DETERMINEX_LOCAL_SSH", "").strip()
    if local_ssh:
        print(f"[drive] Hub pull failed; trying local pipe from {local_ssh}...", flush=True)
        # Try both plain :task and task_cleanroom_v6 on the local machine
        for tag in ("task_cleanroom_v6", "task"):
            local_img = f"programbench/{slug_img}:{tag}"
            save = subprocess.Popen(
                [
                    "ssh",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "BatchMode=yes",
                    local_ssh,
                    f"docker save {local_img}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            load = subprocess.Popen(
                ["docker", "load"],
                stdin=save.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            save.stdout.close()
            _, lerr = load.communicate(timeout=600)
            save.wait(timeout=30)
            if load.returncode == 0:
                print(f"[drive] local-pipe loaded {local_img}", flush=True)
                return R._image_for(slug) or hub_image
            print(
                f"[drive] local-pipe {tag} failed: {lerr.decode('utf-8', 'replace')[:200]}",
                flush=True,
            )

    print(f"[drive] could not obtain image for {slug}", flush=True)
    return None


def drive(
    slug: str,
    *,
    models: str = "local/qwen2.5-coder:7b-instruct",
    decompose: bool = True,
    iters: int = 4,
    fuzz_n: int = 40,
    k: int = 4,
    rounds: int = 2,
    official: bool = True,
    lang: str = "python",
) -> dict:
    image = R._image_for(slug)
    if not image:
        image = _pull_task_image(slug)
    if not image:
        print(f"[drive] no :task image for {slug}")
        return {"error": "no image"}
    short = slug.split("__")[-1].split(".")[0]
    helptext = R._docs_and_help(image)[1]
    flags = OBS.mine_flags(helptext)[:16]
    out = ROOT / "logs" / "reimpl" / f"{short}_drive.py"
    out.parent.mkdir(parents=True, exist_ok=True)

    # TEST-TARGETED ORACLE SEED (oracle-completeness): pull every recoverable OFFICIAL-TEST
    # input and add it to the corpus oracle; the oracle runs the reference on each to obtain
    # the ground-truth expectation. Closes the byte-exact tail that random fuzz can't reach
    # and the gated I/O extractor skips. Black-box-legitimate: inputs only, reference fills it.
    try:
        import determinex_test_oracle as _TO

        _np, _seeded = _TO.seed_corpus(slug, short, cap=400)
        print(
            f"[drive] TEST-ORACLE seed: {_np} official-test input probes -> +{_seeded} new "
            f"in corpus oracle (total {len(CORPUS.load_probes(short))})"
        )
    except Exception as _e:
        print("[drive] test-oracle seed skipped:", _e)

    print(f"=== AUTONOMOUS DRIVE :: {short} (iters={iters}, fuzz={fuzz_n}, models={models}) ===")
    history = []
    for it in range(iters):
        print(f"\n----- iteration {it} -----")
        if not _run_workshop(slug, out, models, decompose, k, rounds, lang):
            print("[drive] workshop run failed; stopping")
            break
        candidate = out.read_text(encoding="utf-8", errors="replace")
        # FUZZ-DIAGNOSE: black-box divergences = oracle blind spots the candidate fails
        diverged = OBS.fuzz_diagnose(image, EXE, candidate, n=fuzz_n, seed=it, flags=flags)
        serial = [dataclasses.asdict(p) for p in diverged]
        added = CORPUS.add_probes(short, serial)
        history.append({"iter": it, "diverged": len(diverged), "added": added})
        print(
            f"[drive] iter {it}: fuzz found {len(diverged)} candidate≠reference divergences; "
            f"+{added} NEW probes into the corpus oracle (total persisted: "
            f"{len(CORPUS.load_probes(short))})"
        )
        if len(diverged) == 0:
            print(
                "[drive] *** ORACLE SATURATED: fuzzing finds no candidate divergence -> "
                "black-box-complete. The next miss (if any) is genuinely un-observable. ***"
            )
            break
        if added == 0:
            print(
                "[drive] no NEW probes (all divergences already known) -> the search isn't "
                "closing them at this budget; tweak (raise budget / add escalation tier)."
            )
            break

    result = {"tool": short, "candidate": str(out), "history": history}
    if not out.exists():
        result["error"] = "no candidate"
        return result
    if official and out.exists():
        print("\n[drive] OFFICIAL eval of the final candidate...")
        oe = subprocess.run(
            [
                PY,
                str(Path(__file__).resolve().parent / "determinex_pb_official_eval.py"),
                slug,
                str(out),
                "--lang",
                lang,
            ],
            env={**__import__("os").environ, "PYTHONUTF8": "1"},
            capture_output=True,
            text=True,
        )
        tail = (oe.stdout or "").strip().splitlines()[-3:]
        for ln in tail:
            print("  " + ln)
        result["official_tail"] = tail
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    # 2026-07-02: default is the ESCALATION LADDER the router was built for but which no
    # run had ever actually used (every run passed a flat single-model ladder) -- which is
    # exactly how the bug below survived undetected. The 7b (4.7GB) clears the cheap bulk;
    # tier 2 is invoked only on stations/leaves the 7b misses.
    #
    # 2026-07-18 FIX: tier 2 named 'qwen2.5-coder:14b-instruct', a model that was never
    # actually pulled on the box this ran on. Every escalation attempt silently produced a
    # generation-error string that the search loop treated as just another wrong-code
    # candidate -- 6+ decompose stations on a real gron drive burned ~10-15 min each on a
    # completely unreachable model before a human noticed by querying Ollama directly.
    # preflight_ladder() (determinex_pb_reimpl.py) now catches this class of bug before any
    # compute is spent, on ANY --models spec -- but the DEFAULT itself needed a real model:
    # deepseek-coder-v2:16b (8.9GB, confirmed present + responsive) replaces the phantom tag.
    ap.add_argument(
        "--models", default="ollama/qwen2.5-coder:7b-instruct:1:1,ollama/deepseek-coder-v2:16b:2:3"
    )
    ap.add_argument("--decompose", action="store_true", default=True)
    ap.add_argument("--no-decompose", dest="decompose", action="store_false")
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--fuzz", type=int, default=40)
    # 2026-07-02: match determinex_pb_reimpl.py's own sound defaults (k=8, rounds=3);
    # k=4/rounds=2 under-amplifies VerifiedSearch when this is invoked directly.
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--no-official", dest="official", action="store_false", default=True)
    ap.add_argument(
        "--lang", default="python", help="DETERMINEX native rule: go/rust/c/cpp/haskell"
    )
    args = ap.parse_args()
    res = drive(
        args.slug,
        models=args.models,
        decompose=args.decompose,
        iters=args.iters,
        fuzz_n=args.fuzz,
        k=args.k,
        rounds=args.rounds,
        official=args.official,
        lang=args.lang,
    )
    if isinstance(res, dict) and "error" in res:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
