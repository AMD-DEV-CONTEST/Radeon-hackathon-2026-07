#!/usr/bin/env python3
"""Remote family repair-loop runner (runs ON the Hetzner Linux box).

For each real upstream repo: clone@commit -> install deps -> baseline test -> seed a defect ->
test (DETECT, must FAIL) -> repair (git checkout) -> test (REVERIFY, must PASS). Detect signal is the
test command's EXIT CODE (non-zero == failures) — uniform across phpunit/rspec/minitest/maven/cargo/
jest/ctest. A row only counts if baseline==pass, seeded==fail, repair==pass. No fake green.

Each row may specify an `image` (an official Docker image, e.g. ruby:3.3 / php:8.3-cli / maven:3-eclipse-
temurin-21 / node:22 / gcc:14). When set, install/test run INSIDE that image against the mounted repo —
so the toolchain is always modern + consistent, killing host-version friction. Without `image`, commands
run on the host toolchain. Clone + seed/repair happen on the host (the repo dir is bind-mounted).

Usage:  python3 hetzner_family_loop.py config.json results.json
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

WORK = Path("/root/fam_runs")


def sh(cmd: str, cwd: Path | None = None, timeout: int = 3000) -> tuple[int, str]:
    # bash -c preserves shell constructs (pipes, redirects, semicolons) without shell=True.
    # This script runs on Hetzner Linux where bash is always present.
    p = subprocess.run(
        ["bash", "-c", cmd],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        errors="replace",
    )
    return p.returncode, (p.stdout + p.stderr)


def in_image(image: str, workdir: Path, inner: str, env: dict | None = None) -> str:
    # Run a shell command inside an official image against the mounted repo. Root in container +
    # root on host (SSH as root) => no git dubious-ownership issues. --network host for dep fetches.
    # golang/rust/swift images don't include bash — use sh -c for those images.
    safe = inner.replace("'", "'\\''")
    _BASH_IMAGES = ("python:", "ruby:", "node:", "php:", "composer:", "maven:", "mcr.microsoft.com")
    shell = "bash -lc" if any(image.startswith(p) for p in _BASH_IMAGES) else "sh -c"
    env_flags = "".join(f" -e {k}={v}" for k, v in (env or {}).items())
    return (
        f"docker run --rm --network host{env_flags} -v {workdir}:/app -w /app {image} "
        f"{shell} 'git config --global --add safe.directory /app 2>/dev/null; {safe}'"
    )


_COUNT_PATS = (
    r"OK \((\d+)",
    r"Tests:\s*(\d+)",
    r"(\d+) examples",
    r"(\d+) runs",
    r"Tests run:\s*(\d+)",
    r"(\d+) passed",
    r"(\d+) passing",
    r"(\d+) tests",
    r"# tests (\d+)",
)


def count_from(text: str) -> int:
    for pat in _COUNT_PATS:
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return 0


def summary_line(text: str) -> str:
    # the verbatim test-runner summary line (real proof, not fabricated per-test rows)
    for ln in reversed(text.splitlines()):
        for pat in _COUNT_PATS:
            if re.search(pat, ln):
                return ln.strip()[:300]
    return ""


def run_repo(cfg: dict) -> dict:
    tool = cfg["tool"]
    d = WORK / tool
    image = cfg.get("image", "")
    res = {
        "tool": tool,
        "upstream": cfg.get("upstream", ""),
        "commit": cfg["commit"],
        "image": image,
        "ok": False,
        "error": None,
    }

    row_env = {k: v for k, v in cfg.items() if k.startswith("env_")} or None
    if row_env:
        row_env = {k[4:]: v for k, v in row_env.items()}  # strip "env_" prefix

    def runner(inner: str, timeout: int = 3000) -> tuple[int, str]:
        return sh(
            in_image(image, d, inner, env=row_env) if image else inner,
            cwd=None if image else d,
            timeout=timeout,
        )

    try:
        sh(f"rm -rf {d}")
        rc, out = sh(f"git clone --quiet {cfg['repo_url']} {d}", timeout=1800)
        if rc != 0:
            res["error"] = "clone_failed: " + out[-300:]
            return res
        if cfg["commit"] != "HEAD":
            rc, _ = sh(
                f"git fetch --quiet --depth 1 origin {cfg['commit']} 2>/dev/null; git checkout --quiet {cfg['commit']}",
                cwd=d,
            )
        res["resolved_sha"] = sh("git rev-parse --short HEAD", cwd=d)[1].strip()
        # Run install+test TOGETHER per phase in ONE container — gem/bundler/venv environments do
        # not carry across separate `docker run` invocations. Deps are cached in the mounted dir
        # (vendor/bundle, node_modules, .m2) so the re-install on phases 2-3 is near-instant.
        phase = lambda: runner("(%s) >/tmp/_inst.log 2>&1; %s" % (cfg["install"], cfg["test"]))
        rc_b, out_b = phase()
        res["baseline_rc"] = rc_b
        res["baseline_count"] = count_from(out_b)
        res["baseline_summary"] = summary_line(out_b)  # verbatim test-runner line (real proof)
        sf = d / cfg["seed_file"]
        t = sf.read_text(encoding="utf-8", errors="replace")
        if cfg["seed_old"] not in t:
            res["error"] = "seed_anchor_not_found"
            res["tail"] = out_b[-200:]
            return res
        sf.write_text(t.replace(cfg["seed_old"], cfg["seed_new"], 1), encoding="utf-8")
        rc_s, out_s = phase()
        res["seeded_rc"] = rc_s
        res["seeded_summary"] = summary_line(out_s)
        sh(f"git checkout -- {cfg['seed_file']}", cwd=d)
        rc_r, out_r = phase()
        res["reverify_rc"] = rc_r
        res["reverify_count"] = count_from(out_r)
        res["reverify_summary"] = summary_line(out_r)  # verbatim proof of the re-verified green
        res["ok"] = rc_b == 0 and rc_s != 0 and rc_r == 0
        if not res["ok"]:
            res["error"] = f"loop_not_clean baseline={rc_b} seeded={rc_s} reverify={rc_r}"
            res["tail"] = (out_b if rc_b != 0 else out_r)[-260:]
    except Exception as exc:  # pragma: no cover
        res["error"] = f"{type(exc).__name__}: {exc}"
    return res


def main() -> int:
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    WORK.mkdir(parents=True, exist_ok=True)
    out = {"family": cfg["family"], "rows": [run_repo(r) for r in cfg["rows"]]}
    out["all_ok"] = all(r["ok"] for r in out["rows"]) and len(out["rows"]) >= 3
    Path(sys.argv[2]).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "family": out["family"],
                "all_ok": out["all_ok"],
                "rows": [
                    {
                        "tool": r["tool"],
                        "ok": r["ok"],
                        "count": r.get("reverify_count"),
                        "err": r["error"],
                    }
                    for r in out["rows"]
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
