#!/usr/bin/env python3
"""
determinex_pb_overnight.py -- unattended native-reimpl campaign (resumable, self-provisioning)
==========================================================================================
Marches the Native Reimplementation Workshop across present PB :task images, one tool at a
time, deep-feeding the corpus (fuzz_diagnose grows the corpus-owned oracle each run). Writes a
glanceable status file after EVERY tool so progress is visible with no prompting.

NO FALSE SURRENDER (operator law): a tool is NEVER marked a "ceiling" for a fixable cause. On
failure the campaign CLASSIFIES the need, tries to PROVISION it (pull image, use a toolchain),
and if it cannot self-fix it RECORDS the need in OVERNIGHT_NEEDS.md (the corpus's alert channel)
and labels the tool NEEDS:<x> so it is retried after provisioning -- never given up as a ceiling.

Resumable: persists OVERNIGHT_RESULTS.json; `--limit N` processes the next N undone tools, so it
runs in waves (each wave's completion is a chance to act on NEEDS, then relaunch).

  python scripts/determinex_pb_overnight.py [--limit 8] [--retry-needs]

Language auto-detected from the binary's metadata (legitimate, not decompilation).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
DRIVE = str(Path(__file__).resolve().parent / "determinex_reimpl_drive.py")
PBDIR = ROOT / "corpus" / "programbench"
STATUS = PBDIR / "OVERNIGHT_STATUS.md"
NEEDS = PBDIR / "OVERNIGHT_NEEDS.md"
RESULTS = PBDIR / "OVERNIGHT_RESULTS.json"
# PUSH-NUMBERS pass (3 levers): (1) richer oracle = fuzz_n up (in run_tool) + the -i stdin fix
# (faithful stdin probes) + harvest; (2) more budget = k=6 rounds=2; (3) escalation tier =
# deepseek-chat -> deepseek-reasoner on a verified miss (router only escalates the hard tail,
# and with faithful oracles chat clears more locally so escalation fires less).
MODELS = "deepseek-chat:1:1,deepseek-reasoner:3:3"
PER_TOOL_TIMEOUT = 2700

SKIP = {
    "sqlite",
    "lua",
    "luajit",
    "tinycc",
    "cppcheck",
    "ctags",
    "masscan",
    "fasttext",
    "csview",  # csview already locked 100% — don't waste budget re-driving it
    # heavy whales (huge codebases; poor ROI for the deepseek+Claude tag-team)
    "pandoc",
    "samtools",
    "sox",
    "bedtools2",
    "quinn",
    "halite",
    # pure-TUI (need pty + screen-exact; not byte-exact-CLI tractable here)
    "walk",
    "hwatch",
    "pueue",
    "kiro-editor",
    "gdu",
    "felix",
    "dstask",
    "pipr",
    # proven impossible-ceilings (don't burn budget)
    "hexyl",
    "doxygen",
    "chafa",
}
# Tag-team priority: unlocked tools with present images that are deterministic CLI (byte-exact-
# able tail). deepseek drives a few rounds; Claude inserts on plateau. Whales/TUI/ceilings are in
# SKIP. (Most of the old WAVE1 list is already LOCKED -> dropped.)
WAVE1 = ["jsonschema", "miller", "ast-grep", "mdbook", "oha", "hush", "lz4", "elfcat"]


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:
        return default


def _images() -> dict[str, dict]:
    out = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True
    ).stdout
    tools: dict[str, dict] = {}
    for line in out.splitlines():
        m = re.match(r"programbench/(.+?)_1776_(.+?)\.([0-9a-f]+):(task|task_cleanroom_v6)$", line)
        if not m:
            continue
        author, short, h, tag = m.groups()
        t = tools.setdefault(short, {"slug": f"{author}__{short}.{h}", "author": author, "hash": h})
        t["task" if tag == "task" else "cleanroom"] = line
    return tools


def detect_lang(image: str) -> str:
    # NOTE: `go version <file>` EXITS 0 even on non-Go binaries (prints "not a Go executable"
    # as a note) -- so we must grep its OUTPUT for a real go1.x version, not trust the exit code.
    script = (
        "B=/workspace/executable; "
        "if go version $B 2>/dev/null | grep -q 'go1\\.'; then echo go; "
        "elif strings $B 2>/dev/null | grep -qi 'rustc\\|cargo registry\\|/rust/'; then echo rust; "
        "elif strings $B 2>/dev/null | grep -q '_ZNSt\\|_ZN9\\|libstdc++\\|GLIBCXX'; then echo cpp; "
        "else echo c; fi"
    )
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "sh", image, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        lang = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else "c"
        return lang if lang in ("go", "rust", "cpp", "c") else "c"
    except Exception:
        return "c"


def classify_need(out: str, status: str, lang: str) -> tuple[str, str]:
    """Return (need_type, detail) -- NEVER a ceiling for a fixable cause."""
    low = out.lower()
    if "toolchain missing" in low or ("compile-error" in low and "not found" in low):
        return ("toolchain", f"{lang} compiler not found in PATH")
    if status == "TIMEOUT":
        if "[observe]" in out and "captured" not in out:
            return (
                "observe-hang",
                "reference binary hangs on probes (likely TUI -> needs PTY provisioning)",
            )
        return ("budget", "exceeded per-tool time budget (raise budget / split decompose)")
    if "no :task image" in low:
        return ("image", "task image missing")
    if "compile-error" in low:
        return (
            "compile",
            f"{lang} candidate did not compile (search needs more budget/escalation)",
        )
    return (
        "more-chew",
        "low local score -> needs more corpus chew / oracle growth (NOT a ceiling)",
    )


def auto_provision(need_type: str, info: dict) -> bool:
    """Give the campaign power to GET what it needs. Returns True if it self-fixed."""
    if need_type == "image" and "cleanroom" not in info:
        cr = f"programbench/{info['author']}_1776_{info['slug'].split('__')[1]}:task_cleanroom_v6"
        try:
            r = subprocess.run(["docker", "pull", cr], capture_output=True, text=True, timeout=1800)
            return r.returncode == 0
        except Exception:
            return False
    # toolchains (go/rust/gcc/ghc) already installed; new-lang installs are operator-gated.
    return False


def record_need(short: str, need_type: str, detail: str) -> None:
    NEEDS.parent.mkdir(parents=True, exist_ok=True)
    head = "# Corpus NEEDS — operator action queue (the corpus telling us what it's missing)\n\n"
    if not NEEDS.exists():
        NEEDS.write_text(head, encoding="utf-8")
    with NEEDS.open("a", encoding="utf-8") as f:
        f.write(
            f"- [{time.strftime('%H:%M')}] **{short}** needs `{need_type}`: {detail} "
            f"(retry after provisioning — NOT a ceiling)\n"
        )


def run_tool(short: str, info: dict) -> dict:
    image = info.get("task") or info.get("cleanroom") or ""
    if not image:
        return {
            "tool": short,
            "lang": "?",
            "cleanroom": False,
            "status": "NEEDS:image",
            "secs": 0,
            "genuine": "0/0",
            "official": "-",
            "probes": "-",
        }
    lang = detect_lang(image)
    has_cr = "cleanroom" in info
    # MONOLITHIC native (no --decompose): the 66-station decompose collapsed in verbose
    # compile-checked Go; monolithic best-of-K produces a coherent compilable program. k=4/r=2.
    cmd = [
        PY,
        DRIVE,
        info["slug"],
        "--models",
        MODELS,
        "--no-decompose",
        "--lang",
        lang,
        "--k",
        "6",
        "--rounds",
        "2",
        "--iters",
        "1",
        "--fuzz",
        "24",
    ]
    if not has_cr:
        cmd += ["--no-official"]
    t0 = time.time()
    out, status = "", "done"
    # Popen + process-TREE kill on timeout: subprocess.run(timeout) does NOT cut the run because
    # the drive's grandchild (the reimpl workshop) holds the pipe (gron ran 8386s past a 1500s cap).
    # process-group leader so we can kill the whole tree on timeout (cross-platform: Linux box
    # via killpg, Windows operator machine via taskkill /T).
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"},
        start_new_session=(os.name != "nt"),
    )
    try:
        out, _ = proc.communicate(timeout=PER_TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        status = "TIMEOUT"
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            import signal as _sig

            try:
                os.killpg(os.getpgid(proc.pid), _sig.SIGKILL)
            except Exception:
                proc.kill()
        try:
            out, _ = proc.communicate(timeout=30)
        except Exception:
            out = out or ""
    out = out or ""
    dt = int(time.time() - t0)
    genuine = re.search(r"GENUINE behavior reproduced: (\d+)/(\d+)", out)
    official = re.search(r"OFFICIAL: (\d+)/(\d+)", out)
    probes = re.search(r"captured (\d+) observations", out)
    g = genuine.group(0).split(": ")[1] if genuine else "0/0"
    res = {
        "tool": short,
        "lang": lang,
        "cleanroom": has_cr,
        "status": status,
        "secs": dt,
        "genuine": g,
        "probes": probes.group(1) if probes else "-",
        "official": official.group(0).split(": ")[1]
        if official
        else ("(local-only)" if not has_cr else "-"),
    }
    # NO FALSE SURRENDER: if it didn't fully chew, classify the need + try to self-provision
    gp = g.split("/")
    chewed = status == "done" and gp[0] == gp[1] and gp[1] != "0"
    if not chewed:
        nt, detail = classify_need(out, status, lang)
        if auto_provision(nt, info):
            res["status"] = f"provisioned:{nt}->retry"
        else:
            record_need(short, nt, detail)
            res["status"] = f"NEEDS:{nt}"
    return res


def write_status(results: list[dict], queue_left: int, current: str = "") -> None:
    done = len(results)
    needs = sum(1 for r in results if str(r["status"]).startswith("NEEDS"))
    off = [r for r in results if "/" in str(r["official"]) and "local" not in str(r["official"])]
    lines = [
        "# Overnight Native-Reimpl Campaign — live status",
        f"> Updated {time.strftime('%Y-%m-%d %H:%M:%S')} · chewed {done} · "
        f"queue left {queue_left} · open NEEDS {needs}" + (f" · NOW: {current}" if current else ""),
        "",
        f"Official-scored tools: {len(off)}  (cleanroom present). See OVERNIGHT_NEEDS.md for "
        "anything the corpus is asking for (none = nothing missing).",
        "",
        "| # | tool | lang | probes | local genuine | official | time | status |",
        "|---|------|------|--------|---------------|----------|------|--------|",
    ]
    for i, r in enumerate(results, 1):
        cr = "" if r["cleanroom"] else " (no cr)"
        lines.append(
            f"| {i} | {r['tool']} | {r['lang']} | {r['probes']} | {r['genuine']} | "
            f"{r['official']}{cr} | {r['secs']}s | {r['status']} |"
        )
    STATUS.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="process next N undone tools (0=all)")
    ap.add_argument("--retry-needs", action="store_true", help="re-run tools previously NEEDS:*")
    args = ap.parse_args()

    tools = _images()
    results = _load(RESULTS, [])
    done = {
        r["tool"]
        for r in results
        if not (args.retry_needs and str(r["status"]).startswith("NEEDS"))
    }
    if args.retry_needs:
        results = [r for r in results if not str(r["status"]).startswith("NEEDS")]

    # PRIORITIZE tools with a cleanroom image -> they get a real OFFICIAL score (the points
    # that matter). Then WAVE1, then the rest.
    cr_first = [t for t in tools if "cleanroom" in tools[t] and t not in SKIP and t not in done]
    order = cr_first + [
        t for t in WAVE1 if t in tools and t not in SKIP and t not in done and t not in cr_first
    ]
    order += sorted(t for t in tools if t not in order and t not in SKIP and t not in done)
    if args.limit:
        order = order[: args.limit]

    write_status(results, len(order), current="(starting)")
    for idx, short in enumerate(order):
        write_status(results, len(order) - idx, current=short)
        try:
            res = run_tool(short, tools[short])
        except Exception as e:
            res = {
                "tool": short,
                "lang": "?",
                "cleanroom": "cleanroom" in tools[short],
                "status": f"ERROR:{str(e)[:40]}",
                "secs": 0,
                "genuine": "0/0",
                "official": "-",
                "probes": "-",
            }
        results.append(res)
        RESULTS.write_text(json.dumps(results, indent=1), encoding="utf-8")
        write_status(results, len(order) - idx - 1)
        print(
            f"[overnight] {short}: {res['status']} genuine={res['genuine']} "
            f"official={res['official']} ({res['secs']}s)",
            flush=True,
        )
    write_status(results, 0)
    print(
        f"[overnight] wave DONE — {len(order)} tools this wave, {len(results)} total. "
        f"Status: {STATUS} · Needs: {NEEDS}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
