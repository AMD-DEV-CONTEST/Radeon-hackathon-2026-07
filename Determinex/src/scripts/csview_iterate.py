#!/usr/bin/env python3
"""Claude-tier iteration harness (ANY tool): build a tool's comprehensive oracle
(flag-combinatorial, captured byte-exact from the reference binary), compile a candidate, and
print the FAILING probes with clean expected-vs-got diffs so the (Claude) escalation tier can
patch byte-exact. Reusable tail-closer for the corpus-compounding loop.

Usage: python3 csview_iterate.py <candidate.(rs|go|c|cpp|hs)> [--slug <slug>] [--lang rust] [--show N]
If --slug omitted, defaults to csview.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")
import determinex_observe as OBS  # noqa: E402


def _resolve_image(slug: str) -> str:
    """Find the on-box reference image for a slug: prefer task_cleanroom_v6, else :task.
    slug like 'sharkdp__hexyl.2e26437' -> programbench/sharkdp_1776_hexyl.2e26437:(task_cleanroom_v6|task)."""
    out = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True
    ).stdout
    short = slug.split("__")[-1]  # hexyl.2e26437
    cands = [
        ln
        for ln in out.splitlines()
        if short in ln and "programbench/" in ln and "compiled" not in ln
    ]
    for ln in cands:
        if "cleanroom" in ln:
            return ln
    return cands[0] if cands else f"programbench/{slug.split('__')[0]}_1776_{short}:task"


SLUG = sys.argv[sys.argv.index("--slug") + 1] if "--slug" in sys.argv else "wfxr__csview.8ac4de0"
LANG = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "rust"
IMAGE = _resolve_image(SLUG)
EXE = "/workspace/executable"


def _docs_and_help():
    import subprocess

    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", "hch", IMAGE, "sleep", "60"], capture_output=True
    )
    try:
        h = subprocess.run(
            ["docker", "exec", "-w", "/workspace", "hch", "./executable", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return h.stdout + h.stderr
    finally:
        subprocess.run(["docker", "rm", "-f", "hch"], capture_output=True)


def main():
    cand_path = Path(sys.argv[1])
    show = 12
    if "--show" in sys.argv:
        show = int(sys.argv[sys.argv.index("--show") + 1])
    code = cand_path.read_text(encoding="utf-8")

    help_text = _docs_and_help()
    task_inputs = OBS.auto_inputs(IMAGE, EXE)
    probes = OBS.build_probes(help_text, task_inputs)
    print(f"[oracle] {len(probes)} probes; capturing reference behavior...")
    observations = OBS.observe_in_image(IMAGE, EXE, probes)
    print(f"[oracle] {len(observations)} observations captured")

    runner = OBS.make_native_runner(LANG)
    verify = OBS.make_verify(observations, runner=runner)
    res = verify(code)
    g = res.n_genuine or 1
    print(
        f"\n=== {cand_path.name}: {res.n_genuine_pass}/{res.n_genuine} genuine "
        f"({100 * res.n_genuine_pass / g:.1f}%)  |  all-probe pass {res.n_pass}/{res.n_total}  "
        f"|  score {res.score:.3f} ==="
    )
    fails = getattr(res, "failures", []) or []
    print(f"--- {len(fails)} failing probes (showing {min(show, len(fails))}) ---\n")
    for f in fails[:show]:
        print(f"################ {getattr(f, 'name', '?')} ################")
        print(getattr(f, "text", "")[:1400])
        print()


if __name__ == "__main__":
    main()
