#!/usr/bin/env python3
"""Evidence-only 60-second judge path for the FlightGuard submission."""
from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path
from typing import Any

try:
    import cv2
except ImportError:
    cv2 = None

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "submission" / "evidence"

EXPECTED_SHA256 = {
    "verified-flight-envelope-aggregate.json": "c7ca6e460e967c3070736d8120bd918a3c489f1e7d62a3ae933ab631af827f58",
    "radeon-formal-scaling.json": "98d9b331907f9968ae65054c6f9d840dc0440eb9209c14e955dc628df736f072",
    "v4-summary.json": "4ebab98a9b9c3b134548ef646c30aaafbd7d6ddeaa8a0485b667ee8054f80f8b",
    "v5-summary.json": "d546a620931fc3afb2c074d749e1fe017ba6c4dcdf2d05b570855a913e83b034",
    "v6-checkpoint-30.json": "905925dedc62a41a8b4c35ace8b1c5a1bd1d97c9cb4d43a5f513f3827cf0a678",
    "v6-audit-receipt.json": "521738135a3dcc28dc42ecd8b4f01fe5abe925b8353a45577d0b8b5de9e3e8c1",
    "capture-terminal.json": "923c24124f9af6d53d82a80c9efd72d8e5ada962a4ceb30adf48e232c2c341be",
    "frozen-claim-auditor-benchmark.json": "ccbf38ef7aa36571c3f2433d5f4e9d54b1dd1de7cc2e8f93f2291ccc816f83f7",
}

RAW_METRICS_SHA256 = {
    "training-collector/seed303-metrics.json": "aaa5e1e4654aec24b907527eb5334338a50f328c679eace8208b87f650e36959",
    "training-collector/seed304-metrics.json": "61b70eead81696608a75436db23f59be9f01a25f65d09af9bc81a6d489010b54",
    "training-collector/seed305-metrics.json": "24cadca684b1de7f069f4ffb3767502396c1f38031f35e606157fc7874395955",
    "heldout-three-gate-mission/seed303-metrics.json": "7d30a032a032b3d757a77afbe8ed60aa97c61e54f557ef2ba242251b14f14238",
    "heldout-three-gate-mission/seed304-metrics.json": "c3408cbb720df48690783888e6335b6350c265ad4af8526d72486250aa2204a8",
    "heldout-three-gate-mission/seed305-metrics.json": "e546809527d28df7b25fa82ad2d552de170672c871fee6aed132889f38d8d63e",
}
RAW_METRICS = EVIDENCE / "raw-metrics"

CHALLENGE_EVIDENCE = EVIDENCE / "challenge-arena"
CHALLENGE_SUMMARY_SHA256 = "91b18677fa9fcb5f05acead2aa3fb4324188b44173ea85fda75c67e2dcb129ee"
CHALLENGE_RAW_ARCHIVE = (
    "challenge-arena-raw-json-v1.tar.gz",
    "21647f791444aed708da5e056f17af98258fbc7605bb46acb4a148c0f6a6811b",
    94_002,
)
CHALLENGE_RAW_MEMBER_SHA256 = {
    "noop-seed264617362-recovery-v2.json": "d5a3a13989168452545c13f20c49ab6aa95f6b19626bb9d8617b0d8937e570e4",
    "kill-seed881940697.json": "6f04a6e9ce3182255ef71e8996edaf0f7226dad223cab299119c4aac06c81178",
    "primary-adversarial-seed831900462.json": "d9ab9e8d5423f8f0a69c466cffa5184fe049dae2be98a8bf842d3a87d5ae20f6",
    "primary-adversarial-seed200501215.json": "ed43b7fd267dd7bd56f4be4b627cceb1d6d5f9c08d2527c87539dd5e304c009e",
    "primary-adversarial-seed144856705.json": "f2e94d07896d238e2171f8ebde7cbd2fbc2328df08a32f116d87b501e9cbfa32",
    "retention-heldout-seed831900462.json": "9bc3ffe552a59c5dc5c0a867a923024872dfd388f97f381712a7ad6cc72d688c",
    "retention-heldout-seed200501215.json": "13702b5a7d3b8fbea87a57ed5eb0add444b6c19b62f75c4a360b7e50be0583bb",
    "retention-heldout-seed144856705.json": "4d1ee9db7de0de04a6c2ab815a5a554f7c196774341725b6ac8699c9dcf5a14a",
}

WORKFLOW_ASSETS = (
    (
        "submission/flightguard-challenge-arena-v1.mp4",
        "aabdea74a53e07ba0b77b52cab68a5fd5f5ed03e68b81aa3647ef36d49dd5b65",
        2_146_360,
        (140, 1_280, 720, 20.0),
    ),
    (
        "submission/flightguard-challenge-arena-workflow-demo-v3.mp4",
        "d72057ff2a1bdf1796240a857f6451f545c070204ec6dcbe551f2dd039e00670",
        17_874_513,
        (2_100, 1_280, 720, 10.0),
    ),
    (
        "submission/flightguard-nominal-envelope-demo-v2.mp4",
        "a5f13ea90ed64468299e925721607c2a2e896efc33fc99213f50cb0fa50799fd",
        17_428_715,
        (2_100, 1_280, 720, 10.0),
    ),
    (
        "submission/genesis-nominal-visual-replay.mp4",
        "adc0ea528b611e55dca006d220c30ef935f32448f6b935b7b6c1a33cd9d9fbce",
        3_717_464,
        (500, 1_280, 720, 10.0),
    ),
)

STATIC_FILES = (
    "docs/technical-report.md",
    "submission/video-script.md",
    "demo/faultfork/index.html",
    "demo/faultfork/app.js",
    "demo/faultfork/styles.css",
)
RENDERER_ASSETS = (
    (
        "scripts/render_submission_video.py",
        "a0a17d91e15c92f8541da594c7c2ca04b97ce7c5326f61b08436798caace35cd",
        26_993,
    ),
    (
        "scripts/render_challenge_arena_workflow_video_v3.py",
        "ed138fc753771172b8922ce83b6ebf52a1e2010247aadf87fa1e0cfb9883fe84",
        32_850,
    ),
)
CHALLENGE_CODE_ASSETS = (
    ("configs/challenge_arena_v1.json", "af30cfdaaecb1b00ec477a2a22b96eeaf25b328327b11a43f04f1e570045173d", 2_989),
    ("scripts/run_challenge_arena_amd.py", "cd0898cde2630a686f3cbded0463c06f20dc7b3e9c8a742b4df7ed95ba21c4d6", 27_746),
    ("scripts/summarize_challenge_arena.py", "e966bee62ebd685ff06a7f1054b3468f8568eb08f169ced88e2213fe96c69a26", 14_876),
    ("scripts/render_challenge_arena_pair_amd.py", "9f68a91013b943e4642f86d2ba96472ba41221826f96f9eb363610f7f1dd5e8f", 20_815),
    ("scripts/build_challenge_arena_figure.py", "21fb3afe2b70fb224d7af8e67d2a5777c2a8f73fc4199af11c78abc6b76ba355", 8_032),
)
CHALLENGE_STATIC_ASSETS = (
    ("submission/figures/challenge-arena.svg", "7144d4c82a774a5249f45faf6073ee9a12900128390170cb072ffa18feff4532", 10_135),
    ("submission/figures/challenge-arena-terminal.png", "1d60af874454fffd6d1c7064e90606551534b2748cee717d2cd27c5c85a21d01", 678_621),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path.relative_to(ROOT)}")
    return value


def equal(errors: list[str], label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, got {actual!r}")


def check_video(
    errors: list[str],
    relative: str,
    expected_sha: str,
    expected_size: int,
    expected_meta: tuple[int, int, int, float],
) -> int:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing workflow asset: {relative}")
        return 0
    equal(errors, f"size {relative}", path.stat().st_size, expected_size)
    equal(errors, f"SHA {relative}", sha256(path), expected_sha)
    if cv2 is None:
        errors.append(f"OpenCV unavailable for video metadata: {relative}")
        return 0
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            errors.append(f"cannot open workflow video: {relative}")
            return 0
        actual = (
            int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT))),
            int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))),
            int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))),
            float(capture.get(cv2.CAP_PROP_FPS)),
        )
    finally:
        capture.release()
    equal(errors, f"video frames/size {relative}", actual[:3], expected_meta[:3])
    if abs(actual[3] - expected_meta[3]) > 1e-6:
        errors.append(f"video fps {relative}: expected {expected_meta[3]}, got {actual[3]}")
    return actual[0]


def mp4_handler_types(path: Path) -> list[str]:
    raw = path.read_bytes()
    handlers: list[str] = []
    start = 0
    while True:
        offset = raw.find(b"hdlr", start)
        if offset < 0:
            return handlers
        handlers.append(raw[offset + 12 : offset + 16].decode("ascii", "replace"))
        start = offset + 4


def main() -> int:
    errors: list[str] = []
    documents: dict[str, dict[str, Any]] = {}

    for name, expected_sha in EXPECTED_SHA256.items():
        path = EVIDENCE / name
        if not path.is_file():
            errors.append(f"missing evidence: submission/evidence/{name}")
            continue
        actual_sha = sha256(path)
        if actual_sha != expected_sha:
            errors.append(f"SHA mismatch: {name} expected {expected_sha}, got {actual_sha}")
            continue
        try:
            documents[name] = load_object(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid JSON: {name}: {exc}")

    raw_documents: dict[str, dict[str, Any]] = {}
    for relative, expected_sha in RAW_METRICS_SHA256.items():
        path = RAW_METRICS / relative
        if not path.is_file():
            errors.append(f"missing raw metric: submission/evidence/raw-metrics/{relative}")
            continue
        actual_sha = sha256(path)
        if actual_sha != expected_sha:
            errors.append(f"raw metric SHA mismatch: {relative} expected {expected_sha}, got {actual_sha}")
            continue
        try:
            raw_documents[relative] = load_object(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid raw metric JSON: {relative}: {exc}")

    challenge_documents: dict[str, dict[str, Any]] = {}
    challenge_summary_path = CHALLENGE_EVIDENCE / "challenge-arena-summary.json"
    if not challenge_summary_path.is_file():
        errors.append("missing Challenge Arena summary")
    elif sha256(challenge_summary_path) != CHALLENGE_SUMMARY_SHA256:
        errors.append("Challenge Arena summary SHA mismatch")
    else:
        try:
            challenge_documents["challenge-arena-summary.json"] = load_object(challenge_summary_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid Challenge Arena summary: {exc}")

    archive_name, archive_sha, archive_size = CHALLENGE_RAW_ARCHIVE
    archive_path = CHALLENGE_EVIDENCE / archive_name
    if not archive_path.is_file():
        errors.append(f"missing Challenge Arena raw archive: {archive_name}")
    else:
        equal(errors, "Challenge Arena raw archive size", archive_path.stat().st_size, archive_size)
        equal(errors, "Challenge Arena raw archive SHA", sha256(archive_path), archive_sha)
        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                members = archive.getmembers()
                equal(errors, "Challenge Arena raw archive members", [member.name for member in members], sorted(CHALLENGE_RAW_MEMBER_SHA256))
                for member in members:
                    if not member.isfile() or member.name not in CHALLENGE_RAW_MEMBER_SHA256:
                        errors.append(f"invalid Challenge Arena archive member: {member.name}")
                        continue
                    handle = archive.extractfile(member)
                    if handle is None:
                        errors.append(f"unreadable Challenge Arena archive member: {member.name}")
                        continue
                    payload = handle.read()
                    actual_sha = hashlib.sha256(payload).hexdigest()
                    equal(errors, f"Challenge Arena member SHA {member.name}", actual_sha, CHALLENGE_RAW_MEMBER_SHA256[member.name])
                    try:
                        value = json.loads(payload)
                        if not isinstance(value, dict):
                            raise ValueError("JSON root is not an object")
                        challenge_documents[member.name] = value
                    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                        errors.append(f"invalid Challenge Arena archive JSON {member.name}: {exc}")
        except (OSError, tarfile.TarError) as exc:
            errors.append(f"invalid Challenge Arena raw archive: {exc}")

    if len(documents) == len(EXPECTED_SHA256):
        envelope = documents["verified-flight-envelope-aggregate.json"]
        equal(errors, "envelope simulation-only", envelope.get("simulation_only"), True)
        equal(errors, "envelope existing-metrics-only", envelope.get("generated_from_existing_metrics_only"), True)
        equal(errors, "envelope source commit", envelope.get("source_commit"), "5f56f9ca3bd236f752844d2e3518276d9f494d8c")

        mission = envelope["heldout_three_gate_mission"]["aggregate"]
        equal(errors, "paired heldout course contexts", mission.get("paired_course_contexts"), 384)
        equal(errors, "method episodes", mission.get("method_episodes"), 1_152)
        equal(errors, "mission all finite", mission.get("all_fields_finite"), True)
        equal(errors, "mission one Radeon", mission.get("all_runs_one_visible_radeon"), True)
        equal(errors, "mission source statuses", mission.get("all_source_status_pass"), True)
        equal(errors, "mission saturation field present", mission.get("motor_saturation_recorded_in_source_metrics"), False)
        equal(errors, "mass min/max", (mission.get("mass_scale_min"), mission.get("mass_scale_max")), (0.8004579544067383, 1.1993319988250732))
        equal(errors, "thrust min/max", (mission.get("thrust_scale_min"), mission.get("thrust_scale_max")), (0.8060941696166992, 1.1986122131347656))
        equal(errors, "wind max", mission.get("wind_acceleration_norm_max_mps2"), 0.5982784032821655)
        equal(errors, "delay min/max", (mission.get("action_delay_steps_min"), mission.get("action_delay_steps_max")), (0, 6))
        equal(errors, "dropout-minus-mean-terminal", mission.get("dropout_minus_mean_terminal_step_by_seed"), [534.2578125, 532.53125, 532.6953125])

        for method in ("constant_velocity", "hold_last", "learned"):
            result = mission["per_method"][method]
            equal(errors, f"{method} evaluated envs", result.get("evaluated_envs"), 384)
            equal(errors, f"{method} mission successes", result.get("mission_success_count"), 384)
            equal(errors, f"{method} gate passes", result.get("gate_passes_total"), 1_152)
            for field in ("mission_failure_count", "strike_count", "terminal_failure_count", "unfinished_count"):
                equal(errors, f"{method} {field}", result.get(field), 0)

        claim = envelope["claim_boundary"]
        for key in (
            "continuous_envelope_guarantee_claim",
            "dropout_recovery_claim",
            "learned_superiority_claim",
            "real_flight_claim",
            "safety_or_certification_claim",
            "sim_to_real_claim",
        ):
            equal(errors, f"claim boundary {key}", claim.get(key), False)

        collector = envelope["training_distribution_collector"]["aggregate"]
        if len(raw_documents) == len(RAW_METRICS_SHA256):
            mission_raw = [
                raw_documents[f"heldout-three-gate-mission/seed{seed}-metrics.json"]
                for seed in (303, 304, 305)
            ]
            collector_raw = [
                raw_documents[f"training-collector/seed{seed}-metrics.json"]
                for seed in (303, 304, 305)
            ]

            raw_paired_contexts = sum(int(item["pairs"]) for item in mission_raw)
            raw_method_episodes = sum(int(item["total_envs"]) for item in mission_raw)
            equal(errors, "raw paired heldout course contexts", raw_paired_contexts, 384)
            equal(errors, "raw method episodes", raw_method_episodes, 1_152)
            equal(errors, "raw mission statuses", [item["status"] for item in mission_raw], ["PASS"] * 3)
            equal(errors, "raw mission visible GPU count", [item["visible_gpu_count"] for item in mission_raw], [1, 1, 1])
            equal(errors, "raw mission GPU names", [item["gpu_name"] for item in mission_raw], ["AMD Radeon Graphics"] * 3)
            equal(
                errors,
                "raw mission integrity",
                [item["integrity"]["checks"]["all_tracked_tensors_finite"] for item in mission_raw],
                [True, True, True],
            )
            for item in mission_raw:
                for method_name, finite_fields in item["integrity"]["finite_by_method"].items():
                    equal(
                        errors,
                        f"raw mission finite fields seed {item['seed']} {method_name}",
                        all(finite_fields.values()),
                        True,
                    )
            for method in ("constant_velocity", "hold_last", "learned"):
                method_rows = [item["methods"][method] for item in mission_raw]
                success = sum(int(row["mission_success_count"]) for row in method_rows)
                gates = sum(int(row["gate_passes_total"]) for row in method_rows)
                equal(errors, f"raw {method} mission successes", success, 384)
                equal(errors, f"raw {method} gate passes", gates, 1_152)
                for field in ("mission_failure_count", "strike_count", "terminal_failure_count", "unfinished_count"):
                    equal(
                        errors,
                        f"raw {method} {field}",
                        sum(int(row[field]) for row in method_rows),
                        0,
                    )
                equal(
                    errors,
                    f"raw/aggregate {method} mission successes",
                    success,
                    mission["per_method"][method]["mission_success_count"],
                )
                equal(
                    errors,
                    f"raw/aggregate {method} gate passes",
                    gates,
                    mission["per_method"][method]["gate_passes_total"],
                )

            raw_survivors = [int(item["collector"]["survivor_count"]) for item in collector_raw]
            equal(errors, "raw collector survivors by seed", raw_survivors, [63, 62, 61])
            equal(errors, "raw collector survivors total", sum(raw_survivors), 186)
            equal(
                errors,
                "raw collector visible GPU count",
                [item["single_gpu_proof"]["visible_gpu_count"] for item in collector_raw],
                [1, 1, 1],
            )
            equal(
                errors,
                "raw collector GPU names",
                [item["single_gpu_proof"]["gpu_name"] for item in collector_raw],
                ["AMD Radeon Graphics"] * 3,
            )
            for item in collector_raw:
                seed = item["args"]["seed"]
                equal(errors, f"raw collector status seed {seed}", item["status"], "PASS")
                equal(
                    errors,
                    f"raw collector finite seed {seed}",
                    all(field["all"] for field in item["collector"]["finite"].values()),
                    True,
                )
                equal(
                    errors,
                    f"raw collector applied saturation seed {seed}",
                    item["collector"]["motor_saturation"]["applied_action"]["max_per_env_fraction"],
                    0.0,
                )
            equal(errors, "raw/aggregate paired contexts", raw_paired_contexts, mission["paired_course_contexts"])
            equal(errors, "raw/aggregate method episodes", raw_method_episodes, mission["method_episodes"])
            equal(errors, "raw/aggregate collector survivors", sum(raw_survivors), collector["survivors"])

        equal(errors, "collector environments", collector.get("environments"), 192)
        equal(errors, "collector survivors", collector.get("survivors"), 186)
        equal(errors, "collector survivor fraction", collector.get("survivor_fraction"), 0.96875)
        equal(errors, "collector all finite", collector.get("all_fields_finite"), True)
        equal(errors, "collector one Radeon", collector.get("all_runs_one_visible_radeon"), True)
        equal(errors, "collector applied saturation", collector.get("max_applied_action_per_env_saturation_fraction"), 0.0)

        scaling = documents["radeon-formal-scaling.json"]["scaling"]
        summaries = scaling["env_summaries"]
        equal(errors, "scaling status", scaling.get("status"), "PASS")
        equal(errors, "scaling transitions", scaling.get("total_measured_transitions"), 2_227_200)
        equal(errors, "scaling env counts", [item["env_count"] for item in summaries], [32, 128, 256, 512])
        equal(errors, "scaling throughput", [item["mean_transitions_per_s"] for item in summaries], [4632.582556654058, 18354.411592309174, 36383.01129648785, 74246.46385791198])
        equal(errors, "scaling speedup", summaries[-1]["speedup_vs_32_envs"], 16.027013647337444)
        equal(errors, "scaling efficiency", summaries[-1]["parallel_efficiency_vs_32_envs"], 1.0016883529585903)

        v4 = documents["v4-summary.json"]
        equal(errors, "v4 status", v4.get("status"), "FAIL")
        equal(errors, "v4 Patch/Action/Raw/Cal", [v4["metrics"][arm]["fault"]["mission_success_count"] for arm in ("CausalIMUPatch", "ActionOnly", "RawStrapdown", "CalibratedStrapdown")], [11, 0, 33, 32])

        v5 = documents["v5-summary.json"]
        equal(errors, "v5 formal eligibility", v5.get("formal_claim_eligible"), False)
        equal(errors, "v5 award eligibility", v5.get("award_evidence_eligible"), False)

        v6 = documents["v6-checkpoint-30.json"]
        lanes = v6.get("lanes", [])
        equal(errors, "v6 status", v6.get("status"), "FAIL")
        equal(errors, "v6 admitted lanes", v6.get("admitted_lane_count"), 0)
        equal(errors, "v6 exact-Cal fallback", sum(all(lane["fallback_integrity_checks"].values()) for lane in lanes), 12)

        terminal = documents["capture-terminal.json"]
        equal(errors, "capture status", terminal.get("status"), "complete")
        equal(errors, "capture jobs", [job.get("name") for job in terminal.get("completed_jobs", [])], ["capture-checkpoint-30", "capture-checkpoint-31", "capture-checkpoint-32"])

        auditor = documents["frozen-claim-auditor-benchmark.json"]
        equal(errors, "auditor status", auditor.get("status"), "PASS")
        equal(errors, "auditor confusion", [auditor["confusion"][key] for key in ("true_positive", "true_negative", "false_positive", "false_negative")], [1, 3, 0, 0])

    if len(challenge_documents) == 1 + len(CHALLENGE_RAW_MEMBER_SHA256):
        challenge = challenge_documents["challenge-arena-summary.json"]
        equal(errors, "Challenge Arena status", challenge.get("status"), "PASS")
        equal(errors, "Challenge Arena simulation-only", challenge.get("simulation_only"), True)
        challenge_gates = challenge.get("gates", {})
        equal(errors, "Challenge Arena gate count", len(challenge_gates), 14)
        equal(errors, "Challenge Arena all gates", all(challenge_gates.values()), True)

        primary = challenge["primary"]
        equal(errors, "Challenge Arena primary pairs", primary.get("pair_count"), 384)
        equal(errors, "Challenge Arena primary nominal/robust", [primary.get("nominal_success_count"), primary.get("robust_success_count")], [194, 371])
        equal(errors, "Challenge Arena primary delta", [primary.get("success_delta_count"), primary.get("success_delta_percentage_points")], [177, 46.09375])
        equal(errors, "Challenge Arena primary nominal-only wins", primary.get("nominal_only_success"), 0)
        equal(errors, "Challenge Arena primary failure reduction", primary.get("failure_reduction_fraction"), 0.9315789473684211)
        equal(errors, "Challenge Arena primary strikes", [primary.get("nominal_strike_count"), primary.get("robust_strike_count")], [178, 13])
        equal(errors, "Challenge Arena primary terminal failures", [primary.get("nominal_terminal_failure_count"), primary.get("robust_terminal_failure_count")], [190, 13])
        equal(errors, "Challenge Arena primary saturation", primary.get("maximum_applied_saturation_fraction"), {"nominal": 0.0, "robust_z": 0.0})
        equal(errors, "Challenge Arena primary per-seed deltas", sorted(primary.get("per_seed_success_delta", {}).values()), [57, 58, 62])

        retention = challenge["retention"]
        equal(errors, "Challenge Arena retention pairs", retention.get("pair_count"), 192)
        equal(errors, "Challenge Arena retention nominal/robust", [retention.get("nominal_success_count"), retention.get("robust_success_count")], [121, 192])
        equal(errors, "Challenge Arena retention delta", retention.get("success_delta_count"), 71)
        equal(errors, "Challenge Arena retention nominal-only wins", retention.get("nominal_only_success"), 0)
        equal(errors, "Challenge Arena retention saturation", retention.get("maximum_applied_saturation_fraction"), {"nominal": 0.0, "robust_z": 0.0})

        noop = challenge_documents["noop-seed264617362-recovery-v2.json"]
        equal(errors, "Challenge Arena no-op status", noop.get("status"), "PASS")
        equal(errors, "Challenge Arena no-op bit exact", noop.get("diagnostic", {}).get("bit_exact"), True)
        equal(errors, "Challenge Arena no-op fields", noop.get("diagnostic", {}).get("required_fields"), ["issued_action", "applied_action", "state", "gate", "terminal"])

        kill = challenge_documents["kill-seed881940697.json"]
        equal(errors, "Challenge Arena kill status", kill.get("status"), "PASS")
        equal(errors, "Challenge Arena kill zero-action success", kill["arms"]["zero_action"].get("mission_success_count"), 0)
        equal(errors, "Challenge Arena kill divergence", kill.get("diagnostic", {}).get("maximum_position_divergence_m"), 10.506417274475098)
        equal(errors, "Challenge Arena kill checks", all(kill.get("diagnostic", {}).get("checks", {}).values()), True)

        source_rows = challenge["per_seed"]["primary"] + challenge["per_seed"]["retention"]
        equal(errors, "Challenge Arena one visible Radeon", [row["runtime"]["visible_gpu_count"] for row in source_rows], [1] * 6)
        equal(errors, "Challenge Arena GPU name", [row["runtime"]["gpu_name"] for row in source_rows], ["AMD Radeon Graphics"] * 6)
        boundaries = challenge["claim_boundary"]
        for key in ("real_flight_claim", "safety_or_certification_claim", "sim_to_real_claim", "sota_baseline_claim", "tuning_after_unblinding_permitted"):
            equal(errors, f"Challenge Arena boundary {key}", boundaries.get(key), False)

    for relative in STATIC_FILES:
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing or empty submission file: {relative}")

    for renderer_relative, renderer_sha, renderer_size in RENDERER_ASSETS:
        renderer_path = ROOT / renderer_relative
        if not renderer_path.is_file():
            errors.append(f"missing renderer: {renderer_relative}")
        else:
            equal(errors, f"renderer size {renderer_relative}", renderer_path.stat().st_size, renderer_size)
            equal(errors, f"renderer SHA {renderer_relative}", sha256(renderer_path), renderer_sha)

    for relative, expected_sha, expected_size in CHALLENGE_CODE_ASSETS + CHALLENGE_STATIC_ASSETS:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing Challenge Arena asset: {relative}")
            continue
        equal(errors, f"size {relative}", path.stat().st_size, expected_size)
        equal(errors, f"SHA {relative}", sha256(path), expected_sha)

    video_frames: dict[str, int] = {}
    for relative, expected_sha, expected_size, expected_meta in WORKFLOW_ASSETS:
        video_frames[relative] = check_video(errors, relative, expected_sha, expected_size, expected_meta)

    primary_video = ROOT / "submission/flightguard-challenge-arena-workflow-demo-v3.mp4"
    if primary_video.is_file() and cv2 is not None:
        capture = cv2.VideoCapture(str(primary_video))
        try:
            fourcc_value = int(round(capture.get(cv2.CAP_PROP_FOURCC)))
        finally:
            capture.release()
        codec = "".join(chr((fourcc_value >> (8 * index)) & 0xFF) for index in range(4))
        equal(errors, "primary reviewer video codec", codec, "FMP4")
        handlers = mp4_handler_types(primary_video)
        equal(errors, "primary reviewer video video-track count", handlers.count("vide"), 1)
        equal(errors, "primary reviewer video audio-track count", handlers.count("soun"), 0)

    if errors:
        print("FlightGuard judge smoke: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("FlightGuard judge smoke: PASS")
    print("raw metrics 6/6 | submitted aggregate verified")
    print("nominal envelope | 384 paired contexts | 1152 method episodes | every method 384/384")
    print("mission integrity | 0 strikes | 0 mission/terminal failures | 0 unfinished | all finite")
    print("collector | 186/192 survivors | all tracked fields finite | applied saturation max 0.0")
    print("challenge arena | primary 194/384 -> 371/384 (+46.1 pp) | retention 121/192 -> 192/192 | 0 regressions")
    print("challenge self-tests | no-op bit-exact | kill 0/8 success and 10.506417 m divergence | 14/14 gates")
    print("sampled ranges | mass 0.80046-1.19933 | thrust 0.80609-1.19861 | wind 0-0.59828 m/s^2 | delay 0-6")
    print("Radeon | 2,227,200 transitions | 4,632.58 -> 74,246.46 transitions/s | 16.027013647337444x")
    print(f"workflow assets | Challenge Arena {video_frames['submission/flightguard-challenge-arena-v1.mp4']}/140 | primary v3 {video_frames['submission/flightguard-challenge-arena-workflow-demo-v3.mp4']}/2100 | historical v2 {video_frames['submission/flightguard-nominal-envelope-demo-v2.mp4']}/2100 | Genesis clip {video_frames['submission/genesis-nominal-visual-replay.mp4']}/500")
    print("boundaries | simulation-only | sampled, not continuous | no SOTA/safety/sim-to-real/real-flight claim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
