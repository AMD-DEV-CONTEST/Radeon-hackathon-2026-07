"""Build final reconciliation_audit.json. Read-only data gathering."""

import datetime
import hashlib
import json
import os
import pathlib
import subprocess
from typing import Any

# Repo root, derived. These paths were literal '<repo>/...' strings,
# which made the audit runnable on exactly one machine.
_ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_json(p: str) -> Any:
    with open(p, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


BS = chr(92)

tasks_root = "T:/Dev/ProgramBench/src/programbench/data/tasks"
all_task_dirs = os.listdir(tasks_root)

index = load_json("corpus/programbench/eval_index.json")
locks = [x for x in index if x.get("official_full_suite_resolved")]

pb_head = subprocess.run(
    ["git", "-C", "T:/Dev/ProgramBench", "rev-parse", "HEAD"], capture_output=True, text=True
).stdout.strip()
print(f"PB HEAD: {pb_head}")
print(f"Locks: {len(locks)}")

# ── T3: slug -> task dir ─────────────────────────────────────────────────────
t3_records: dict = {}
for lock in locks:
    slug: str = lock["slug"]
    slug_tool = slug.split("__")[-1].split(".")[0].lower().replace("-", "").replace("_", "")
    found = []
    for td in all_task_dirs:
        if "__" in td:
            tool_part = td.split("__", 1)[1].split(".")[0].lower().replace("-", "").replace("_", "")
        else:
            tool_part = td.split(".")[0].lower().replace("-", "").replace("_", "")
        if tool_part == slug_tool:
            found.append(td)
    if len(found) == 1:
        td = found[0]
        full_tj = f"{tasks_root}/{td}/tests.json"
        upstream_commit = td.rsplit(".", 1)[-1] if "." in td else "UNKNOWN"
        sha = sha256_file(full_tj) if os.path.exists(full_tj) else None
        tj_data = load_json(full_tj) if os.path.exists(full_tj) else {}
        branches = tj_data.get("branches", []) if isinstance(tj_data, dict) else []
        t3_records[slug] = {
            "task_dir": td,
            "task_dir_full": f"{tasks_root}/{td}",
            "tests_json_path": full_tj,
            "tests_json_exists": os.path.exists(full_tj),
            "tests_json_sha256": sha,
            "upstream_commit_from_dir_name": upstream_commit,
            "task_branch_count": len(branches),
            "pb_repo_head": pb_head,
            "pb_repo_path": "T:/Dev/ProgramBench",
        }
    else:
        t3_records[slug] = {
            "task_dir": None,
            "note": "NOT FOUND" if not found else f"AMBIGUOUS: {found}",
        }

# ── Load T1/T2 base data ─────────────────────────────────────────────────────
t12_data = load_json("reconciliation_audit_data.json")

# ── Build output ─────────────────────────────────────────────────────────────
output: dict = {
    "audit_meta": {
        "generated_at": datetime.datetime.now(tz=datetime.UTC).isoformat(),
        "auditor_role": "Executor -- READ ONLY",
        "protocol_path": str(_ROOT / "PROTOCOL.md"),
        "ground_truth_path": str(_ROOT / "corpus" / "programbench" / "GROUND_TRUTH.md"),
        "eval_index_path": str(_ROOT / "corpus" / "programbench" / "eval_index.json"),
    },
    "T1_lock_enumeration": {
        "count_in_eval_index": len(locks),
        "count_in_ground_truth": 50,
        "count_matches": len(locks) == 50,
        "flags": [],
        "per_tool": {},
    },
    "T2_cert_fingerprint": {
        "counts": {"PINNED": 0, "RECONSTRUCTIBLE": 0, "UNPINNED": 0},
        "PINNED": [],
        "RECONSTRUCTIBLE": [],
        "UNPINNED": [],
    },
    "T3_local_task_definitions": {
        "pb_repo_path": "T:/Dev/ProgramBench",
        "pb_repo_git_head": pb_head,
        "pb_repo_remote": "https://github.com/facebookresearch/ProgramBench.git",
        "tasks_root": tasks_root,
        "per_tool": t3_records,
    },
    "T4_upstream_source_pinning": {
        "answer": "YES",
        "evidence_path": "T:/Dev/ProgramBench/.git",
        "pb_head_commit": pb_head,
        "pb_remote": "https://github.com/facebookresearch/ProgramBench.git",
        "git_log_head": "24facbe Update paper link",
        "note": (
            "T:/Dev/ProgramBench has .git intact with tracked HEAD "
            + pb_head
            + ". All 201 task dirs present; each dir name "
            "encodes the upstream source commit hash "
            "(e.g. jqlang__jq.b33a763 = jq repo commit b33a763). "
            "Task-level upstream commits are embedded in dir names -- "
            "SHA-256 of each tests.json recorded in T3."
        ),
    },
    "T5_isolation_evidence": {
        "findings": [
            {
                "file": "<repo>/scripts/determinex_programbench_agent.py",
                "line": 679,
                "excerpt": (
                    "R18. NEVER MAKE NETWORK CALLS AT RUNTIME (during ./executable invocation). "
                    "The grader sandbox blocks outbound HTTP. pip install during compile.sh "
                    "is fine; urlopen() while executing is not."
                ),
                "type": "system_prompt_claim",
                "note": (
                    "Text in LLM system prompt. Describes expected eval-environment behavior. "
                    "NOT an OS-level, Docker-level, or firewall configuration artifact."
                ),
            },
            {
                "file": "<repo>/scripts/determinex_programbench_agent.py",
                "line": 518,
                "excerpt": "python3 (3.10), pip (network available -- pip install works)",
                "type": "system_prompt_claim",
                "note": "Documents compile-time network as available. Grade-time blocked per line 679. Both are system-prompt claims, not enforced config.",
            },
            {
                "file": "T:/Dev/ProgramBench/src/programbench/container.py",
                "lines": "42-58",
                "excerpt": (
                    'cmd = [executable, "run", "-d", "--init", "--name", self._name, '
                    '"-w", cwd, "--cpus", str(cpus), *env_args, *run_args, image, "sleep", "2h"]'
                ),
                "type": "docker_run_command",
                "note": (
                    "No --network none, --network bridge-with-rules, or any network restriction flag "
                    "present. Default Docker bridge networking applies to eval containers. "
                    "run_args are caller-supplied; no caller in pb_hetzner_eval_shard.sh adds network flags."
                ),
            },
            {
                "file": "<repo>/scripts/install_hetzner_stack.sh",
                "line": 79,
                "excerpt": "--network host (docker run for otel/opentelemetry-collector-contrib)",
                "type": "hetzner_provisioning",
                "note": "Applies to monitoring collector container, not eval containers.",
            },
            {
                "file": "<repo>/scripts/pb_hetzner_eval_shard.sh",
                "note": (
                    'Delegates to "programbench eval" CLI. No network flags injected. '
                    "No firewall or netns configuration present in this file."
                ),
                "type": "hetzner_runner",
            },
        ],
        "conclusion": (
            "NO on-disk evidence of network isolation enforcement (firewall rules, netns, "
            "--network none, iptables/nftables) for ProgramBench eval containers. "
            "The only isolation statement is a system-prompt claim in "
            "determinex_programbench_agent.py:679. The actual Docker run command in "
            "T:/Dev/ProgramBench/src/programbench/container.py carries no network restriction flags."
        ),
    },
    "discrepancies": [
        {
            "id": "DISC-01",
            "slug": "flamelens",
            "type": "REPORT_COUNT_MISMATCH",
            "description": (
                "eval_index records passed=510/total=510, official_passed=510/official_total=510. "
                "Archived eval_report.json at the same path contains 622 test_results (all passed): "
                "311 eval.tests.* + 311 tests.* bidir pairs across 8 branches. "
                "Re-parsing per PROTOCOL.md Sec 2 step 1 yields 622/622, not 510/510. "
                "The factory_note says nofilter_discriminating_run: 510/510 -- "
                "the archived report appears to be from a different (later) eval run "
                "than the one that produced the indexed score."
            ),
            "eval_index_passed": 510,
            "eval_index_total": 510,
            "report_test_count_on_disk": 622,
            "report_passed_count_on_disk": 622,
            "report_path": "<repo>/corpus/programbench/locked/flamelens/eval_report.json",
            "eval_index_entry": "<repo>/corpus/programbench/eval_index.json slug=flamelens",
            "ground_truth_impact": "GROUND_TRUTH.md shows 510/510 (derived from eval_index). On-disk report gives 622/622.",
        },
        {
            "id": "DISC-02",
            "slug": "thokr",
            "type": "BIDIR_FIELD_SPLIT",
            "description": (
                "official_passed=507/official_total=507 vs passed=1014/total=1014. "
                "GROUND_TRUTH.md records 1014/1014 (from passed/total fields). "
                "official_* fields reflect raw PB CLI output (507 unique test cases); "
                "passed/total fields reflect bidir-doubled count (507*2=1014). "
                "Archived eval_report.json has 1014 test_results matching passed/total. "
                "This is a documentation inconsistency between two field sets in eval_index, "
                "not an evidence/score mismatch."
            ),
            "official_passed": 507,
            "official_total": 507,
            "passed": 1014,
            "total": 1014,
            "ground_truth_records": 1014,
            "report_test_count_on_disk": 1014,
        },
        {
            "id": "DISC-03",
            "slug": "rust-embedded__svd2rust.1760b5e",
            "type": "MISSING_EVAL_REPORT_PATH_IN_INDEX",
            "description": (
                "eval_index.json has no eval_report_path for this lock (field absent/empty). "
                "File located via locked-dir fallback at "
                "<repo>/corpus/programbench/locked/rust-embedded__svd2rust.1760b5e/eval_report.json"
            ),
            "eval_report_path_in_index": "",
            "file_found_at": "<repo>/corpus/programbench/locked/rust-embedded__svd2rust.1760b5e/eval_report.json",
        },
        {
            "id": "DISC-04",
            "slug": "trasta298__keifu.3331426",
            "type": "MISSING_EVAL_REPORT_PATH_IN_INDEX",
            "description": (
                "eval_index.json has no eval_report_path for this lock (field absent/empty). "
                "File located via locked-dir fallback at "
                "<repo>/corpus/programbench/locked/trasta298__keifu.3331426/eval_report.json"
            ),
            "eval_report_path_in_index": "",
            "file_found_at": "<repo>/corpus/programbench/locked/trasta298__keifu.3331426/eval_report.json",
        },
    ],
    "unknowns": [],
}

# ── Per-tool T1/T2 records ───────────────────────────────────────────────────
classes: dict = {"PINNED": [], "RECONSTRUCTIBLE": [], "UNPINNED": []}
for lock in locks:
    slug = lock["slug"]
    t12 = t12_data.get(slug, {})
    t3 = t3_records.get(slug, {})
    cls = t12.get("t2_class", "UNPINNED")
    classes[cls].append(slug)

    t1_rec: dict = {
        "eval_index_passed": lock.get("passed"),
        "eval_index_total": lock.get("total"),
        "official_passed": lock.get("official_passed"),
        "official_total": lock.get("official_total"),
        "not_run": lock.get("not_run", 0),
        "skipped": lock.get("skipped", 0),
        "failed": lock.get("failed", 0),
        "source": lock.get("source"),
        "last_eval_date": lock.get("last_eval_date"),
        "eval_report_path_raw": t12.get("eval_report_path_raw", ""),
        "eval_report_path_resolved": t12.get("eval_report_path_resolved"),
        "eval_report_path_source": t12.get("eval_report_path_source", "none"),
        "eval_report_exists": t12.get("eval_report_exists", False),
        "eval_report_path_flag": t12.get("eval_report_path_flag"),
        "report_test_count": t12.get("report_test_count"),
        "report_passed_count": t12.get("report_passed_count"),
        "report_sha256": t12.get("report_sha256"),
        "report_mtime_iso": t12.get("report_mtime_iso"),
        "report_test_branches": t12.get("report_test_branches", []),
        "report_executable_hash": t12.get("report_executable_hash"),
        "submission_tar_exists": t12.get("submission_tar_exists", False),
        "locked_dir": t12.get("locked_dir"),
        "locked_dir_contents": t12.get("locked_dir_contents", []),
        "t2_class": cls,
        "t3_task_dir": t3.get("task_dir"),
        "t3_tests_json_path": t3.get("tests_json_path"),
        "t3_tests_json_sha256": t3.get("tests_json_sha256"),
        "t3_upstream_commit": t3.get("upstream_commit_from_dir_name"),
        "t3_task_branch_count": t3.get("task_branch_count"),
    }
    output["T1_lock_enumeration"]["per_tool"][slug] = t1_rec

output["T2_cert_fingerprint"]["PINNED"] = classes["PINNED"]
output["T2_cert_fingerprint"]["RECONSTRUCTIBLE"] = classes["RECONSTRUCTIBLE"]
output["T2_cert_fingerprint"]["UNPINNED"] = classes["UNPINNED"]
output["T2_cert_fingerprint"]["counts"] = {
    "PINNED": len(classes["PINNED"]),
    "RECONSTRUCTIBLE": len(classes["RECONSTRUCTIBLE"]),
    "UNPINNED": len(classes["UNPINNED"]),
}

# UNKNOWNS: things we could not determine
output["unknowns"] = [
    {
        "id": "UNK-01",
        "question": "What eval run produced the flamelens eval_index score of 510/510?",
        "reason": (
            "The archived eval_report.json at the indexed path has 622 test_results. "
            "The 510/510 score is recorded in eval_index with last_eval_source=hetzner_nofilter_discriminating_run "
            "but no separate eval log file or JSON with 510 results was found on disk during this audit."
        ),
    },
    {
        "id": "UNK-02",
        "question": "Does ProgramBench enforce any network isolation inside eval containers at the OS or Docker daemon level?",
        "reason": (
            "container.py builds docker run without network flags. No iptables/nftables rules, "
            "netns configuration, or Docker daemon network policy found in any script on disk. "
            "The system prompt claim (determinex_programbench_agent.py:679) describes the PB container "
            "environment behavior but is not an enforcement artifact. "
            "Cannot verify from local files alone -- would require inspecting the live Docker daemon "
            "config or PB upstream issue tracker."
        ),
    },
    {
        "id": "UNK-03",
        "question": "What is the cert-time SHA-256 of each eval_report.json for the 50 locks?",
        "reason": (
            "SHA-256 of each current eval_report.json is recorded in this audit (field report_sha256 in T1 per_tool). "
            "However, no archived SHA-256 value recorded AT CERTIFICATION TIME was found -- "
            "PROTOCOL.md Sec 2 step 2 requires a hash check but no hash archive file was located on disk. "
            "The current SHA-256 may or may not match the cert-time value."
        ),
    },
]

with open("reconciliation_audit.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print("reconciliation_audit.json written.")
print(f"  T1 locks: {len(locks)}")
print(
    f"  T2: PINNED={len(classes['PINNED'])} RECONSTRUCTIBLE={len(classes['RECONSTRUCTIBLE'])} UNPINNED={len(classes['UNPINNED'])}"
)
print(f"  Discrepancies: {len(output['discrepancies'])}")
print(f"  Unknowns: {len(output['unknowns'])}")
