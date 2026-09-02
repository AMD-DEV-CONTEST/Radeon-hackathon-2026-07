#!/usr/bin/env python3
"""Differential fuzz for csview: generate varied CSV inputs x flag combos, run BOTH the
reference binary and the candidate, report DIVERGENCES (mine != reference). Those are exactly
the byte-bugs behind the official gap. Pure black-box (no held-out tests)."""

import random
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")
import determinex_observe as OBS  # noqa: E402

IMAGE = "programbench/wfxr_1776_csview.8ac4de0:task_cleanroom_v6"
EXE = "/workspace/executable"

CELLS = [
    "a",
    "bb",
    "ccc",
    "1",
    "42",
    "-7",
    "3.14",
    "long text",
    "中文",
    "中文字",
    "café",
    "ééé",
    "\U0001f600",
    "x\U0001f600y",
    "",
    " ",
    "  sp  ",
    "a,b",
    'has"quote',
    "tab\tin",
    "0",
    "100000",
    "русский",
    "한글",
    "ab中",
    "日本語テスト",
    "very long cell content here",
    "1.2e10",
    "True",
    "null",
]
STYLES = ["none", "ascii", "ascii2", "sharp", "rounded", "reinforced", "markdown", "grid"]
ALIGNS = ["left", "center", "right"]


def rand_csv(rng):
    ncols = rng.randint(1, 5)
    nrows = rng.randint(0, 5)
    out = []
    for _ in range(nrows + 1):
        row = []
        for _ in range(ncols):
            c = rng.choice(CELLS)
            if "," in c or '"' in c or "\t" in c or "\n" in c:
                c = '"' + c.replace('"', '""') + '"'
            row.append(c)
        out.append(",".join(row))
    return "\n".join(out) + ("\n" if rng.random() < 0.85 else "")


def rand_flags(rng):
    fl = []
    if rng.random() < 0.6:
        fl += ["--style", rng.choice(STYLES)]
    if rng.random() < 0.4:
        fl += ["--header-align", rng.choice(ALIGNS)]
    if rng.random() < 0.4:
        fl += ["--body-align", rng.choice(ALIGNS)]
    if rng.random() < 0.3:
        fl += ["-n"]
    if rng.random() < 0.3:
        fl += ["--no-headers"]
    if rng.random() < 0.3:
        fl += ["-p", str(rng.randint(0, 3))]
    if rng.random() < 0.3:
        fl += ["-i", str(rng.randint(0, 3))]
    return fl


def main():
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 12
    code = open(sys.argv[1], encoding="utf-8").read()
    rng = random.Random(7)

    probes = []
    for i in range(n):
        body = rand_csv(rng)
        fl = rand_flags(rng)
        if i % 2 == 0:
            probes.append(OBS.Probe(f"fz{i}", list(fl), stdin=body))
        else:
            probes.append(OBS.Probe(f"fz{i}", [*fl, "in.csv"], files={"in.csv": body}))

    print(f"[fuzz] {len(probes)} probes; capturing reference...")
    obs = OBS.observe_in_image(IMAGE, EXE, probes)
    runner = OBS.make_native_runner("rust")

    diverge = []
    for o in obs:
        so, _se, rc = runner(code, o.probe)
        if so != o.stdout or rc != o.returncode:
            diverge.append((o, so, rc))
    print(f"\n=== {len(diverge)}/{len(obs)} divergences ===\n")
    for o, so, rc in diverge[:show]:
        argv = " ".join(o.probe.argv) or "(no args)"
        inp = (
            o.probe.stdin
            if o.probe.stdin is not None
            else (list(o.probe.files.values())[0] if o.probe.files else "")
        )
        print(f"#### {o.probe.name}  argv: {argv}")
        print(f"  INPUT: {inp!r}")
        print(f"  exit ref={o.returncode} mine={rc}")
        if o.stdout != so:
            print(OBS.aligned_diff(o.stdout, so)[:900])
        print()


if __name__ == "__main__":
    main()
