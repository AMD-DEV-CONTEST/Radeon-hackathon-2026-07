"""Evidence inventory script for reconciliation audit. Read-only."""

import datetime
import hashlib
import json
import os
from typing import Any

BS = chr(92)  # backslash — avoids heredoc escaping issues


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def load_json(p: str) -> Any:
    with open(p, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def mtime_iso(p: str) -> str:
    mt = os.path.getmtime(p)
    return datetime.datetime.fromtimestamp(mt, tz=datetime.UTC).isoformat()


def resolve_path(p: str) -> str | None:
    if not p:
        return None
    p2 = p.replace(BS, "/").replace("/", "/")
    if len(p2) >= 2 and p2[1] == ":":
        p2 = p2[0].upper() + p2[1:]
    if os.path.exists(p2):
        return p2
    # DERIVED, not literal. This strips the repo root off an absolute path so the
    # remainder can be resolved relatively. It was two hardcoded spellings of one
    # machine's checkout, which meant the audit silently stopped stripping anywhere
    # else -- and a linter pass briefly replaced both with the same placeholder,
    # which would have made the loop compare a path against '<repo>/' twice.
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")).replace(BS, "/")
    for prefix in [_root + "/", _root.lower() + "/"]:
        if p2.lower().startswith(prefix.lower()):
            rel = p2[len(prefix) :]
            if os.path.exists(rel):
                return os.path.abspath(rel).replace(BS, "/")
    return None


index = load_json("corpus/programbench/eval_index.json")
locks = [x for x in index if x.get("official_full_suite_resolved")]
print(f"Strict locks in eval_index.json: {len(locks)}")

all_results: dict = {}

for lock in locks:
    slug: str = lock["slug"]
    ep_raw: str = lock.get("eval_report_path", "")
    actual_ep = resolve_path(ep_raw)
    ep_on_disk = actual_ep is not None and os.path.exists(actual_ep)

    # Fallback: look in standard locked dir
    locked_dir_ep: str | None = None
    ap: str = lock.get("archive_path", "")
    if ap:
        c = ap + "/eval_report.json"
        if os.path.exists(c):
            locked_dir_ep = c
    std = f"corpus/programbench/locked/{slug}/eval_report.json"
    if not locked_dir_ep and os.path.exists(std):
        locked_dir_ep = std

    final_ep: str | None = actual_ep if ep_on_disk else locked_dir_ep
    ep_path_source = (
        "eval_index" if ep_on_disk else ("locked_dir_fallback" if locked_dir_ep else "none")
    )

    rec: dict = {
        "slug": slug,
        "eval_index_passed": lock.get("passed"),
        "eval_index_total": lock.get("total"),
        "official_passed": lock.get("official_passed"),
        "official_total": lock.get("official_total"),
        "eval_index_not_run": lock.get("not_run", 0),
        "eval_index_skipped": lock.get("skipped", 0),
        "eval_index_failed": lock.get("failed", 0),
        "eval_index_source": lock.get("source"),
        "eval_index_last_eval_date": lock.get("last_eval_date"),
        "eval_report_path_raw": ep_raw,
        "eval_report_path_resolved": final_ep,
        "eval_report_path_source": ep_path_source,
        "eval_report_exists": final_ep is not None,
    }

    # Flags
    if ep_raw and not ep_on_disk:
        rec["eval_report_path_flag"] = "PATH_IN_INDEX_MISSING_ON_DISK"
    if not ep_raw and locked_dir_ep:
        rec["eval_report_path_flag"] = "MISSING_FROM_INDEX_FOUND_IN_DIR"
    if not ep_raw and not locked_dir_ep:
        rec["eval_report_path_flag"] = "NO_PATH_AND_NOT_FOUND"

    if final_ep is not None and os.path.exists(final_ep):
        try:
            rpt = load_json(final_ep)
            tr: list = rpt.get("test_results", [])
            rec["report_test_count"] = len(tr)
            rec["report_test_branches"] = rpt.get("test_branches", [])
            rec["report_solution_branch"] = rpt.get("solution_branch")
            rec["report_executable_hash"] = rpt.get("executable_hash")
            rec["report_has_full_test_list"] = len(tr) > 0
            rec["report_passed_count"] = sum(1 for x in tr if x.get("status") == "passed")
            rec["report_mtime_iso"] = mtime_iso(final_ep)
            rec["report_sha256"] = sha256_file(final_ep)
        except Exception as e:
            rec["report_parse_error"] = str(e)

    # Locked directory
    locked_dir: str | None = None
    if ap and os.path.isdir(ap):
        locked_dir = ap
    if not locked_dir:
        c2 = f"corpus/programbench/locked/{slug}"
        if os.path.isdir(c2):
            locked_dir = c2
    rec["locked_dir"] = locked_dir

    if locked_dir is not None:
        items = sorted(os.listdir(locked_dir))
        rec["locked_dir_contents"] = items
        found_tj: str | None = None
        for tj in [locked_dir + "/tests.json", locked_dir + "/source/tests.json"]:
            if os.path.exists(tj):
                found_tj = tj
                break
        if found_tj is not None:
            rec["vendored_tests_json_path"] = found_tj
            try:
                data = load_json(found_tj)
                rec["vendored_tests_count"] = len(data)
                rec["vendored_tests_sha256"] = sha256_file(found_tj)
            except Exception as e:
                rec["vendored_tests_parse_error"] = str(e)
        rec["submission_tar_exists"] = os.path.exists(locked_dir + "/submission.tar.gz")

    # T2 classification
    if rec.get("vendored_tests_json_path"):
        rec["t2_class"] = "PINNED"
    elif rec.get("report_has_full_test_list"):
        rec["t2_class"] = "RECONSTRUCTIBLE"
    else:
        rec["t2_class"] = "UNPINNED"

    all_results[slug] = rec

# ── Summary output ──────────────────────────────────────────────────────────
classes: dict = {"PINNED": [], "RECONSTRUCTIBLE": [], "UNPINNED": []}
for slug, r in all_results.items():
    classes[r.get("t2_class", "UNPINNED")].append(slug)

print(
    f"\nT2: PINNED={len(classes['PINNED'])}  "
    f"RECONSTRUCTIBLE={len(classes['RECONSTRUCTIBLE'])}  "
    f"UNPINNED={len(classes['UNPINNED'])}"
)

print("\nFLAGS (per tool):")
for slug, r in all_results.items():
    flags = []
    pf = r.get("eval_report_path_flag")
    if pf:
        flags.append(pf)
    op, ot = r.get("official_passed"), r.get("official_total")
    ip, it = r.get("eval_index_passed"), r.get("eval_index_total")
    if op != ip or ot != it:
        flags.append(f"BIDIR_SPLIT: official={op}/{ot} passed/total={ip}/{it}")
    rtc = r.get("report_test_count")
    rpc = r.get("report_passed_count")
    if rtc is not None and ip is not None and rtc != ip:
        flags.append(f"COUNT_MISMATCH: report_tests={rtc} report_passed={rpc} index_passed={ip}")
    if flags:
        print(f"  {slug}: {'; '.join(flags)}")

print("\nUNPINNED detail:")
for slug in classes["UNPINNED"]:
    r = all_results[slug]
    print(
        f"  {slug}: exists={r.get('eval_report_exists')} "
        f"flag={r.get('eval_report_path_flag', '—')} "
        f"locked_dir={r.get('locked_dir')}"
    )

print("\nSaving reconciliation_audit_data.json ...")
with open("reconciliation_audit_data.json", "w", encoding="utf-8") as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print("Done.")
