#!/usr/bin/env python3
"""pb_enrich_spec.py -- enrich a tool's harvested spec with the EXACT reference output.

WHY (operator, 2026-06-27): the corpus must hold "the same things as upstream" so it can
hand the LLM "the exact real thing" and the reimpl recreates byte-for-byte what the tests
expect. The bulk-harvested spec (pb_bulk_spec, via io_extractor) only captured the literal
assertions the AST could read -- thin (handlr 6/165 exact, figlet 16/386). Every test that
compares to a golden or to the reference left expect_stdout EMPTY, so the corpus did NOT
have the real expected behavior and an LLM could not recreate it exactly.

This runs the REFERENCE binary (execute-only -- PB-legal: run, never read) inside the tool's
`:task` image on every distinct test invocation (argv + stdin) via the existing
determinex_observe.observe_in_image, and writes the EXACT observed (stdout, stderr, rc) back
into corpus/programbench/specs/<slug>.json as ref_stdout/ref_stderr/ref_rc.

AUDIT-BEFORE-BUILD: composes determinex_observe (reference runner) + the already-harvested
spec. No new observation logic. Stateful/fixture-file tests (argv references a file the
probe doesn't stage) are marked ref_unobserved -- the enricher never guesses, only records
what the reference actually produced (sound: no slop).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import determinex_observe as OBS  # noqa: E402

SPECS = ROOT / "corpus" / "programbench" / "specs"


def resolve_image(slug: str, pull: bool = True) -> str | None:
    """The tool's :task reference image. Canonical name (PB convention:
    programbench/<owner>_1776_<repo>.<hash>:task). Pull on demand if not local."""
    img = f"programbench/{slug.replace('__', '_1776_')}:task"
    if subprocess.run(
        ["docker", "images", "-q", img], capture_output=True, text=True
    ).stdout.strip():
        return img
    if pull:
        print(f"[enrich] pulling reference image {img} ...")
        r = subprocess.run(["docker", "pull", img], capture_output=True, text=True)
        if r.returncode == 0:
            return img
        print(f"[enrich] pull failed: {(r.stderr or '').strip().splitlines()[-1:]}")
    return None


def _clean_argv(argv: list) -> list:
    argv = list(argv or [])
    if argv and (
        argv[0].endswith("executable")
        or argv[0].endswith(".py")
        or "/" in argv[0]
        or argv[0] in ("executable", "./executable")
    ):
        return argv[1:]
    return argv


def enrich(slug: str, timeout: int = 20) -> dict:
    specp = SPECS / f"{slug}.json"
    if not specp.exists():
        sys.exit(f"no harvested spec at {specp} (run pb_bulk_spec first)")
    spec = json.loads(specp.read_text(encoding="utf-8"))
    img = resolve_image(slug)
    if not img:
        sys.exit(f"no :task image found for {slug} (docker images | grep {slug.split('__')[-1]})")
    print(f"[enrich] {slug}  image={img}  examples={len(spec['examples'])}")

    # Build distinct probes from the test invocations (argv + stdin). Dedup so we run the
    # reference once per unique (argv, stdin).
    seen: dict[tuple, str] = {}
    probes: list = []
    for i, ex in enumerate(spec["examples"]):
        argv = _clean_argv(ex.get("argv"))
        key = (
            tuple(argv),
            ex.get("stdin"),
            tuple(sorted((ex.get("env") or {}).items())),
            tuple(sorted((ex.get("files") or {}).items())),
        )
        if key in seen:
            ex["_probe"] = seen[key]
            continue
        name = f"ex{i}"
        seen[key] = name
        ex["_probe"] = name
        probes.append(
            OBS.Probe(
                name=name,
                argv=list(argv),
                stdin=ex.get("stdin"),
                env=ex.get("env") or {},
                files=ex.get("files") or {},
            )
        )

    print(f"[enrich] {len(probes)} distinct invocations -> running reference in image...")
    obs = OBS.observe_in_image(img, "/workspace/executable", probes, timeout=timeout)
    by = {o.probe.name: o for o in obs}

    n_ref = 0
    n_match = 0  # reference agrees with io_extractor's literal (sanity)
    n_filled = 0  # io_extractor had no expected; reference filled it
    for ex in spec["examples"]:
        o = by.get(ex.pop("_probe", None))
        if not o:
            ex["ref_unobserved"] = True
            continue
        ex["ref_stdout"] = o.stdout
        ex["ref_stderr"] = o.stderr
        ex["ref_rc"] = o.returncode
        n_ref += 1
        lit = ex.get("expect_stdout")
        if lit is not None:
            if lit == o.stdout:
                n_match += 1
        else:
            n_filled += 1
    spec["n_reference_enriched"] = n_ref
    spec["reference_image"] = img
    specp.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(
        f"[enrich] DONE  {n_ref}/{len(spec['examples'])} examples now carry EXACT reference I/O "
        f"(filled {n_filled} previously-empty; {n_match} literal-asserts confirmed) -> {specp}"
    )
    return {"slug": slug, "enriched": n_ref, "filled": n_filled, "confirmed": n_match}


def main():
    ap = argparse.ArgumentParser(description="Enrich a PB spec with exact reference output")
    ap.add_argument("slug")
    ap.add_argument("--timeout", type=int, default=20)
    a = ap.parse_args()
    enrich(a.slug, a.timeout)


if __name__ == "__main__":
    main()
