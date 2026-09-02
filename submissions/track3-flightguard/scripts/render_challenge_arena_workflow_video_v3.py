#!/usr/bin/env python3
"""Render the primary FlightGuard Challenge Arena workflow video from frozen evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

WIDTH = 1280
HEIGHT = 720
FPS = 10.0
DURATION_SECONDS = 210.0
FRAME_COUNT = 2100
FOURCC = "mp4v"
FONT = cv2.FONT_HERSHEY_SIMPLEX
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "submission/flightguard-challenge-arena-workflow-demo-v3.mp4"

CHALLENGE_CLIP = PROJECT_ROOT / "submission/flightguard-challenge-arena-v1.mp4"
CHALLENGE_SUMMARY = PROJECT_ROOT / "submission/evidence/challenge-arena/challenge-arena-summary.json"
CHALLENGE_CONFIG = PROJECT_ROOT / "configs/challenge_arena_v1.json"
CHALLENGE_ARCHIVE = (
    PROJECT_ROOT
    / "submission/evidence/challenge-arena/challenge-arena-raw-json-v1.tar.gz"
)
SCALING_EVIDENCE = PROJECT_ROOT / "submission/evidence/radeon-formal-scaling.json"

EXPECTED = {
    "challenge_clip": (
        "aabdea74a53e07ba0b77b52cab68a5fd5f5ed03e68b81aa3647ef36d49dd5b65",
        2_146_360,
    ),
    "challenge_summary": (
        "91b18677fa9fcb5f05acead2aa3fb4324188b44173ea85fda75c67e2dcb129ee",
        25_395,
    ),
    "challenge_config": (
        "af30cfdaaecb1b00ec477a2a22b96eeaf25b328327b11a43f04f1e570045173d",
        2_989,
    ),
    "challenge_archive": (
        "21647f791444aed708da5e056f17af98258fbc7605bb46acb4a148c0f6a6811b",
        94_002,
    ),
    "scaling": (
        "98d9b331907f9968ae65054c6f9d840dc0440eb9209c14e955dc628df736f072",
        11_436,
    ),
}
RAW_MEMBER_SHA = {
    "noop-seed264617362-recovery-v2.json":
        "d5a3a13989168452545c13f20c49ab6aa95f6b19626bb9d8617b0d8937e570e4",
    "kill-seed881940697.json":
        "6f04a6e9ce3182255ef71e8996edaf0f7226dad223cab299119c4aac06c81178",
}

BG = (23, 19, 15)
PANEL = (42, 34, 27)
PANEL_ALT = (52, 43, 34)
INK = (245, 241, 235)
MUTED = (185, 174, 160)
BLUE = (245, 165, 89)
GREEN = (141, 214, 88)
RED = (107, 107, 255)
AMBER = (96, 189, 246)
LINE = (78, 66, 55)
BLACK = (12, 10, 9)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_verified_json(role: str, path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    expected_sha, expected_size = EXPECTED[role]
    require(len(raw) == expected_size, f"{role} size mismatch")
    require(sha256_bytes(raw) == expected_sha, f"{role} SHA-256 mismatch")
    value = json.loads(raw)
    require(isinstance(value, dict), f"{role} root must be an object")
    return value


def load_diagnostic_members() -> tuple[dict[str, Any], dict[str, Any]]:
    raw = CHALLENGE_ARCHIVE.read_bytes()
    expected_sha, expected_size = EXPECTED["challenge_archive"]
    require(len(raw) == expected_size, "challenge archive size mismatch")
    require(sha256_bytes(raw) == expected_sha, "challenge archive SHA-256 mismatch")
    values: dict[str, dict[str, Any]] = {}
    with tarfile.open(CHALLENGE_ARCHIVE, "r:gz") as archive:
        names = set(archive.getnames())
        for name, expected in RAW_MEMBER_SHA.items():
            require(name in names, f"missing diagnostic archive member: {name}")
            handle = archive.extractfile(name)
            require(handle is not None, f"cannot read archive member: {name}")
            member_raw = handle.read()
            require(sha256_bytes(member_raw) == expected, f"{name} SHA mismatch")
            value = json.loads(member_raw)
            require(isinstance(value, dict), f"{name} root must be an object")
            values[name] = value
    return (
        values["noop-seed264617362-recovery-v2.json"],
        values["kill-seed881940697.json"],
    )


def open_verified_challenge_clip() -> cv2.VideoCapture:
    raw = CHALLENGE_CLIP.read_bytes()
    expected_sha, expected_size = EXPECTED["challenge_clip"]
    require(len(raw) == expected_size, "Challenge Arena clip size mismatch")
    require(sha256_bytes(raw) == expected_sha, "Challenge Arena clip SHA mismatch")
    capture = cv2.VideoCapture(str(CHALLENGE_CLIP))
    require(capture.isOpened(), "Challenge Arena clip cannot be opened")
    frame_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    require(frame_count == 140, "Challenge Arena clip frame-count mismatch")
    require(width == WIDTH and height == HEIGHT, "Challenge Arena clip dimensions mismatch")
    require(abs(fps - 20.0) < 0.01, "Challenge Arena clip fps mismatch")
    return capture


def evidence_values() -> dict[str, Any]:
    summary = load_verified_json("challenge_summary", CHALLENGE_SUMMARY)
    config = load_verified_json("challenge_config", CHALLENGE_CONFIG)
    scaling = load_verified_json("scaling", SCALING_EVIDENCE)
    noop, kill = load_diagnostic_members()

    require(summary["status"] == "PASS", "Challenge Arena status drift")
    require(summary["simulation_only"] is True, "Challenge Arena scope drift")
    require(all(summary["gates"].values()), "Challenge Arena gate drift")
    primary = summary["primary"]
    retention = summary["retention"]
    require(primary["pair_count"] == 384, "primary pair count drift")
    require(primary["nominal_success_count"] == 194, "primary nominal drift")
    require(primary["robust_success_count"] == 371, "primary robust drift")
    require(primary["success_delta_count"] == 177, "primary delta drift")
    require(primary["nominal_only_success"] == 0, "primary regression drift")
    require(retention["pair_count"] == 192, "retention pair count drift")
    require(retention["nominal_success_count"] == 121, "retention nominal drift")
    require(retention["robust_success_count"] == 192, "retention robust drift")
    require(retention["success_delta_count"] == 71, "retention delta drift")
    require(retention["nominal_only_success"] == 0, "retention regression drift")

    baseline = config["baseline"]
    candidate = config["candidate"]
    require(config["paired_design"]["only_controller_profile_changes"] is True, "pairing drift")
    require(baseline["position_kp_z"] == 2.5 and baseline["velocity_kd_z"] == 2.0, "baseline gain drift")
    require(candidate["position_kp_z"] == 8.0 and candidate["velocity_kd_z"] == 3.6, "candidate gain drift")

    require(noop["status"] == "PASS" and noop["mode"] == "noop", "no-op status drift")
    require(noop["diagnostic"]["bit_exact"] is True, "no-op exactness drift")
    require(noop["runtime"]["visible_gpu_count"] == 1, "no-op GPU count drift")
    require(noop["runtime"]["gpu_name"] == "AMD Radeon Graphics", "no-op GPU name drift")
    for key, value in noop["integrity"].items():
        require(value is True, f"no-op integrity drift: {key}")

    require(kill["status"] == "PASS" and kill["mode"] == "kill", "kill status drift")
    require(kill["arms"]["zero_action"]["mission_success_count"] == 0, "kill success drift")
    require(kill["arms"]["zero_action"]["gate_passes_total"] == 0, "kill gate drift")
    require(kill["diagnostic"]["maximum_position_divergence_m"] == 10.506417274475098, "kill divergence drift")
    require(all(kill["diagnostic"]["checks"].values()), "kill diagnostic drift")

    scale = scaling["scaling"]
    require(scaling["status"] == "PASS" and scale["status"] == "PASS", "scaling status drift")
    require(scale["total_measured_transitions"] == 2_227_200, "scaling transition drift")
    rows = scale["env_summaries"]
    require([row["env_count"] for row in rows] == [32, 128, 256, 512], "scaling env drift")
    require(rows[-1]["speedup_vs_32_envs"] == 16.027013647337444, "scaling speedup drift")

    return {
        "primary": primary,
        "retention": retention,
        "baseline": baseline,
        "candidate": candidate,
        "noop": noop,
        "kill": kill,
        "scaling": scale,
        "scaling_rows": rows,
    }


def put_text(
    image: np.ndarray,
    text: str,
    x: int,
    y: int,
    *,
    scale: float = 0.55,
    color: tuple[int, int, int] = INK,
    thickness: int = 1,
) -> None:
    cv2.putText(image, text, (x, y), FONT, scale, color, thickness, cv2.LINE_AA)


def wrap_lines(text: str, max_width: int, scale: float, thickness: int = 1) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = word if not current else f"{current} {word}"
        if current and cv2.getTextSize(candidate, FONT, scale, thickness)[0][0] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def put_wrapped(
    image: np.ndarray,
    text: str,
    x: int,
    y: int,
    max_width: int,
    *,
    scale: float = 0.55,
    color: tuple[int, int, int] = INK,
    thickness: int = 1,
    line_height: int = 27,
) -> int:
    for line in wrap_lines(text, max_width, scale, thickness):
        put_text(image, line, x, y, scale=scale, color=color, thickness=thickness)
        y += line_height
    return y


def base_slide(section: str, title: str, subtitle: str) -> np.ndarray:
    image = np.full((HEIGHT, WIDTH, 3), BG, dtype=np.uint8)
    put_text(image, section.upper(), 68, 55, scale=0.42, color=BLUE, thickness=2)
    put_text(image, title, 68, 112, scale=0.95, color=INK, thickness=2)
    put_wrapped(image, subtitle, 70, 152, 1130, scale=0.46, color=MUTED, line_height=23)
    cv2.line(image, (68, 190), (1212, 190), LINE, 2)
    return image


def panel(
    image: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    value: str,
    color: tuple[int, int, int],
    note: str = "",
) -> None:
    cv2.rectangle(image, (x, y), (x + w, y + h), PANEL, -1)
    cv2.rectangle(image, (x, y), (x + 7, y + h), color, -1)
    put_text(image, title.upper(), x + 23, y + 33, scale=0.39, color=MUTED)
    put_text(image, value, x + 23, y + 78, scale=0.74, color=color, thickness=2)
    if note:
        put_wrapped(image, note, x + 23, y + 111, w - 42, scale=0.35, color=INK, line_height=18)


def add_caption(image: np.ndarray, caption: str, elapsed: float) -> np.ndarray:
    frame = image.copy()
    cv2.rectangle(frame, (0, 650), (WIDTH, HEIGHT), BLACK, -1)
    put_wrapped(frame, caption, 42, 677, 1010, scale=0.42, color=INK, line_height=20)
    put_text(frame, f"{elapsed:06.1f}s / 210.0s", 1083, 686, scale=0.34, color=MUTED)
    cv2.rectangle(frame, (0, 714), (WIDTH, 719), PANEL_ALT, -1)
    cv2.rectangle(frame, (0, 714), (int(WIDTH * elapsed / DURATION_SECONDS), 719), BLUE, -1)
    return frame


def annotate_challenge(frame: np.ndarray, elapsed: float) -> np.ndarray:
    result = frame.copy()
    cv2.rectangle(result, (0, 0), (WIDTH, 45), BLACK, -1)
    put_text(result, "CHALLENGE ARENA | FROZEN PAIRED GENESIS REPLAY | SIMULATION ONLY", 28, 30, scale=0.50, color=INK, thickness=2)
    cv2.rectangle(result, (0, 650), (WIDTH, HEIGHT), BLACK, -1)
    caption = "Same scene and random stream: nominal collides; robust_z clears all three gates."
    put_text(result, caption, 34, 680, scale=0.44, color=INK, thickness=1)
    put_text(result, f"{elapsed:04.1f}s", 1160, 680, scale=0.38, color=MUTED)
    cv2.rectangle(result, (0, 714), (WIDTH, 719), PANEL_ALT, -1)
    cv2.rectangle(result, (0, 714), (int(WIDTH * elapsed / DURATION_SECONDS), 719), BLUE, -1)
    return result


def draw_title(values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "01 / product",
        "FlightGuard",
        "Challenge Arena controller qualification on Genesis, PyTorch ROCm, and one AMD Radeon.",
    )
    put_text(image, "SIMULATION-ONLY PHYSICAL AI", 70, 250, scale=0.60, color=AMBER, thickness=2)
    put_text(image, "From a visible failure to a reproducible controller decision.", 70, 295, scale=0.58, color=INK)
    panel(image, 70, 355, 350, 190, "matched contexts", "384 + 192", GREEN, "Primary adversarial and retention heldout paired suites.")
    panel(image, 465, 355, 350, 190, "primary success", "50.5% -> 96.6%", BLUE, "194/384 to 371/384; zero nominal-only wins.")
    panel(image, 860, 355, 350, 190, "execution", "ONE RADEON", AMBER, "Genesis 1.2.3 through PyTorch ROCm.")
    put_text(image, "Evidence is frozen before this video is rendered.", 70, 610, scale=0.48, color=MUTED)
    return image


def draw_workflow(_values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "02 / workflow",
        "Freeze -> pair -> simulate -> gate -> reproduce",
        "One hypothesis, matched initial state and disturbances, then hash-bound outputs.",
    )
    steps = [
        ("01", "Freeze", "controller gains + acceptance"),
        ("02", "Pair", "same state, gates, domain, RNG"),
        ("03", "Genesis", "batched mission on ROCm"),
        ("04", "Gate", "success, regression, finite, saturation"),
        ("05", "Export", "raw JSON, summary, video"),
    ]
    x = 62
    for index, (number, title, note) in enumerate(steps):
        w = 208
        cv2.rectangle(image, (x, 250), (x + w, 475), PANEL if index % 2 == 0 else PANEL_ALT, -1)
        put_text(image, number, x + 18, 287, scale=0.48, color=BLUE, thickness=2)
        put_text(image, title, x + 18, 338, scale=0.62, color=INK, thickness=2)
        put_wrapped(image, note, x + 18, 382, w - 34, scale=0.36, color=MUTED, line_height=20)
        if index < len(steps) - 1:
            put_text(image, ">", x + w + 8, 368, scale=0.72, color=BLUE, thickness=2)
        x += 242
    put_text(image, "The paired controller intervention is isolated before formal seeds run.", 70, 555, scale=0.53, color=GREEN, thickness=2)
    put_text(image, "All displayed metrics are read from committed frozen evidence.", 70, 600, scale=0.48, color=MUTED)
    return image


def draw_remote(values: dict[str, Any]) -> np.ndarray:
    noop = values["noop"]
    runtime = noop["runtime"]
    image = base_slide(
        "03 / real remote run",
        "Radeon + ROCm + Genesis",
        "Frozen no-op diagnostic output from the submitted Challenge Arena evidence.",
    )
    cv2.rectangle(image, (65, 225), (1215, 606), (8, 11, 13), -1)
    lines = [
        ("$ HIP_VISIBLE_DEVICES=0 /opt/venv/bin/python3.12 \\", GREEN),
        ("    scripts/reconstruct_challenge_arena_amd.py --mode noop ...", INK),
        (f"Genesis {runtime['genesis_version']} | PyTorch {runtime['torch_version']}", MUTED),
        (f"HIP {runtime['torch_hip']} | device {runtime['device']} | visible GPU 1", MUTED),
        (f"GPU: {runtime['gpu_name']} | simulated transitions: {runtime['simulated_transitions']:,}", MUTED),
        ("PASS | status=PASS | diagnostic.bit_exact=true", GREEN),
        ("PASS | all fields finite | paired contexts exact | one visible Radeon", GREEN),
    ]
    y = 270
    for text, color in lines:
        put_text(image, text, 88, y, scale=0.47, color=color, thickness=1 if color != GREEN else 2)
        y += 45
    put_text(image, "Source: frozen no-op raw JSON, not a synthetic benchmark card.", 70, 635, scale=0.42, color=AMBER)
    return image


def draw_primary(values: dict[str, Any]) -> np.ndarray:
    primary = values["primary"]
    image = base_slide(
        "04 / primary adversarial suite",
        "The controller change survives the hard distribution",
        "Three preregistered seeds, 384 matched contexts, zero nominal-only wins.",
    )
    maximum = primary["pair_count"]
    for y, name, count, color in [
        (285, "Nominal PD", primary["nominal_success_count"], RED),
        (410, "robust_z", primary["robust_success_count"], GREEN),
    ]:
        put_text(image, name, 82, y + 32, scale=0.62, color=INK, thickness=2)
        cv2.rectangle(image, (315, y), (1165, y + 52), PANEL_ALT, -1)
        width = int(850 * count / maximum)
        cv2.rectangle(image, (315, y), (315 + width, y + 52), color, -1)
        put_text(image, f"{count} / {maximum}", 930, y + 37, scale=0.58, color=INK, thickness=2)
    panel(image, 80, 515, 330, 110, "added successes", f"+{primary['success_delta_count']}", GREEN)
    panel(image, 475, 515, 330, 110, "percentage points", f"+{primary['success_delta_percentage_points']:.1f}", BLUE)
    panel(image, 870, 515, 330, 110, "failure reduction", f"{100*primary['failure_reduction_fraction']:.2f}%", AMBER)
    return image


def draw_retention(values: dict[str, Any]) -> np.ndarray:
    retention = values["retention"]
    image = base_slide(
        "05 / retention heldout suite",
        "No trade-off hidden behind the hard-distribution gain",
        "A separate 192-pair heldout suite checks that nominal successes are retained.",
    )
    panel(image, 75, 250, 350, 180, "nominal success", f"{retention['nominal_success_count']} / 192", RED, "63.0% mission success.")
    panel(image, 465, 250, 350, 180, "robust_z success", f"{retention['robust_success_count']} / 192", GREEN, "100.0% mission success.")
    panel(image, 855, 250, 350, 180, "nominal-only wins", str(retention["nominal_only_success"]), BLUE, "Zero retained-success regressions.")
    deltas = retention["per_seed_success_delta"]
    put_text(image, "PER-SEED ADDED SUCCESSES", 75, 505, scale=0.45, color=MUTED, thickness=2)
    x = 75
    for seed in ("831900462", "200501215", "144856705"):
        cv2.rectangle(image, (x, 535), (x + 350, 610), PANEL_ALT, -1)
        put_text(image, f"seed {seed}", x + 18, 565, scale=0.40, color=MUTED)
        put_text(image, f"+{deltas[seed]}", x + 250, 586, scale=0.75, color=GREEN, thickness=2)
        x += 390
    return image


def draw_diagnostics(values: dict[str, Any]) -> np.ndarray:
    noop = values["noop"]
    kill = values["kill"]
    image = base_slide(
        "06 / intervention sanity checks",
        "No-op proves identity; kill proves sensitivity",
        "The pipeline must preserve an identical controller and react to a zero-action intervention.",
    )
    panel(image, 75, 255, 525, 255, "no-op diagnostic", "BIT-EXACT", GREEN, "Issued action, applied action, state, gate, and terminal traces match exactly across 8 pairs.")
    panel(image, 680, 255, 525, 255, "zero-action kill", "0 / 8 SUCCESS", RED, f"0 gates; maximum paired-active position divergence {kill['diagnostic']['maximum_position_divergence_m']:.6f} m.")
    put_text(image, "NO-OP", 75, 570, scale=0.44, color=MUTED)
    put_text(image, f"{noop['arms']['nominal']['mission_success_count']}/8 = {noop['arms']['nominal_duplicate']['mission_success_count']}/8", 190, 570, scale=0.55, color=GREEN, thickness=2)
    put_text(image, "KILL", 680, 570, scale=0.44, color=MUTED)
    put_text(image, f"{kill['diagnostic']['action_divergent_pair_steps']:,} divergent paired-active steps", 775, 570, scale=0.52, color=RED, thickness=2)
    put_text(image, "Both diagnostics report PASS in the frozen raw archive.", 75, 625, scale=0.48, color=INK)
    return image


def draw_gains(values: dict[str, Any]) -> np.ndarray:
    baseline = values["baseline"]
    candidate = values["candidate"]
    image = base_slide(
        "07 / isolated intervention",
        "Only vertical position and velocity gains change",
        "Initial state, gate geometry, environment parameters, and random streams remain paired.",
    )
    put_text(image, "PROJECT NOMINAL PD", 85, 250, scale=0.46, color=MUTED, thickness=2)
    put_text(image, "robust_z", 850, 250, scale=0.46, color=MUTED, thickness=2)
    rows = [
        ("kp_z", baseline["position_kp_z"], candidate["position_kp_z"]),
        ("kd_z", baseline["velocity_kd_z"], candidate["velocity_kd_z"]),
    ]
    y = 325
    for name, before, after in rows:
        cv2.rectangle(image, (80, y - 45), (1200, y + 50), PANEL, -1)
        put_text(image, name, 105, y + 10, scale=0.62, color=INK, thickness=2)
        put_text(image, f"{before:.1f}", 400, y + 10, scale=0.82, color=RED, thickness=2)
        put_text(image, "->", 625, y + 10, scale=0.72, color=BLUE, thickness=2)
        put_text(image, f"{after:.1f}", 900, y + 10, scale=0.82, color=GREEN, thickness=2)
        y += 135
    cv2.rectangle(image, (80, 555), (1200, 620), PANEL_ALT, -1)
    put_text(image, "UNCHANGED", 105, 595, scale=0.45, color=BLUE, thickness=2)
    put_text(image, "xy gains | attitude | rate loop | vehicle | gates | domain | RNG", 310, 595, scale=0.50, color=INK)
    return image


def draw_scaling(values: dict[str, Any]) -> np.ndarray:
    rows = values["scaling_rows"]
    scale = values["scaling"]
    image = base_slide(
        "08 / Radeon scaling",
        "One Radeon, larger batches, fixed workload",
        f"{scale['total_measured_transitions']:,} measured transitions across 32, 128, 256, and 512 environments.",
    )
    chart_x, chart_y, chart_w, chart_h = 95, 260, 1090, 285
    cv2.line(image, (chart_x, chart_y + chart_h), (chart_x + chart_w, chart_y + chart_h), LINE, 2)
    maximum = max(float(row["mean_transitions_per_s"]) for row in rows)
    for index, row in enumerate(rows):
        bar_w = 205
        gap = 55
        x = chart_x + 40 + index * (bar_w + gap)
        throughput = float(row["mean_transitions_per_s"])
        height = int(chart_h * throughput / maximum)
        y = chart_y + chart_h - height
        cv2.rectangle(image, (x, y), (x + bar_w, chart_y + chart_h), BLUE, -1)
        put_text(image, f"{throughput:,.1f}", x + 8, y - 10, scale=0.43, color=INK, thickness=2)
        put_text(image, f"{row['env_count']} envs", x + 52, chart_y + chart_h + 30, scale=0.37, color=INK)
    put_text(image, f"32 -> 512 environments: {rows[-1]['speedup_vs_32_envs']:.3f}x intra-device speedup", 95, 625, scale=0.54, color=GREEN, thickness=2)
    return image


def draw_reproduce(_values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "09 / reproduce",
        "One CPU-only command checks the submitted evidence",
        "No GPU, simulator, training, or network access is required for the judge smoke.",
    )
    cv2.rectangle(image, (65, 230), (1215, 610), (8, 11, 13), -1)
    lines = [
        ("$ cd submissions/track3-flightguard", GREEN),
        ("$ python3 scripts/judge_smoke.py", GREEN),
        ("FlightGuard judge smoke: PASS", INK),
        ("challenge arena | primary 194/384 -> 371/384 (+46.1 pp)", MUTED),
        ("retention 121/192 -> 192/192 | 0 regressions", MUTED),
        ("challenge self-tests | no-op bit-exact | kill 0/8 | 14/14 gates", MUTED),
        ("Radeon | 2,227,200 transitions | 16.027013647337444x", MUTED),
    ]
    y = 275
    for text, color in lines:
        put_text(image, text, 90, y, scale=0.47, color=color, thickness=2 if color in (GREEN, INK) else 1)
        y += 44
    return image


def draw_application(_values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "10 / application",
        "A reviewable controller-qualification product",
        "FlightGuard turns a controller change into matched evidence a robotics team can inspect.",
    )
    cards = [
        ("Before tuning", "Expose a visible mission failure on frozen contexts."),
        ("After tuning", "Measure gain and regression with the same paired contexts."),
        ("Before deployment", "Export reproducible evidence and explicit limits."),
    ]
    x = 70
    colors = [RED, GREEN, BLUE]
    for index, (title, note) in enumerate(cards):
        panel(image, x, 265, 350, 260, title, ("FIND" if index == 0 else "QUALIFY" if index == 1 else "REVIEW"), colors[index], note)
        x += 395
    put_text(image, "Target users: embodied-AI researchers and flight-control developers.", 70, 605, scale=0.50, color=INK, thickness=2)
    return image


def draw_boundary(_values: dict[str, Any]) -> np.ndarray:
    image = np.full((HEIGHT, WIDTH, 3), BG, dtype=np.uint8)
    put_text(image, "FLIGHTGUARD", 70, 92, scale=0.68, color=BLUE, thickness=2)
    put_text(image, "What this evidence supports", 70, 165, scale=1.00, color=INK, thickness=2)
    put_text(image, "A sampled controller comparison in Genesis on one AMD Radeon.", 72, 220, scale=0.58, color=GREEN, thickness=2)
    claims = [
        "SIMULATION ONLY",
        "SAMPLED CONTEXTS ONLY",
        "PROJECT NOMINAL PD BASELINE",
        "NO SOTA / SAFETY / SIM-TO-REAL / REAL-FLIGHT CLAIM",
    ]
    y = 315
    for claim in claims:
        cv2.circle(image, (93, y - 7), 7, AMBER, -1)
        put_text(image, claim, 120, y, scale=0.55, color=INK, thickness=2)
        y += 65
    put_text(image, "Source + frozen evidence + one-command check", 70, 625, scale=0.48, color=MUTED)
    return image


SEGMENTS: list[tuple[float, float, Callable[[dict[str, Any]], np.ndarray], str]] = [
    (7.0, 20.0, draw_title, "FlightGuard turns a visible Genesis failure into a reproducible controller decision on one AMD Radeon."),
    (20.0, 38.0, draw_workflow, "Freeze one hypothesis, pair every context, simulate on ROCm, enforce gates, and export frozen evidence."),
    (38.0, 58.0, draw_remote, "This submitted no-op run reports Genesis 1.2.3, PyTorch ROCm, one visible AMD Radeon, and bit-exact PASS."),
    (58.0, 88.0, draw_primary, "On 384 primary adversarial pairs, mission success rises from 194 to 371 with zero nominal-only wins."),
    (88.0, 108.0, draw_retention, "On 192 separate heldout pairs, robust_z retains every nominal success and reaches 192 of 192."),
    (108.0, 128.0, draw_diagnostics, "The no-op is bit-exact, while zero action yields zero successes and a 10.506417 meter divergence."),
    (128.0, 150.0, draw_gains, "Only kp_z and kd_z change; initial state, gates, domain parameters, and random streams stay paired."),
    (150.0, 175.0, draw_scaling, "A fixed one-Radeon workload scales from 32 to 512 environments over 2,227,200 measured transitions."),
    (175.0, 193.0, draw_reproduce, "A CPU-only judge command checks raw metrics, diagnostics, aggregates, media, and claim boundaries."),
    (193.0, 205.0, draw_application, "The result is a controller-qualification workflow for embodied-AI researchers and flight-control developers."),
    (205.0, 210.0, draw_boundary, "The claim is simulation-only and sampled: no SOTA, safety, sim-to-real, or real-flight conclusion."),
]


def build_slides(values: dict[str, Any]) -> list[np.ndarray]:
    slides = [builder(values) for _, _, builder, _ in SEGMENTS]
    require(len(slides) == 11, "slide count mismatch")
    for index, slide in enumerate(slides):
        require(slide.shape == (HEIGHT, WIDTH, 3), f"slide {index} shape mismatch")
        require(slide.dtype == np.uint8, f"slide {index} dtype mismatch")
    return slides


def validate_in_memory(values: dict[str, Any]) -> dict[str, Any]:
    slides = build_slides(values)
    representatives = []
    for index, (start, end, _builder, caption) in enumerate(SEGMENTS):
        elapsed = (start + end) / 2
        frame = add_caption(slides[index], caption, elapsed)
        require(frame.shape == (HEIGHT, WIDTH, 3), f"captioned frame {index} mismatch")
        representatives.append(sha256_bytes(frame.tobytes()))
    capture = open_verified_challenge_clip()
    decoded = 0
    first_sha = ""
    last_sha = ""
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        require(frame.shape == (HEIGHT, WIDTH, 3), "Challenge Arena decoded frame mismatch")
        digest = sha256_bytes(frame.tobytes())
        if decoded == 0:
            first_sha = digest
        last_sha = digest
        decoded += 1
    capture.release()
    require(decoded == 140, "Challenge Arena complete decode mismatch")
    return {
        "status": "PASS",
        "mode": "validate-only",
        "source_clip_frames_decoded": decoded,
        "source_clip_first_frame_sha256": first_sha,
        "source_clip_last_frame_sha256": last_sha,
        "representative_frame_sha256": representatives,
        "timeline_seconds": [[start, end] for start, end, _, _ in SEGMENTS],
        "output_contract": {
            "frame_count": FRAME_COUNT,
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "duration_seconds": DURATION_SECONDS,
            "audio": False,
        },
    }


def render(values: dict[str, Any], output: Path) -> dict[str, Any]:
    require(output.resolve() == DEFAULT_OUTPUT.resolve(), f"output path is fixed to {DEFAULT_OUTPUT}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_name(f".{output.name}.part.mp4")
    if part.exists():
        raise FileExistsError(f"refusing to overwrite {part}")

    slides = build_slides(values)
    challenge = open_verified_challenge_clip()
    writer = cv2.VideoWriter(
        str(part),
        cv2.VideoWriter_fourcc(*FOURCC),
        FPS,
        (WIDTH, HEIGHT),
    )
    if not writer.isOpened():
        challenge.release()
        raise RuntimeError("cv2 VideoWriter failed to open output")

    try:
        for frame_index in range(FRAME_COUNT):
            elapsed = frame_index / FPS
            if frame_index < 70:
                ok, source_frame = challenge.read()
                require(ok, f"Challenge Arena early EOF at source frame {frame_index * 2}")
                ok_skip, _skip = challenge.read()
                require(ok_skip, f"Challenge Arena early EOF at source frame {frame_index * 2 + 1}")
                frame = annotate_challenge(source_frame, elapsed)
            else:
                segment_index = next(
                    index
                    for index, (start, end, _builder, _caption) in enumerate(SEGMENTS)
                    if start <= elapsed < end
                )
                start, end, _builder, caption = SEGMENTS[segment_index]
                local = (elapsed - start) / (end - start)
                frame = add_caption(slides[segment_index], caption, elapsed)
                fade = min(1.0, local / 0.035, (1.0 - local) / 0.035)
                if fade < 1.0:
                    frame = cv2.addWeighted(
                        frame,
                        max(0.0, fade),
                        np.zeros_like(frame),
                        1.0 - max(0.0, fade),
                        0.0,
                    )
            writer.write(frame)
        extra_ok, _extra = challenge.read()
        require(not extra_ok, "Challenge Arena has frames beyond source frame 139")
    finally:
        writer.release()
        challenge.release()

    capture = cv2.VideoCapture(str(part))
    require(capture.isOpened(), "rendered video cannot be opened")
    actual_frames = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    actual_width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    actual_height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    actual_fps = float(capture.get(cv2.CAP_PROP_FPS))
    fourcc_value = int(round(capture.get(cv2.CAP_PROP_FOURCC)))
    codec_reported = "".join(chr((fourcc_value >> (8 * index)) & 0xFF) for index in range(4))
    capture.release()
    require(actual_frames == FRAME_COUNT, "rendered frame-count mismatch")
    require(actual_width == WIDTH and actual_height == HEIGHT, "rendered dimensions mismatch")
    require(abs(actual_fps - FPS) < 0.01, "rendered fps mismatch")

    os.replace(part, output)
    raw = output.read_bytes()
    return {
        "status": "PASS",
        "path": str(output.resolve()),
        "sha256": sha256_bytes(raw),
        "size_bytes": len(raw),
        "frame_count": actual_frames,
        "width": actual_width,
        "height": actual_height,
        "fps": actual_fps,
        "duration_seconds": actual_frames / actual_fps,
        "codec_requested": FOURCC,
        "codec_reported": codec_reported,
        "audio": False,
        "captioned": True,
        "challenge_clip": {
            "sha256": EXPECTED["challenge_clip"][0],
            "source_frames_consumed": 140,
            "source_fps": 20.0,
            "output_frames": 70,
            "output_seconds": 7.0,
        },
        "challenge_summary_sha256": EXPECTED["challenge_summary"][0],
        "scaling_sha256": EXPECTED["scaling"][0],
        "timeline_seconds": [[0.0, 7.0]] + [[start, end] for start, end, _, _ in SEGMENTS],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    values = evidence_values()
    report = validate_in_memory(values) if args.validate_only else render(values, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
