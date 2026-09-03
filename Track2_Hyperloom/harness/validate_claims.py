#!/usr/bin/env python3
"""
validate_claims.py — re-check every load-bearing claim in the submission.

Mechanical, so it can be re-run after any edit rather than believed once. Each
check names the claim, the file that should support it, and what was actually
found. Nothing here trusts prose: a number counts as backed only if it appears
in a file that is not itself the document making the claim.

    python3 harness/validate_claims.py [/path/to/Track2_Hyperloom]
"""
import re, subprocess, sys, urllib.request
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/pr-submit/Track2_Hyperloom")
SPEC = REPO / "PROJECT-SPECIFICATION.md"
RDME = REPO / "README.md"
OK, BAD, WARN = [], [], []

def grep(pat, *globs):
    args = ["grep", "-rnE", pat]
    args += [f"--include={g}" for g in (globs or ("*.md","*.txt","*.hip","*.py","*.sh"))]
    args.append(".")
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
    return [l for l in (r.stdout or "").strip().splitlines() if l]

def check(name, cond, detail):
    (OK if cond else BAD).append((name, detail))

def number_backed(name, pattern, exclude_docs=True):
    """A number is backed only if it appears somewhere other than the prose."""
    hits = grep(pattern)
    ev = [h for h in hits if not (exclude_docs and
          (h.startswith("./PROJECT-SPECIFICATION.md") or h.startswith("./README.md")
           or h.startswith("./submission/")))]
    check(name, bool(ev), (ev[0][:110] if ev else "NO SOURCE OUTSIDE THE PROSE"))

print(f"validating {REPO}\n" + "="*74)

# ---- 1. deliverables ---------------------------------------------------------
for label, pat in [("spec document","PROJECT-SPECIFICATION.md"), ("README","README.md"),
                   ("poster","submission/poster.pdf"), ("license","LICENSE")]:
    check(f"deliverable: {label}", (REPO/pat).exists(), pat)
vids = list(REPO.rglob("*.mp4"))
if vids:
    d = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","csv=p=0",str(vids[0])], capture_output=True, text=True)
    try: secs = float((d.stdout or "0").strip())
    except ValueError: secs = 0.0
    check("deliverable: video 3-5 min", 180 <= secs <= 300, f"{secs:.1f}s ({secs/60:.2f} min)")
else:
    check("deliverable: video", False, "no .mp4 found")

# ---- 2. numbers must exist outside the prose --------------------------------
number_backed("prefill 3.669x has a source",        r"3\.669")
number_backed("crossover 8B numbers have a source", r"1965\.02|2014\.17")
number_backed("crossover 24B numbers have a source",r"810\.31|501\.00")
number_backed("fp8 gate value has a source",        r"2\.658e-05")
number_backed("fp8 throughput has a source",        r"62[0-9] GB/s|629 GB/s")
number_backed("ISA census has a source",            r"125666|125,666")

# ---- 3. cited files exist ---------------------------------------------------
for m in set(re.findall(r"`([a-zA-Z0-9_./-]+\.(?:hip|py|sh|md|txt|cuh|cu))`", SPEC.read_text())):
    if m.startswith(("http","/")): continue
    hit = list(REPO.rglob(Path(m).name))
    if not hit: BAD.append((f"cited file exists: {m}", "NOT FOUND IN TREE"))
    else: OK.append((f"cited file exists: {m}", str(hit[0].relative_to(REPO))))

# ---- 4. no contradictions ---------------------------------------------------
spec = SPEC.read_text(); rdme = RDME.read_text()
check("prefill figure consistent (3.67/3.669 only)",
      not re.search(r"\b3\.(5\d|6[0-5])x", spec+rdme), "no stray 3.5x/3.6x prefill values")
# 90.5 may legitimately appear in prose DESCRIBING the corrected error (10e/10f).
# What must not survive is 90.5 presented as the measurement.
check("90.5 TOP/s not claimed as the measurement",
      not re.search(r"90\.5\s*(vs|versus)\s*25\.0|measured\s+90\.5", spec),
      "only referenced as a corrected error")
check("Magpie not described as a fix",
      not re.search(r"Magpie#70[^.]{0,60}with a fix", spec+rdme), "described as an issue")
check("roofline stated as overridable",
      "ROOFLINE_GBS" in (REPO/"kernels/decode/decode_fp8.hip").read_text(), "env var present")

# ---- 5. kernels build --------------------------------------------------------
import shutil
hipcc = Path.home()/".local/bin/hipcc"
if hipcc.exists():
    for k in sorted((REPO/"kernels/decode").glob("*.hip")):
        r = subprocess.run([str(hipcc),"--offload-arch=gfx1201","-O3",str(k),
                            "-o",f"/tmp/vc_{k.stem}"], capture_output=True, text=True)
        check(f"builds: {k.name}", r.returncode == 0,
              "clean" if r.returncode == 0 else (r.stderr or "")[:90])
else:
    WARN.append(("kernel builds","hipcc not found; skipped"))

# ---- 6. external links resolve ----------------------------------------------
for url in sorted(set(re.findall(r"https://github\.com/[A-Za-z0-9_.\-/]+", spec)))[:8]:
    api = url.replace("https://github.com/","https://api.github.com/repos/")
    api = re.sub(r"/tree/.*$","",api)
    try:
        with urllib.request.urlopen(api, timeout=12) as r: code = r.status
    except Exception as e:
        code = getattr(e,"code",0)
    check(f"link resolves: {url[:58]}", code == 200, f"HTTP {code}")

# ---- report ------------------------------------------------------------------
for n,d in OK:   print(f"  PASS  {n:<52} {d[:44]}")
for n,d in WARN: print(f"  WARN  {n:<52} {d[:44]}")
for n,d in BAD:  print(f"  FAIL  {n:<52} {d[:44]}")
print("="*74)
print(f"  {len(OK)} pass, {len(WARN)} warn, {len(BAD)} FAIL")
sys.exit(1 if BAD else 0)
