#!/usr/bin/env python3
"""Generate a worker-facing PACKET.md for a ProgramBench tool.

Reads:
- `logs/programbench_lock_board.json` (canonical state per tool)
- the override directory `corpus/programbench/per_tool_overrides/<slug>/` (if present)
- the cluster report `logs/programbench_failure_inventory/<slug>.official_cluster_report.json` (if present)

Writes:
- `logs/programbench_factory/<slug>/PACKET.md`

The packet is self-contained: a worker LLM (or human) reading PACKET.md should
have every path and every command it needs to do exactly one cluster of work,
gate it, and produce a report. PACKET.md never tells the worker which model to
use, what prompt to follow, or how to reason - it specifies inputs, outputs,
allowed scope, forbidden actions, and the exact pack/eval/gate commands.

Usage:
    python scripts/pb_make_packet.py <slug>
    python scripts/pb_make_packet.py konradsz__igrep.aa75630
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"
INVENTORY_DIR = ROOT / "logs" / "programbench_failure_inventory"
FACTORY_DIR = ROOT / "logs" / "programbench_factory"
LOCKED_DIR = ROOT / "corpus" / "programbench" / "locked"

# The interpreter running this script, not one machine's pythoncore install.
PY311_DEFAULT = sys.executable


def _load_board(board_path: Path) -> list[dict[str, Any]]:
    if not board_path.is_file():
        return []
    try:
        return json.loads(board_path.read_text(encoding="utf-8"))
    except Exception as e:
        sys.stderr.write(f"could not parse {board_path}: {e}\n")
        return []


def _find_row(board: list[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    """Match by full slug (with hash) or by base_slug if uniquely identified."""
    # Exact slug match first
    for row in board:
        if row.get("slug") == slug:
            return row
    # base_slug match (owner__repo, no hash)
    base = slug.split(".", 1)[0]
    matches = [r for r in board if r.get("base_slug") == base]
    if len(matches) == 1:
        return matches[0]
    return None


def _short_name(slug: str) -> str:
    """e.g. konradsz__igrep.aa75630 -> igrep"""
    if "__" in slug:
        right = slug.split("__", 1)[1]
        if "." in right:
            return right.split(".", 1)[0]
        return right
    return slug


def _override_info(slug: str) -> dict[str, Any]:
    """Inspect override directory and report its contents."""
    p = OVERRIDES_DIR / slug
    info: dict[str, Any] = {"path": str(p), "exists": p.is_dir(), "files": []}
    if not p.is_dir():
        return info
    for child in sorted(p.iterdir()):
        if child.is_file() and not child.name.startswith("."):
            if child.name.endswith((".bak", ".backup", ".regressed_pre_recovery")):
                continue
            info["files"].append({"name": child.name, "size": child.stat().st_size})
    info["has_compile_sh"] = (p / "compile.sh").is_file()
    return info


def _cluster_info(slug: str) -> dict[str, Any]:
    """Load the latest cluster report for this slug, if present.

    Tolerates both the new schema produced by `pb_cluster_from_eval.py`
    (list of cluster dicts) and the legacy session-specific schema where
    `clusters` was a dict keyed by hand-named cluster code.
    """
    md = INVENTORY_DIR / f"{slug}.official_cluster_report.md"
    js = INVENTORY_DIR / f"{slug}.official_cluster_report.json"
    info: dict[str, Any] = {"md": str(md), "json": str(js), "exists": js.is_file()}
    if not js.is_file():
        return info
    try:
        data = json.loads(js.read_text(encoding="utf-8"))
    except Exception:
        return info

    info["counts"] = data.get("counts")
    info["eval_json"] = data.get("eval_json") or data.get("source_eval")
    info["by_category"] = data.get("by_category", [])
    info["executable_hash"] = data.get("executable_hash")

    raw_clusters = data.get("clusters", [])
    top: list[dict[str, Any]] = []
    if isinstance(raw_clusters, list):
        # New schema
        for c in raw_clusters[:8]:
            if not isinstance(c, dict):
                continue
            top.append(
                {
                    "category": c.get("category", "unknown"),
                    "count": int(c.get("count", 0) or 0),
                    "signature": str(c.get("signature", ""))[:160],
                }
            )
    elif isinstance(raw_clusters, dict):
        # Legacy schema - keys are cluster codes like "C4_help_argparse_exactness"
        items: list[tuple[str, dict[str, Any]]] = []
        for k, v in raw_clusters.items():
            if isinstance(v, dict):
                items.append((str(k), v))
        items.sort(key=lambda kv: -(int(kv[1].get("count") or 0)))
        for k, v in items[:8]:
            top.append(
                {
                    "category": k,
                    "count": int(v.get("count") or 0),
                    "signature": str(v.get("label") or v.get("expected_shape") or "")[:160],
                }
            )
    info["top_clusters"] = top
    return info


def _locked_info(slug: str) -> dict[str, Any]:
    """Detect if this tool already has a locked archive."""
    short = _short_name(slug)
    p = LOCKED_DIR / short
    return {
        "short_name": short,
        "is_locked": p.is_dir() and (p / "eval_report.json").is_file(),
        "locked_path": str(p) if p.is_dir() else None,
    }


def _format_packet(
    slug: str,
    row: dict[str, Any] | None,
    override: dict[str, Any],
    cluster: dict[str, Any],
    locked: dict[str, Any],
    py: str,
) -> str:
    short = _short_name(slug)
    staging = f".determinex_staging/pb_{short}_packet"
    lines: list[str] = []
    cluster_counts = cluster.get("counts") or {}
    cluster_passed = cluster_counts.get("passed")
    cluster_runnable = cluster_counts.get("runnable")
    cluster_eval = cluster.get("eval_json")
    board_best_passed = row.get("best_passed") if row is not None else None
    use_cluster_baseline = (
        isinstance(cluster_passed, int)
        and isinstance(board_best_passed, int)
        and cluster_passed > board_best_passed
        and bool(cluster_eval)
    )

    lines.append(f"# ProgramBench packet - `{slug}`")
    lines.append("")
    lines.append(f"Short name: `{short}`")
    lines.append("Generated by: `scripts/pb_make_packet.py`")
    lines.append("")
    if locked["is_locked"]:
        lines.append(
            f"> WARNING This tool already has a locked archive at `{locked['locked_path']}`. "
            f"Worker should not target this tool unless re-evaluating or extending the lock."
        )
        lines.append("")

    # 1) Current score
    lines.append("## 1. Current state")
    lines.append("")
    if row is None:
        lines.append(
            f"WARNING No row found in `logs/programbench_lock_board.json` for `{slug}`. "
            f"Run `scripts/pb_score_audit.py` first."
        )
    else:
        bs = row.get("best_score")
        ls = row.get("latest_score")
        bp = row.get("best_passed")
        brt = row.get("best_runnable_total") or row.get("best_total")
        lp = row.get("latest_passed")
        lrt = row.get("latest_runnable_total") or row.get("latest_total")
        lines.append(
            f"- Best official score:   `{bp}/{brt}` ({bs:.2f} display)"
            if isinstance(bs, (int, float))
            else "- Best official score:   n/a"
        )
        lines.append(
            f"- Latest official score: `{lp}/{lrt}` ({ls:.2f} display)"
            if isinstance(ls, (int, float))
            else "- Latest official score: n/a"
        )
        lines.append(f"- Latest regressed vs best: `{row.get('latest_regressed_from_best')}`")
        lines.append(f"- Next-action label (from board): `{row.get('next_action')}`")
        if use_cluster_baseline:
            lines.append(
                f"- Packet baseline override: `{cluster_passed}/{cluster_runnable}` "
                "from latest cluster/eval artifact. Use this for the gate, not stale board best."
            )
    lines.append("")

    # 2) Source paths
    lines.append("## 2. Source paths")
    lines.append("")
    lines.append("### Override (worker may edit ONLY files here)")
    lines.append("")
    lines.append(f"`{override['path']}`")
    lines.append("")
    if override["exists"]:
        if not override["files"]:
            lines.append("(directory exists but is empty)")
        else:
            lines.append("| File | Size (B) |")
            lines.append("|---|---:|")
            for f in override["files"]:
                lines.append(f"| `{f['name']}` | {f['size']} |")
        lines.append("")
        lines.append(f"compile.sh present: `{override['has_compile_sh']}`")
    else:
        lines.append("(directory does not exist - RECOVERY required before patching)")
    lines.append("")

    # 3) Eval paths
    lines.append("## 3. Eval paths")
    lines.append("")
    if row is not None:
        baseline_for_gate = cluster_eval if use_cluster_baseline else row.get("best_eval_path")
        lines.append(f"- Baseline eval JSON for gate: `{baseline_for_gate or '(n/a)'}`")
        if use_cluster_baseline:
            lines.append(f"- Board best eval JSON:        `{row.get('best_eval_path') or '(n/a)'}`")
        lines.append(f"- Latest eval JSON:          `{row.get('latest_eval_path') or '(n/a)'}`")
        if locked["is_locked"]:
            lines.append(
                f"- Locked archive eval:       `{(LOCKED_DIR / short / 'eval_report.json')}`"
            )
    else:
        lines.append("- (no eval JSON on record - run baseline eval first)")
    lines.append("")

    # 4) Top failure clusters
    lines.append("## 4. Top failure clusters")
    lines.append("")
    if cluster["exists"]:
        c = cluster.get("counts") or {}
        lines.append(f"Cluster report: `{cluster['md']}`")
        lines.append(
            f"Counts (at time of cluster generation): "
            f"passed={c.get('passed')} failed={c.get('failed')} "
            f"skipped={c.get('skipped')} runnable={c.get('runnable')} total={c.get('total')}"
        )
        lines.append("")
        if cluster.get("by_category"):
            lines.append("By category:")
            lines.append("")
            lines.append("| Category | Count |")
            lines.append("|---|---:|")
            for cat in cluster["by_category"][:12]:
                lines.append(f"| `{cat['category']}` | {cat['count']} |")
            lines.append("")
        if cluster.get("top_clusters"):
            lines.append("Top signatures:")
            lines.append("")
            lines.append("| # | Count | Category | Signature |")
            lines.append("|---:|---:|---|---|")
            for i, cl in enumerate(cluster["top_clusters"], 1):
                lines.append(f"| {i} | {cl['count']} | `{cl['category']}` | `{cl['signature']}` |")
            lines.append("")
    else:
        lines.append(
            f"WARNING No cluster report found at `{cluster['json']}`. "
            f"Run `scripts/pb_cluster_from_eval.py {slug} <eval-json-path> "
            f"--out-dir logs/programbench_failure_inventory` first."
        )
        lines.append("")

    # 5) Allowed scope
    lines.append("## 5. Allowed scope")
    lines.append("")
    lines.append("- **Exactly one** tool: this slug.")
    lines.append(
        "- **Exactly one** cluster: pick the highest-ROI, lowest-risk cluster from Section 4."
    )
    lines.append(f"- **Exactly one** writable dir: `{override['path']}`.")
    lines.append("- The patch must address only the chosen cluster.")
    lines.append(
        "- The patch must be small enough to fit in your worker reasoning budget - no full-file rewrites."
    )
    lines.append("")

    # 6) Forbidden actions
    lines.append("## 6. Forbidden actions")
    lines.append("")
    lines.append(
        "- Do **not** edit any file under `T:/Dev/ProgramBench/` or any `tests/`, `eval/tests/`, or fixture file."
    )
    lines.append("- Do **not** edit `corpus/programbench/locked/*`.")
    lines.append("- Do **not** edit any `scripts/*.py` shared infrastructure.")
    lines.append("- Do **not** commit, push, or stage any change.")
    lines.append(
        "- Do **not** rewrite the override `main.py`/`main.go` in full. Surgical edits only."
    )
    lines.append("- Do **not** run `full_sweep_iterate.py`.")
    lines.append(
        "- Do **not** claim a score from any source other than the official Docker eval JSON."
    )
    lines.append("")

    # 7) Pack command
    lines.append("## 7. Pack command")
    lines.append("")
    lines.append("```powershell")
    lines.append(
        f"& '{py}' scripts\\pb_pack_candidate.py {slug} --run-root {staging.replace('/', chr(92))}"
    )
    lines.append("```")
    lines.append("")
    lines.append(f"Staging root: `{staging}`")
    lines.append("")

    # 8) Eval + gate command
    lines.append("## 8. Eval + gate command")
    lines.append("")
    lines.append(
        "Use the gate; it calls the runner internally, parses the eval JSON, "
        "and writes `gate_result.json`:"
    )
    lines.append("")
    if row is not None and row.get("best_eval_path"):
        baseline = cluster_eval if use_cluster_baseline else row["best_eval_path"]
        min_pass = cluster_passed if use_cluster_baseline else (row.get("best_passed") or 0)
    elif row is not None and row.get("latest_eval_path"):
        baseline = row["latest_eval_path"]
        min_pass = row.get("latest_passed") or 0
    else:
        baseline = "<path/to/baseline.eval.json>"
        min_pass = 0
    lines.append("```powershell")
    lines.append(
        f"& '{py}' scripts\\pb_candidate_gate.py {slug} {staging.replace('/', chr(92))} "
        f'--baseline-eval `"{baseline}`" --min-baseline-passed {min_pass}'
    )
    lines.append("```")
    lines.append("")
    lines.append(
        "Gate exit codes: 0 = accept (improved + runnable stable), "
        "1 = reject (tie/regression/runnable unstable), 2 = eval infra error."
    )
    lines.append("")
    lines.append("Monitoring:")
    lines.append("")
    lines.append(
        f"- While the gate is running, watch `{staging}/gate_status.json` and `{staging}/gate_eval.log`."
    )
    lines.append(
        "- Do **not** pipe the gate through `tail`; it hides long-running progress and can make monitors look empty."
    )
    lines.append(
        "- `gate_result.json` is final-only. If it does not exist yet, the gate is still running or has not reached a decision."
    )
    lines.append("")

    # 9) Report format
    lines.append("## 9. Report format")
    lines.append("")
    lines.append(f"Write to: `logs/programbench_factory/{slug}/REPORT.md`")
    lines.append("")
    lines.append("Report must include:")
    lines.append("")
    lines.append("- Slug + cluster targeted")
    lines.append("- Files changed (paths only - diffs are visible via `git diff`)")
    lines.append("- Baseline vs candidate counts (cite both eval JSON paths)")
    lines.append("- `decision`, `reason`, `exit_code` from `gate_result.json`")
    lines.append("- Newly passing / newly failing test names (from the diff in `gate_result.json`)")
    lines.append("- Whether the candidate is kept or reverted")
    lines.append("- Any cluster still left as next-target")
    lines.append("")

    # 10) Keep/revert rule
    lines.append("## 10. Keep/revert rule")
    lines.append("")
    lines.append(
        '- If `gate_result.json.decision == "accept"`: leave the override edited. Codex will commit.'
    )
    lines.append(
        '- If `gate_result.json.decision == "reject"`: run '
        f"`git checkout -- {override['path'].replace(chr(92), '/')}` to revert."
    )
    lines.append("- The packet ends after the gate. Do not iterate within one packet.")
    lines.append("")

    # 11) Provenance
    lines.append("## 11. Provenance")
    lines.append("")
    lines.append(f"- Board JSON read at packet generation: `{BOARD_JSON}`")
    lines.append(f"- This packet path: `logs/programbench_factory/{slug}/PACKET.md`")
    if cluster["exists"]:
        lines.append(f"- Cluster report cited: `{cluster['md']}`")
    lines.append("")
    lines.append("(End of packet)")

    return "\n".join(lines)


def _run_preflight(slug: str, py: str) -> tuple[dict | None, str | None]:
    """Invoke `pb_packet_preflight.py` and return (parsed_json, classification).
    Returns (None, None) if the preflight tool is missing or fails to parse."""
    preflight = ROOT / "scripts" / "pb_packet_preflight.py"
    if not preflight.is_file():
        return None, None
    try:
        out = subprocess.run(
            [py, str(preflight), slug, "--json-only"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"slug": slug, "classification": "BLOCKED", "error": str(e)}, "BLOCKED"
    try:
        data = json.loads(out.stdout)
    except (json.JSONDecodeError, ValueError):
        return None, None
    return data, data.get("classification")


def _render_preflight_section(pre: dict | None) -> str:
    if pre is None:
        return (
            "## 0. Preflight\n\n"
            "Preflight tool `scripts/pb_packet_preflight.py` was not available "
            "when this packet was generated. Run it manually before editing:\n\n"
            "```\npython scripts/pb_packet_preflight.py <slug>\n```\n"
        )
    cls = pre.get("classification", "UNKNOWN")
    lines = [
        "## 0. Preflight (mandatory classification)",
        "",
        f"**Classification: `{cls}`**",
        "",
    ]
    reasons = pre.get("reasons") or []
    for r in reasons:
        lines.append(f"- reason: {r}")
    if reasons:
        lines.append("")
    h = pre.get("hashes") or {}
    paths = pre.get("paths") or {}
    lines.append("| field | value |")
    lines.append("|---|---|")
    lines.append(f"| active_override_main | `{paths.get('active_override_main')}` |")
    lines.append(f"| active_override_main sha[:16] | `{h.get('active_override_main_sha256_16')}` |")
    lines.append(
        f"| active_override_main @ HEAD sha[:16] | `{h.get('active_override_main_head_sha256_16')}` |"
    )
    lines.append(f"| best_source_main | `{paths.get('best_source_main')}` |")
    lines.append(f"| best_source_main sha[:16] | `{h.get('best_source_main_sha256_16')}` |")
    lines.append(f"| best_eval_json | `{paths.get('best_eval_json')}` |")
    br = pre.get("board_row") or {}
    lines.append(f"| board best | `{br.get('best_passed')} / {br.get('best_runnable_total')}` |")
    lines.append("")
    lines.append("Rules by classification:")
    lines.append("")
    lines.append("- `PATCH`     — proceed; apply one micro-primitive and gate.")
    lines.append(
        "- `RECOVERY`  — STOP: recover source from `best_source_main` first; reproduce best score; only then patch."
    )
    lines.append("- `ARCHIVE`   — STOP: run `pb_lock_archiver.py` to create the locked entry.")
    lines.append("- `LOCKED`    — STOP: tool is already at 100/100 with a locked archive; no edit.")
    lines.append(
        "- `BLOCKED`   — STOP: missing artifact (override/best source/best eval/docker image); fix the artifact, do not edit blindly."
    )
    lines.append("")
    return "\n".join(lines)


def make_packet(slug: str, py: str = PY311_DEFAULT) -> Path:
    board = _load_board(BOARD_JSON)
    row = _find_row(board, slug)
    override = _override_info(slug)
    cluster = _cluster_info(slug)
    locked = _locked_info(slug)
    preflight_data, _ = _run_preflight(slug, py)

    out_dir = FACTORY_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "PACKET.md"

    body = _format_packet(slug, row, override, cluster, locked, py)
    preamble = _render_preflight_section(preflight_data)
    out_path.write_text(preamble + "\n" + body, encoding="utf-8")
    # Also dump the raw preflight JSON sidecar for tooling.
    if preflight_data is not None:
        (out_dir / "preflight.json").write_text(
            json.dumps(preflight_data, indent=2), encoding="utf-8"
        )
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument(
        "--python",
        default=PY311_DEFAULT,
        help="Python interpreter the worker should use (default: pinned 3.11)",
    )
    args = ap.parse_args()

    out_path = make_packet(args.slug, py=args.python)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
