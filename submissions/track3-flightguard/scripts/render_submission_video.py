#!/usr/bin/env python3
"""Render the positive-first FlightGuard reviewer video from frozen evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

WIDTH = 1280
HEIGHT = 720
DEFAULT_FPS = 10.0
DEFAULT_DURATION = 210.0
FOURCC = "mp4v"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENESIS_CLIP_PATH = PROJECT_ROOT / "submission/genesis-nominal-visual-replay.mp4"
GENESIS_CLIP_SHA256 = "adc0ea528b611e55dca006d220c30ef935f32448f6b935b7b6c1a33cd9d9fbce"
GENESIS_CLIP_FRAME_COUNT = 500
GENESIS_CLIP_START_FRAME = 300
GENESIS_CLIP_END_FRAME = GENESIS_CLIP_START_FRAME + GENESIS_CLIP_FRAME_COUNT
GENESIS_CLIP_FPS = 10.0
DEFAULT_OUTPUT = PROJECT_ROOT / "submission/flightguard-nominal-envelope-demo-v2.mp4"
FONT = cv2.FONT_HERSHEY_SIMPLEX

EXPECTED_SHA256 = {
    "envelope": "c7ca6e460e967c3070736d8120bd918a3c489f1e7d62a3ae933ab631af827f58",
    "v4": "4ebab98a9b9c3b134548ef646c30aaafbd7d6ddeaa8a0485b667ee8054f80f8b",
    "v5": "d546a620931fc3afb2c074d749e1fe017ba6c4dcdf2d05b570855a913e83b034",
    "v6": "905925dedc62a41a8b4c35ace8b1c5a1bd1d97c9cb4d43a5f513f3827cf0a678",
    "scaling": "98d9b331907f9968ae65054c6f9d840dc0440eb9209c14e955dc628df736f072",
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_verified(role: str, path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    expected = EXPECTED_SHA256[role]
    require(digest == expected, f"{role} SHA-256 mismatch: expected {expected}, got {digest}")
    value = json.loads(raw)
    require(isinstance(value, dict), f"{role} JSON root must be an object")
    return value


def open_verified_genesis_clip() -> cv2.VideoCapture:
    raw = GENESIS_CLIP_PATH.read_bytes()
    require(
        sha256_bytes(raw) == GENESIS_CLIP_SHA256,
        "fixed-seed 5001 Genesis clip SHA-256 mismatch",
    )
    capture = cv2.VideoCapture(str(GENESIS_CLIP_PATH))
    if not capture.isOpened():
        raise RuntimeError(f"Genesis clip cannot be opened: {GENESIS_CLIP_PATH}")
    try:
        frame_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        require(frame_count == GENESIS_CLIP_FRAME_COUNT, "Genesis clip frame count mismatch")
        require(width == WIDTH and height == HEIGHT, "Genesis clip dimensions mismatch")
        require(abs(fps - GENESIS_CLIP_FPS) < 0.01, "Genesis clip fps mismatch")
    except Exception:
        capture.release()
        raise
    return capture


def evidence_values(
    envelope: dict[str, Any],
    v4: dict[str, Any],
    v5: dict[str, Any],
    v6: dict[str, Any],
    scaling: dict[str, Any],
) -> dict[str, Any]:
    require(envelope["simulation_only"] is True, "envelope scope drift")
    mission = envelope["heldout_three_gate_mission"]["aggregate"]
    require(mission["paired_course_contexts"] == 384, "paired context count drift")
    require(mission["method_episodes"] == 1152, "method episode count drift")
    require(mission["all_fields_finite"] is True, "mission finiteness drift")
    require(mission["all_runs_one_visible_radeon"] is True, "mission GPU count drift")
    methods: dict[str, dict[str, int]] = {}
    for name in ("constant_velocity", "hold_last", "learned"):
        source = mission["per_method"][name]
        require(source["mission_success_count"] == 384, f"{name} success drift")
        require(source["gate_passes_total"] == 1152, f"{name} gate drift")
        for key in ("mission_failure_count", "strike_count", "terminal_failure_count", "unfinished_count"):
            require(source[key] == 0, f"{name} {key} drift")
        methods[name] = {
            "success": int(source["mission_success_count"]),
            "gates": int(source["gate_passes_total"]),
        }

    collector = envelope["training_distribution_collector"]["aggregate"]
    require(collector["environments"] == 192, "collector environment drift")
    require(collector["survivors"] == 186, "collector survivor drift")
    require(collector["all_fields_finite"] is True, "collector finiteness drift")
    require(
        collector["max_applied_action_per_env_saturation_fraction"] == 0.0,
        "collector saturation drift",
    )

    boundary = envelope["claim_boundary"]
    for key in (
        "continuous_envelope_guarantee_claim",
        "dropout_recovery_claim",
        "learned_superiority_claim",
        "real_flight_claim",
        "safety_or_certification_claim",
        "sim_to_real_claim",
    ):
        require(boundary[key] is False, f"claim boundary drift: {key}")

    require(v4["status"] == "FAIL", "v4 status drift")
    require(v5["award_evidence_eligible"] is False, "v5 eligibility drift")
    require(v6["status"] == "FAIL" and v6["admitted_lane_count"] == 0, "v6 status drift")

    scale = scaling["scaling"]
    require(scale["status"] == "PASS", "scaling status drift")
    require(scale["total_measured_transitions"] == 2_227_200, "scaling transition drift")
    rows = scale["env_summaries"]
    require([row["env_count"] for row in rows] == [32, 128, 256, 512], "scaling env drift")
    require(rows[-1]["speedup_vs_32_envs"] == 16.027013647337444, "scaling speedup drift")

    return {
        "methods": methods,
        "paired_contexts": int(mission["paired_course_contexts"]),
        "method_episodes": int(mission["method_episodes"]),
        "mass_min": float(mission["mass_scale_min"]),
        "mass_max": float(mission["mass_scale_max"]),
        "thrust_min": float(mission["thrust_scale_min"]),
        "thrust_max": float(mission["thrust_scale_max"]),
        "wind_max": float(mission["wind_acceleration_norm_max_mps2"]),
        "delay_min": int(mission["action_delay_steps_min"]),
        "delay_max": int(mission["action_delay_steps_max"]),
        "dropout_delta": list(mission["dropout_minus_mean_terminal_step_by_seed"]),
        "collector_survivors": int(collector["survivors"]),
        "collector_envs": int(collector["environments"]),
        "collector_saturation": float(
            collector["max_applied_action_per_env_saturation_fraction"]
        ),
        "scaling_rows": [
            {
                "env_count": int(row["env_count"]),
                "throughput": float(row["mean_transitions_per_s"]),
                "gpu_mean": float(row["measured_gpu_monitor"]["gpu_use_percent_mean"]),
            }
            for row in rows
        ],
        "total_transitions": int(scale["total_measured_transitions"]),
        "speedup": float(rows[-1]["speedup_vs_32_envs"]),
        "efficiency": float(rows[-1]["parallel_efficiency_vs_32_envs"]),
        "max_vram": max(int(row["measured_gpu_monitor"]["vram_used_bytes_max"]) for row in rows),
        "v4_counts": [
            int(v4["metrics"][arm]["fault"]["mission_success_count"])
            for arm in ("CausalIMUPatch", "ActionOnly", "RawStrapdown", "CalibratedStrapdown")
        ],
        "v5_patch": int(v5["metrics"]["CausalIMUPatch"]["fault"]["mission_success_count"]),
        "v5_cal": int(v5["metrics"]["CalibratedStrapdown"]["fault"]["mission_success_count"]),
        "v6_admitted": int(v6["admitted_lane_count"]),
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
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        width = cv2.getTextSize(candidate, FONT, scale, thickness)[0][0]
        if current and width > max_width:
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
    put_text(image, section.upper(), 70, 68, scale=0.48, color=BLUE, thickness=2)
    put_text(image, title, 70, 132, scale=1.04, color=INK, thickness=2)
    put_wrapped(image, subtitle, 72, 177, 1120, scale=0.48, color=MUTED, line_height=24)
    cv2.line(image, (70, 208), (1210, 208), LINE, 2)
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
    put_text(image, title.upper(), x + 24, y + 34, scale=0.42, color=MUTED, thickness=1)
    put_text(image, value, x + 24, y + 84, scale=0.86, color=color, thickness=2)
    if note:
        put_wrapped(image, note, x + 24, y + 118, w - 44, scale=0.38, color=INK, line_height=20)


def draw_title(values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "01 / application",
        "FlightGuard",
        "Radeon-Native Sampled Nominal Flight Envelope Verifier | AMD Track 3",
    )
    put_text(image, "SIMULATION-ONLY", 72, 280, scale=0.74, color=AMBER, thickness=2)
    put_text(image, "One-Radeon Genesis mission qualification with frozen evidence.", 72, 325, scale=0.58, color=INK, thickness=1)
    panel(image, 72, 380, 350, 175, "paired course contexts", f"{values['paired_contexts']}", GREEN, "Heldout samples across seeds 303, 304, and 305.")
    panel(image, 465, 380, 350, 175, "method episodes", f"{values['method_episodes']:,}", BLUE, "Three registered replicas; each completes 384/384.")
    panel(image, 858, 380, 350, 175, "Radeon speedup", f"{values['speedup']:.3f}x", AMBER, "Fixed workload, 32 to 512 environments.")
    put_text(image, "Sampled contexts; no continuous-envelope, safety, or real-flight claim.", 72, 625, scale=0.52, color=MUTED)
    return image


def draw_workflow(_values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "02 / workflow",
        "Sample -> simulate -> qualify -> freeze",
        "The simulator and scaling campaigns are independent one-Radeon runs; all numeric claims come from frozen JSON.",
    )
    labels = [
        ("Domain samples", "mass / thrust / wind / delay"),
        ("Genesis + robust_z", "three-gate mission"),
        ("One Radeon / ROCm", "batched simulation"),
        ("Evidence checks", "mission / finite / collector saturation"),
        ("Frozen artifacts", "raw metrics + aggregate"),
    ]
    x = 70
    for index, (title, note) in enumerate(labels):
        w = 205
        cv2.rectangle(image, (x, 290), (x + w, 470), PANEL if index % 2 == 0 else PANEL_ALT, -1)
        put_text(image, f"{index + 1:02d}", x + 16, 326, scale=0.55, color=BLUE, thickness=2)
        put_wrapped(image, title, x + 16, 375, w - 30, scale=0.48, color=INK, thickness=2, line_height=24)
        put_wrapped(image, note, x + 16, 430, w - 30, scale=0.36, color=MUTED, line_height=19)
        if index < len(labels) - 1:
            put_text(image, ">", x + w + 10, 388, scale=0.8, color=BLUE, thickness=2)
        x += 235
    put_text(image, "The upcoming clip is a separate fixed-seed 5001 truth-controller nominal visual.", 72, 565, scale=0.55, color=AMBER, thickness=2)
    put_text(image, "It is metric-ineligible and is not one of the 384 heldout evidence contexts.", 72, 605, scale=0.50, color=MUTED)
    return image


def draw_mission(values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "03 / heldout mission evidence",
        "384 paired contexts; every replica completes 384/384",
        "Aggregate metrics are recomputed from six submitted raw source JSON files.",
    )
    names = [("constant_velocity", GREEN), ("hold_last", BLUE), ("learned", AMBER)]
    for index, (name, color) in enumerate(names):
        y = 250 + index * 115
        cv2.rectangle(image, (85, y), (1195, y + 88), PANEL, -1)
        put_text(image, name, 112, y + 36, scale=0.58, color=INK, thickness=2)
        put_text(image, "384 / 384 missions", 470, y + 36, scale=0.62, color=color, thickness=2)
        put_text(image, "1,152 gate passes", 815, y + 36, scale=0.58, color=color, thickness=2)
        put_text(image, "0 strike | 0 mission failure | 0 terminal failure | 0 unfinished", 470, y + 68, scale=0.38, color=MUTED)
    put_text(image, "THREE REPLICAS TIE EXACTLY - NO LEARNED-SUPERIORITY CLAIM", 86, 630, scale=0.53, color=AMBER, thickness=2)
    return image


def draw_ranges(values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "04 / sampled conditions",
        "Observed heldout ranges",
        "These values describe sampled contexts; they are not a continuous hyper-rectangle guarantee.",
    )
    panel(image, 80, 260, 520, 150, "mass scale", f"{values['mass_min']:.5f} - {values['mass_max']:.5f}", GREEN)
    panel(image, 680, 260, 520, 150, "thrust scale", f"{values['thrust_min']:.5f} - {values['thrust_max']:.5f}", BLUE)
    panel(image, 80, 450, 520, 150, "wind acceleration norm", f"0 - {values['wind_max']:.5f} m/s^2", AMBER)
    panel(image, 680, 450, 520, 150, "action delay", f"{values['delay_min']} - {values['delay_max']} steps", RED)
    put_text(image, "SAMPLED NOMINAL EVIDENCE - NOT A FORMAL OR CERTIFIED ENVELOPE", 80, 650, scale=0.50, color=MUTED, thickness=2)
    return image


def draw_collector(values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "05 / training-distribution collector",
        "186 / 192 survivor environments",
        "Collector metrics are separate from the heldout mission metrics.",
    )
    panel(image, 80, 275, 340, 190, "survivors", f"{values['collector_survivors']} / {values['collector_envs']}", GREEN, "63/64 + 62/64 + 61/64 across seeds 303-305.")
    panel(image, 470, 275, 340, 190, "tracked fields", "ALL FINITE", BLUE, "Position, velocity, quaternion, angular velocity, issued action, and applied action.")
    panel(image, 860, 275, 340, 190, "applied saturation", f"MAX {values['collector_saturation']:.1f}", AMBER, "Maximum per-environment fraction in collector metrics.")
    put_text(image, "Heldout mission metrics do not contain a saturation field.", 82, 545, scale=0.58, color=RED, thickness=2)
    put_text(image, "No mission-saturation claim is made.", 82, 585, scale=0.52, color=MUTED)
    return image


def draw_scaling(values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "06 / Radeon scaling",
        "Fixed workload on one Radeon",
        f"{values['total_transitions']:,} measured transitions | 32 to 512 environments",
    )
    rows = values["scaling_rows"]
    chart_x, chart_y, chart_w, chart_h = 100, 280, 1080, 285
    cv2.line(image, (chart_x, chart_y + chart_h), (chart_x + chart_w, chart_y + chart_h), LINE, 2)
    maximum = max(row["throughput"] for row in rows)
    gap = 50
    bar_w = 205
    for index, row in enumerate(rows):
        x = chart_x + gap + index * (bar_w + gap)
        h = int(chart_h * row["throughput"] / maximum)
        y = chart_y + chart_h - h
        cv2.rectangle(image, (x, y), (x + bar_w, chart_y + chart_h), BLUE, -1)
        put_text(image, f"{row['throughput']:,.1f}", x + 8, y - 12, scale=0.45, color=INK, thickness=2)
        label = f"{row['env_count']} envs"
        label_width = cv2.getTextSize(label, FONT, 0.38, 1)[0][0]
        put_text(
            image,
            label,
            x + (bar_w - label_width) // 2,
            chart_y + chart_h + 30,
            scale=0.38,
            color=INK,
            thickness=1,
        )
    put_text(
        image,
        f"Speedup {values['speedup']:.3f}x | efficiency {values['efficiency']:.5f}",
        102,
        635,
        scale=0.52,
        color=GREEN,
        thickness=2,
    )
    put_text(image, f"Maximum observed VRAM {values['max_vram']:,} bytes", 830, 635, scale=0.42, color=MUTED)
    return image


def draw_limitations(values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "07 / retained research lineage",
        "Attractive mechanisms that did not earn a claim",
        "Negative branches remain visible as limitations; they are not the FlightGuard application headline.",
    )
    panel(image, 80, 275, 340, 205, "v4 scientific fail", "11 / 36", RED, f"Patch vs ActionOnly/Raw/Cal = {values['v4_counts']}. Missed the preregistered gate.")
    panel(image, 470, 275, 340, 205, "v5 award-ineligible", "10 = 10", AMBER, f"Patch {values['v5_patch']}/12 equals Cal {values['v5_cal']}/12; incremental capability 0.")
    panel(image, 860, 275, 340, 205, "v6 rejected", f"{values['v6_admitted']} / 12", RED, "No lanes admitted; exact-Cal fallback.")
    put_text(image, "Honest stop decisions support reproducibility; they do not establish estimator superiority.", 80, 560, scale=0.53, color=MUTED)
    return image


def draw_boundary(_values: dict[str, Any]) -> np.ndarray:
    image = base_slide(
        "08 / reproduce and boundaries",
        "One command verifies the frozen evidence",
        "cd submissions/track3-flightguard && python3 scripts/judge_smoke.py",
    )
    claims = [
        "Simulation-only; no physical-flight validation.",
        "Sampled contexts; no continuous or certified envelope.",
        "Three method replicas tie; no learned superiority.",
        "Dropout begins >532 steps after each seed mean terminal, but no dropout-recovery claim.",
        "No safety, sim-to-real, certification, or real-flight repair claim.",
    ]
    y = 285
    for claim in claims:
        cv2.circle(image, (110, y - 7), 6, BLUE, -1)
        put_text(image, claim, 135, y, scale=0.50, color=INK, thickness=1)
        y += 58
    put_text(image, "submission/evidence/raw-metrics/ + verified-flight-envelope-aggregate.json", 82, 615, scale=0.43, color=GREEN, thickness=2)
    return image


def add_caption(
    image: np.ndarray,
    caption: str,
    elapsed: float,
    duration: float,
    local_fraction: float,
) -> np.ndarray:
    frame = image.copy()
    cv2.rectangle(frame, (0, 664), (WIDTH, HEIGHT), (14, 12, 10), -1)
    put_wrapped(frame, caption, 48, 690, 1080, scale=0.43, color=INK, line_height=21)
    put_text(frame, f"{elapsed:06.1f}s / {duration:06.1f}s", 1095, 700, scale=0.36, color=MUTED)
    cv2.rectangle(frame, (0, 714), (WIDTH, 719), PANEL_ALT, -1)
    cv2.rectangle(frame, (0, 714), (int(WIDTH * elapsed / duration), 719), BLUE, -1)
    return frame


def annotate_genesis_clip(frame: np.ndarray, elapsed: float, duration: float) -> np.ndarray:
    result = frame.copy()
    cv2.rectangle(result, (0, 0), (WIDTH, 72), (10, 10, 10), -1)
    put_text(result, "FIXED-SEED 5001 TRUTH-CONTROLLER NOMINAL VISUAL", 34, 30, scale=0.56, color=AMBER, thickness=2)
    put_text(result, "SIMULATION ONLY | METRIC-INELIGIBLE | INDEPENDENT OF 384-CONTEXT AGGREGATE", 34, 58, scale=0.40, color=INK, thickness=1)
    cv2.rectangle(result, (0, 714), (WIDTH, 719), PANEL_ALT, -1)
    cv2.rectangle(result, (0, 714), (int(WIDTH * elapsed / duration), 719), BLUE, -1)
    return result


def render_video(values: dict[str, Any], output: Path, fps: float, duration: float) -> dict[str, Any]:
    require(duration == 210.0, "reviewer video requires exactly 210 seconds")
    require(fps == 10.0, "reviewer video requires exactly 10 fps")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_name(f".{output.name}.part.mp4")
    if part.exists():
        raise FileExistsError(f"refusing to overwrite {part}")

    frame_count = int(round(duration * fps))
    require(frame_count == 2100, "reviewer video requires exactly 2100 frames")
    segments: list[tuple[float, float, Callable[[dict[str, Any]], np.ndarray], str]] = [
        (0.0, 20.0, draw_title, "FlightGuard qualifies a simulated quadrotor across sampled conditions on Radeon."),
        (20.0, 30.0, draw_workflow, "Deterministic contexts feed Genesis, mission checks, and frozen evidence."),
        (30.0, 80.0, draw_workflow, "Fixed-seed 5001 nominal truth-controller visual; metric-ineligible and separate from aggregate evidence."),
        (80.0, 115.0, draw_mission, "Across 384 paired contexts, every method replica completes 384 of 384 missions."),
        (115.0, 133.0, draw_ranges, "Observed ranges describe samples, not a continuous or certified envelope."),
        (133.0, 150.0, draw_collector, "The collector retains 186 of 192 environments with finite tracked fields and zero applied saturation."),
        (150.0, 180.0, draw_scaling, "A fixed workload scales from 32 to 512 environments on one Radeon."),
        (180.0, 198.0, draw_limitations, "V4, v5, and v6 remain visible as failed or ineligible research branches."),
        (198.0, 210.0, draw_boundary, "The deliverable is sampled nominal simulation evidence, not safety or real-flight certification."),
    ]
    require(segments[-1][1] == duration, "segment duration mismatch")
    slides = [builder(values) for _, _, builder, _ in segments]
    genesis_capture = open_verified_genesis_clip()
    writer = cv2.VideoWriter(
        str(part),
        cv2.VideoWriter_fourcc(*FOURCC),
        fps,
        (WIDTH, HEIGHT),
    )
    if not writer.isOpened():
        genesis_capture.release()
        raise RuntimeError("cv2 VideoWriter failed to open mp4v output")

    try:
        for frame_index in range(frame_count):
            elapsed = frame_index / fps
            if GENESIS_CLIP_START_FRAME <= frame_index < GENESIS_CLIP_END_FRAME:
                clip_index = frame_index - GENESIS_CLIP_START_FRAME
                ok, frame = genesis_capture.read()
                if not ok:
                    raise RuntimeError(f"Genesis clip early EOF at frame {clip_index}")
                require(
                    frame.shape == (HEIGHT, WIDTH, 3) and frame.dtype == np.uint8,
                    f"Genesis clip frame {clip_index} shape or dtype mismatch",
                )
                frame = annotate_genesis_clip(frame, elapsed, duration)
            else:
                segment_index = next(
                    index
                    for index, (start, end, _builder, _caption) in enumerate(segments)
                    if start <= elapsed < end
                )
                start, end, _builder, caption = segments[segment_index]
                local = (elapsed - start) / max(end - start, 1e-9)
                frame = add_caption(slides[segment_index], caption, elapsed, duration, local)
                fade = min(1.0, local / 0.04, (1.0 - local) / 0.04)
                if fade < 1.0:
                    frame = cv2.addWeighted(
                        frame,
                        max(0.0, fade),
                        np.zeros_like(frame),
                        1.0 - max(0.0, fade),
                        0.0,
                    )
            writer.write(frame)
        extra_ok, _extra = genesis_capture.read()
        require(not extra_ok, "Genesis clip has frames beyond frame 499")
    finally:
        writer.release()
        genesis_capture.release()

    capture = cv2.VideoCapture(str(part))
    if not capture.isOpened():
        raise RuntimeError("rendered video cannot be opened")
    actual_fps = float(capture.get(cv2.CAP_PROP_FPS))
    actual_frames = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    actual_width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    actual_height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    fourcc_value = int(round(capture.get(cv2.CAP_PROP_FOURCC)))
    reported_fourcc = "".join(
        chr((fourcc_value >> (8 * index)) & 0xFF) for index in range(4)
    )
    capture.release()
    require(actual_width == WIDTH and actual_height == HEIGHT, "rendered dimensions mismatch")
    require(abs(actual_fps - fps) < 0.01, "rendered fps mismatch")
    require(actual_frames == frame_count, "rendered frame count mismatch")

    os.replace(part, output)
    raw = output.read_bytes()
    return {
        "path": str(output.resolve()),
        "codec_requested": FOURCC,
        "codec_reported": reported_fourcc,
        "width": actual_width,
        "height": actual_height,
        "fps": actual_fps,
        "frame_count": actual_frames,
        "duration_seconds": actual_frames / actual_fps,
        "size_bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "audio": False,
        "captioned": True,
        "genesis_clip": {
            "seed": 5001,
            "controller": "truth-controller",
            "scope": "nominal visual only",
            "metric_eligible": False,
            "sha256": GENESIS_CLIP_SHA256,
        },
        "aggregate_sha256": EXPECTED_SHA256["envelope"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope", required=True, type=Path)
    parser.add_argument("--v4", required=True, type=Path)
    parser.add_argument("--v5", required=True, type=Path)
    parser.add_argument("--v6", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    args = parser.parse_args()
    if args.output.resolve() != DEFAULT_OUTPUT.resolve():
        raise ValueError(f"--output is fixed to {DEFAULT_OUTPUT}")

    values = evidence_values(
        load_verified("envelope", args.envelope),
        load_verified("v4", args.v4),
        load_verified("v5", args.v5),
        load_verified("v6", args.v6),
        load_verified("scaling", args.scaling),
    )
    report = render_video(values, args.output, args.fps, args.duration)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
