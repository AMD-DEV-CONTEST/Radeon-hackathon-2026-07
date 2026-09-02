#!/usr/bin/env python3
"""Build deterministic submission figures from frozen FlightGuard evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
from pathlib import Path
from typing import Any

EXPECTED_SHA256 = {
    "v4": "4ebab98a9b9c3b134548ef646c30aaafbd7d6ddeaa8a0485b667ee8054f80f8b",
    "v5": "d546a620931fc3afb2c074d749e1fe017ba6c4dcdf2d05b570855a913e83b034",
    "v6": "905925dedc62a41a8b4c35ace8b1c5a1bd1d97c9cb4d43a5f513f3827cf0a678",
    "scaling": "98d9b331907f9968ae65054c6f9d840dc0440eb9209c14e955dc628df736f072",
}

OUTPUT_NAMES = (
    "gate-matrix.svg",
    "v4-v5-fault-success.svg",
    "v6-lane-qualification.svg",
    "radeon-scaling.svg",
    "summary.csv",
    "summary.json",
)

COLORS = {
    "ink": "#eef3f7",
    "muted": "#9eabb5",
    "panel": "#18212a",
    "panel_alt": "#202b35",
    "line": "#36434e",
    "green": "#58d68d",
    "red": "#ff6b6b",
    "amber": "#f6bd60",
    "blue": "#59a5f5",
    "purple": "#b794f6",
    "bg": "#0f151b",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_verified(role: str, path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    expected = EXPECTED_SHA256[role]
    if digest != expected:
        raise ValueError(f"{role} SHA-256 mismatch: expected {expected}, got {digest}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError(f"{role} root must be an object")
    return value, digest


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def svg_open(width: int, height: int, title: str, description: str) -> list[str]:
    return [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
        ),
        f"  <title id=\"title\">{esc(title)}</title>",
        f"  <desc id=\"desc\">{esc(description)}</desc>",
        f'  <rect width="{width}" height="{height}" fill="{COLORS["bg"]}"/>',
        "  <style>",
        "    text { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }",
        "  </style>",
    ]


def svg_text(
    x: float,
    y: float,
    value: object,
    *,
    size: int = 16,
    weight: int = 400,
    fill: str | None = None,
    anchor: str = "start",
) -> str:
    color = fill or COLORS["ink"]
    return (
        f'  <text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}" text-anchor="{anchor}">{esc(value)}</text>'
    )


def svg_rect(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str,
    rx: int = 8,
    stroke: str | None = None,
) -> str:
    stroke_attr = f' stroke="{stroke}"' if stroke else ""
    return (
        f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" '
        f'fill="{fill}"{stroke_attr}/>'
    )


def write_new(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def extract(
    v4: dict[str, Any],
    v5: dict[str, Any],
    v6: dict[str, Any],
    scaling: dict[str, Any],
) -> dict[str, Any]:
    require(v4.get("status") == "FAIL", "v4 status must be FAIL")
    require(v4.get("repair_claim_eligible") is False, "v4 claim flag drift")
    v4_arms = ("CausalIMUPatch", "ActionOnly", "RawStrapdown", "CalibratedStrapdown")
    v4_success: dict[str, dict[str, int]] = {}
    for arm in v4_arms:
        metric = v4["metrics"][arm]["fault"]
        v4_success[arm] = {
            "successes": int(metric["mission_success_count"]),
            "episodes": int(metric["episode_count"]),
        }
    require(
        [(v4_success[a]["successes"], v4_success[a]["episodes"]) for a in v4_arms]
        == [(11, 36), (0, 36), (33, 36), (32, 36)],
        "v4 fault counts drift",
    )
    v4_reduction = float(v4["capability_effect"]["patch_vs_action_only_failure_reduction_fraction"])
    require(abs(v4_reduction - 11 / 36) < 1e-15, "v4 failure reduction drift")

    require(v5.get("status") == "PASS", "v5 development status must be PASS")
    require(v5.get("award_evidence_eligible") is False, "v5 award flag drift")
    require(v5.get("formal_claim_eligible") is False, "v5 formal flag drift")
    require(v5.get("formal_extension_permitted") is False, "v5 extension flag drift")
    v5_arms = ("CausalIMUPatch", "ActionOnly", "CalibratedStrapdown")
    v5_success: dict[str, dict[str, int]] = {}
    v5_nominal: dict[str, dict[str, int]] = {}
    for arm in v5_arms:
        fault = v5["metrics"][arm]["fault"]
        nominal = v5["metrics"][arm]["nominal"]
        v5_success[arm] = {
            "successes": int(fault["mission_success_count"]),
            "episodes": int(fault["episode_count"]),
        }
        v5_nominal[arm] = {
            "successes": int(nominal["mission_success_count"]),
            "episodes": int(nominal["episode_count"]),
        }
    require(
        [(v5_success[a]["successes"], v5_success[a]["episodes"]) for a in v5_arms]
        == [(10, 12), (0, 12), (10, 12)],
        "v5 fault counts drift",
    )
    require(v5_nominal["CausalIMUPatch"] == {"successes": 12, "episodes": 12}, "v5 Patch nominal drift")
    require(v5_nominal["CalibratedStrapdown"] == {"successes": 12, "episodes": 12}, "v5 Cal nominal drift")
    traces = v5["integrity"]["fault_paired_patch_calibrated_trace"]
    require(set(traces) == {"30", "31", "32"}, "v5 checkpoint trace set drift")
    field_counts = []
    for checkpoint in ("30", "31", "32"):
        trace = traces[checkpoint]
        require(trace["all_operational_legacy_fields_raw_bit_exact"] is True, f"v5 cp{checkpoint} trace mismatch")
        require(all(trace["fields"].values()), f"v5 cp{checkpoint} field mismatch")
        field_counts.append(len(trace["fields"]))
    require(field_counts == [19, 19, 19], "v5 operational field count drift")

    require(v6.get("status") == "FAIL", "v6 cp30 status must be FAIL")
    require(v6.get("checkpoint_seed") == 30, "v6 evidence must be checkpoint 30")
    require(v6.get("lane_count") == 12, "v6 lane count drift")
    require(v6.get("admitted_lane_count") == 0, "v6 admitted count drift")
    require(v6.get("award_evidence_eligible") is False, "v6 award flag drift")
    recurrence = v6["raw_to_delivered_sensor_recurrence"]
    recurrence_checks = {
        "force_recurrence": bool(recurrence["replayed_delivered_force_raw_bit_exact"]),
        "gyro_recurrence": bool(recurrence["replayed_delivered_gyro_raw_bit_exact"]),
        "force_no_op": bool(recurrence["disabled_no_op_force_raw_bit_exact"]),
        "gyro_no_op": bool(recurrence["disabled_no_op_gyro_raw_bit_exact"]),
        "force_kill": bool(recurrence["enabled_kill_gate_changes_force"]),
        "gyro_kill": bool(recurrence["enabled_kill_gate_changes_gyro"]),
    }
    require(all(recurrence_checks.values()), "v6 recurrence/no-op/kill drift")

    lane_rows = []
    for expected_index, lane in enumerate(v6["lanes"]):
        require(lane["lane_index"] == expected_index, "v6 lane order drift")
        certificate = lane["full_fit_certificate"]
        holdout = lane["holdout_qualification"]
        delta = holdout["delta_velocity_error_mps"]
        rotation = holdout["rotation_geodesic_error_rad"]
        fallback = lane["fallback_integrity_checks"]
        require(lane["deployment_mode"] == "exact_cal_fallback", "v6 deployment mode drift")
        require(all(fallback.values()), "v6 fallback integrity drift")
        lane_rows.append(
            {
                "lane": expected_index,
                "admitted": bool(lane["admitted"]),
                "exact_cal_fallback": lane["deployment_mode"] == "exact_cal_fallback",
                "rank8": int(certificate["numerical_rank"]) == 8,
                "sigma": float(certificate["normalized_sigma_ratio"]),
                "sigma_pass": float(certificate["normalized_sigma_ratio"]) >= 1e-3,
                "split_half": bool(lane["split_half_stability"]["passed"]),
                "delta_v_rmse": bool(delta["rmse_passed_by_core"]),
                "rotation_rmse": bool(rotation["rmse_passed_by_core"]),
                "delta_v_q95": bool(delta["q95_passed_by_core"]),
                "rotation_q95": bool(rotation["q95_passed_by_core"]),
            }
        )
    counts = {
        key: sum(bool(row[key]) for row in lane_rows)
        for key in (
            "admitted",
            "exact_cal_fallback",
            "rank8",
            "sigma_pass",
            "split_half",
            "delta_v_rmse",
            "rotation_rmse",
            "delta_v_q95",
            "rotation_q95",
        )
    }
    require(
        counts
        == {
            "admitted": 0,
            "exact_cal_fallback": 12,
            "rank8": 12,
            "sigma_pass": 12,
            "split_half": 0,
            "delta_v_rmse": 0,
            "rotation_rmse": 0,
            "delta_v_q95": 3,
            "rotation_q95": 3,
        },
        "v6 gate counts drift",
    )
    sigma_values = [row["sigma"] for row in lane_rows]
    sigma_range = [min(sigma_values), max(sigma_values)]
    require(sigma_range == [0.019169591096042157, 0.0321526465925691], "v6 sigma range drift")

    require(scaling.get("status") == "PASS", "scaling status must be PASS")
    require(scaling.get("simulation_only") is True, "scaling simulation-only flag drift")
    scaling_payload = scaling["scaling"]
    require(scaling_payload.get("status") == "PASS", "scaling payload status drift")
    require(
        scaling_payload["performance_acceptance"]["achieved"] is True,
        "scaling performance acceptance drift",
    )
    env_rows = []
    for item in scaling_payload["env_summaries"]:
        monitor = item["measured_gpu_monitor"]
        env_rows.append(
            {
                "env_count": int(item["env_count"]),
                "mean_transitions_per_s": float(item["mean_transitions_per_s"]),
                "speedup_vs_32_envs": float(item["speedup_vs_32_envs"]),
                "parallel_efficiency_vs_32_envs": float(item["parallel_efficiency_vs_32_envs"]),
                "coefficient_of_variation": float(item["coefficient_of_variation"]),
                "gpu_use_percent_mean": float(monitor["gpu_use_percent_mean"]),
                "gpu_use_percent_max": float(monitor["gpu_use_percent_max"]),
                "vram_used_bytes_max": int(monitor["vram_used_bytes_max"]),
                "measured_transitions": int(item["measured_transitions"]),
            }
        )
    require([row["env_count"] for row in env_rows] == [32, 128, 256, 512], "scaling env order drift")
    require(
        sum(row["measured_transitions"] for row in env_rows)
        == int(scaling_payload["total_measured_transitions"])
        == 2_227_200,
        "scaling measured-transition count drift",
    )
    scaling_summary = {
        "status": scaling_payload["status"],
        "performance_acceptance_achieved": bool(
            scaling_payload["performance_acceptance"]["achieved"]
        ),
        "fixed_pipeline": "r5 nominal deployed pipeline",
        "one_radeon_gpu": bool(scaling["execution_contract"]["one_radeon_gpu"]),
        "total_measured_transitions": int(scaling_payload["total_measured_transitions"]),
        "env_summaries": env_rows,
        "speedup_512_vs_32": env_rows[-1]["speedup_vs_32_envs"],
        "parallel_efficiency_512_vs_32": env_rows[-1]["parallel_efficiency_vs_32_envs"],
        "maximum_coefficient_of_variation": max(row["coefficient_of_variation"] for row in env_rows),
        "maximum_gpu_use_percent": max(row["gpu_use_percent_max"] for row in env_rows),
        "maximum_vram_used_bytes": max(row["vram_used_bytes_max"] for row in env_rows),
        "claim_boundary": scaling["claim_boundary"],
    }

    return {
        "v4": {
            "status": v4["status"],
            "fault_success": v4_success,
            "patch_vs_action_only_failure_reduction_fraction": v4_reduction,
            "award_evidence_eligible": False,
        },
        "v5": {
            "status": v5["status"],
            "fault_success": v5_success,
            "nominal_success": v5_nominal,
            "post_onset_operational_fields_raw_bit_exact": 19,
            "incremental_capability": 0,
            "award_evidence_eligible": False,
        },
        "scaling": scaling_summary,
        "v6": {
            "checkpoint": 30,
            "status": v6["status"],
            "recommendation": v6["recommendation"],
            "recurrence_checks": recurrence_checks,
            "lane_count": 12,
            "gate_counts": counts,
            "normalized_sigma_ratio_range": sigma_range,
            "lanes": lane_rows,
            "checkpoints_31_32_audited": False,
            "award_evidence_eligible": False,
        },
    }


def gate_matrix_svg(summary: dict[str, Any]) -> str:
    width, height = 1240, 520
    v4 = summary["v4"]
    v5 = summary["v5"]
    v6 = summary["v6"]
    v4_counts = v4["fault_success"]
    v5_counts = v5["fault_success"]
    v6_counts = v6["gate_counts"]
    v4_reduction_percent = 100.0 * v4["patch_vs_action_only_failure_reduction_fraction"]
    lines = svg_open(
        width,
        height,
        "FlightGuard three-campaign gate matrix",
        "v4 scientific failure, v5 award-ineligible tie, and v6 checkpoint-30 scientific failure.",
    )
    lines += [
        svg_text(52, 58, "FLIGHTGUARD · THREE-CASE CLAIM AUDIT", size=24, weight=700),
        svg_text(52, 88, "Green means a narrow check passed; it does not override a red scientific gate.", size=15, fill=COLORS["muted"]),
    ]
    columns = [
        (292, "INTEGRITY / RECURRENCE"),
        (532, "SCIENTIFIC / DEV GATE"),
        (772, "INCREMENTAL CAPABILITY"),
        (1012, "AWARD EVIDENCE"),
    ]
    for x, label in columns:
        lines.append(svg_text(x + 100, 130, label, size=12, weight=700, fill=COLORS["muted"], anchor="middle"))
    rows = [
        (
            "v4",
            "Causal IMU repair",
            [
                ("PASS", "registered raw evidence", "green"),
                ("FAIL", f"{v4_reduction_percent:.2f}% < 50%", "red"),
                (
                    "FAIL",
                    (
                        f"Patch {v4_counts['CausalIMUPatch']['successes']} < "
                        f"Raw {v4_counts['RawStrapdown']['successes']} / "
                        f"Cal {v4_counts['CalibratedStrapdown']['successes']}"
                    ),
                    "red",
                ),
                ("NO", "scientific FAIL", "panel_alt"),
            ],
        ),
        (
            "v5",
            "Residual-q95 scout",
            [
                (
                    "PASS",
                    f"{v5['post_onset_operational_fields_raw_bit_exact']} fields raw-bit exact",
                    "green",
                ),
                ("PASS", f"development status {v5['status']}", "green"),
                (
                    "ZERO",
                    (
                        f"Patch {v5_counts['CausalIMUPatch']['successes']} = "
                        f"Cal {v5_counts['CalibratedStrapdown']['successes']}"
                    ),
                    "amber",
                ),
                ("NO", "explicitly ineligible", "panel_alt"),
            ],
        ),
        (
            "v6",
            "Frozen observer · cp30",
            [
                (
                    "PASS",
                    "recur / no-op / kill"
                    if all(v6["recurrence_checks"].values())
                    else "recurrence gate failed",
                    "green",
                ),
                (
                    "FAIL",
                    f"{v6_counts['admitted']} / {v6['lane_count']} admitted",
                    "red",
                ),
                (
                    "ZERO",
                    f"{v6_counts['exact_cal_fallback']} exact-Cal fallback",
                    "red",
                ),
                ("NO", v6["recommendation"].lower().replace("_", " "), "panel_alt"),
            ],
        ),
    ]
    for row_index, (tag, name, cells) in enumerate(rows):
        y = 154 + row_index * 102
        lines.append(svg_rect(42, y, 1170, 84, fill=COLORS["panel"], rx=12))
        lines.append(svg_text(64, y + 34, tag.upper(), size=20, weight=800, fill=COLORS["blue"]))
        lines.append(svg_text(64, y + 59, name, size=14, fill=COLORS["muted"]))
        for (x, _), (headline, detail, color_key) in zip(columns, cells, strict=True):
            fill = COLORS[color_key]
            lines.append(svg_rect(x, y + 13, 200, 58, fill=COLORS["panel_alt"], rx=8, stroke=fill))
            lines.append(svg_text(x + 100, y + 38, headline, size=17, weight=800, fill=fill, anchor="middle"))
            lines.append(svg_text(x + 100, y + 59, detail, size=11, fill=COLORS["muted"], anchor="middle"))
    lines.append(svg_text(52, 482, "Simulation-only · single T265 development event · no sim-to-real, safety, or real-flight repair claim", size=14, fill=COLORS["muted"]))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def success_svg(summary: dict[str, Any]) -> str:
    width, height = 1180, 730
    lines = svg_open(
        width,
        height,
        "v4 and v5 fault-episode success comparison",
        "Fault successes derived from frozen v4 and v5 JSON summaries.",
    )
    lines += [
        svg_text(54, 58, "FAULT-EPISODE SUCCESS · FROZEN SUMMARIES", size=24, weight=700),
        svg_text(54, 88, "Bar length is success rate; labels retain exact counts.", size=15, fill=COLORS["muted"]),
    ]
    palette = {
        "CausalIMUPatch": COLORS["blue"],
        "ActionOnly": COLORS["amber"],
        "RawStrapdown": COLORS["purple"],
        "CalibratedStrapdown": COLORS["green"],
    }
    y = 140
    plot_x, plot_w = 330, 760
    for campaign in ("v4", "v5"):
        title = "v4 · scientific FAIL" if campaign == "v4" else "v5 · development PASS, award-ineligible"
        lines.append(svg_text(54, y, title, size=19, weight=700))
        y += 30
        for arm, metric in summary[campaign]["fault_success"].items():
            successes, episodes = metric["successes"], metric["episodes"]
            rate = successes / episodes
            lines.append(svg_text(66, y + 23, arm, size=15, weight=600))
            lines.append(svg_rect(plot_x, y, plot_w, 34, fill=COLORS["panel"], rx=6))
            if rate > 0:
                lines.append(svg_rect(plot_x, y, plot_w * rate, 34, fill=palette[arm], rx=6))
            lines.append(svg_text(plot_x + 12, y + 23, f"{successes} / {episodes}", size=14, weight=700))
            lines.append(svg_text(plot_x + plot_w, y + 23, f"{100 * rate:.1f}%", size=14, weight=700, anchor="end"))
            y += 52
        y += 30
    lines += [
        svg_text(54, 665, "v4 Patch improvement over ActionOnly did not establish superiority over Raw or Cal.", size=14, fill=COLORS["muted"]),
        svg_text(54, 691, "v5 Patch tied Cal and was post-onset raw-bit exact across 19 operational fields: incremental capability = 0.", size=14, fill=COLORS["muted"]),
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def lane_svg(summary: dict[str, Any]) -> str:
    width, height = 1340, 890
    lines = svg_open(
        width,
        height,
        "v6 checkpoint-30 lane qualification",
        "Twelve lanes pass rank and conditioning but fail the preregistered observability gate.",
    )
    counts = summary["v6"]["gate_counts"]
    sigma_min, sigma_max = summary["v6"]["normalized_sigma_ratio_range"]
    lines += [
        svg_text(42, 52, "V6 CHECKPOINT 30 · LANE QUALIFICATION", size=24, weight=700),
        svg_text(42, 82, f"0 / 12 admitted · 12 / 12 exact-Cal fallback · sigma {sigma_min:.17g}–{sigma_max:.17g}", size=15, fill=COLORS["muted"]),
    ]
    columns = [
        (174, "RANK 8", "rank8"),
        (300, "SIGMA", "sigma_pass"),
        (426, "SPLIT", "split_half"),
        (552, "Δv RMSE", "delta_v_rmse"),
        (678, "ROT RMSE", "rotation_rmse"),
        (804, "Δv q95", "delta_v_q95"),
        (930, "ROT q95", "rotation_q95"),
        (1056, "ADMIT", "admitted"),
        (1182, "FALLBACK", "exact_cal_fallback"),
    ]
    for x, label, key in columns:
        lines.append(svg_text(x + 52, 126, label, size=12, weight=700, fill=COLORS["muted"], anchor="middle"))
        lines.append(svg_text(x + 52, 147, f"{counts[key]} / 12", size=12, weight=700, anchor="middle"))
    for row_index, lane in enumerate(summary["v6"]["lanes"]):
        y = 170 + row_index * 54
        lines.append(svg_rect(34, y, 1272, 42, fill=COLORS["panel"] if row_index % 2 == 0 else COLORS["panel_alt"], rx=5))
        lines.append(svg_text(54, y + 27, f"LANE {lane['lane']:02d}", size=13, weight=700))
        for x, _label, key in columns:
            passed = bool(lane[key])
            color = COLORS["green"] if passed else COLORS["red"]
            if key == "exact_cal_fallback":
                color = COLORS["amber"] if passed else COLORS["red"]
            lines.append(svg_rect(x + 34, y + 11, 36, 20, fill=color, rx=10))
            mark = "✓" if passed else "×"
            lines.append(svg_text(x + 52, y + 26, mark, size=14, weight=800, fill=COLORS["bg"], anchor="middle"))
    lines += [
        svg_text(42, 848, "Checkpoint rule: at least 9 / 12 admitted. Result: FAIL; checkpoints 31 and 32 were not audited.", size=15, weight=700, fill=COLORS["red"]),
        "</svg>",
    ]
    return "\n".join(lines) + "\n"



def scaling_svg(summary: dict[str, Any]) -> str:
    width, height = 1240, 650
    scaling = summary["scaling"]
    rows = scaling["env_summaries"]
    maximum = max(row["mean_transitions_per_s"] for row in rows)
    lines = svg_open(
        width,
        height,
        "Radeon fixed-pipeline scaling",
        "Measured throughput for the fixed r5 nominal deployed simulation pipeline on one AMD Radeon GPU.",
    )
    lines += [
        svg_text(50, 56, "ONE RADEON · FIXED R5 NOMINAL DEPLOYED PIPELINE", size=24, weight=700),
        svg_text(50, 86, f"{scaling['total_measured_transitions']:,} measured transitions · three measured runs per environment count", size=15, fill=COLORS["muted"]),
    ]
    plot_x, plot_y, plot_w, plot_h = 120, 150, 1020, 330
    lines.append(f'  <line x1="{plot_x}" y1="{plot_y + plot_h}" x2="{plot_x + plot_w}" y2="{plot_y + plot_h}" stroke="{COLORS["line"]}"/>')
    lines.append(f'  <line x1="{plot_x}" y1="{plot_y}" x2="{plot_x}" y2="{plot_y + plot_h}" stroke="{COLORS["line"]}"/>')
    for tick in range(5):
        value = maximum * tick / 4
        y = plot_y + plot_h - plot_h * tick / 4
        lines.append(f'  <line x1="{plot_x}" y1="{y}" x2="{plot_x + plot_w}" y2="{y}" stroke="{COLORS["line"]}" stroke-opacity="0.45"/>')
        lines.append(svg_text(plot_x - 14, y + 5, f"{value / 1000:.0f}k", size=12, fill=COLORS["muted"], anchor="end"))
    bar_w = 150
    gap = (plot_w - bar_w * len(rows)) / (len(rows) + 1)
    for index, row in enumerate(rows):
        x = plot_x + gap + index * (bar_w + gap)
        bar_h = plot_h * row["mean_transitions_per_s"] / maximum
        y = plot_y + plot_h - bar_h
        lines.append(svg_rect(x, y, bar_w, bar_h, fill=COLORS["blue"], rx=8))
        lines.append(svg_text(x + bar_w / 2, y - 12, f"{row['mean_transitions_per_s']:,.1f}", size=14, weight=700, anchor="middle"))
        lines.append(svg_text(x + bar_w / 2, plot_y + plot_h + 28, f"{row['env_count']} envs", size=14, weight=700, anchor="middle"))
        lines.append(svg_text(x + bar_w / 2, plot_y + plot_h + 50, f"GPU mean {row['gpu_use_percent_mean']:.4f}%", size=11, fill=COLORS["muted"], anchor="middle"))
    summary_y = 548
    summary_cells = [
        ("512 / 32 SPEEDUP", f"{scaling['speedup_512_vs_32']:.15f}x"),
        ("PARALLEL EFFICIENCY", f"{scaling['parallel_efficiency_512_vs_32']:.15f}"),
        ("MAX CV", f"{scaling['maximum_coefficient_of_variation']:.16f}"),
        ("MAX GPU", f"{scaling['maximum_gpu_use_percent']:.0f}%"),
        ("MAX VRAM", f"{scaling['maximum_vram_used_bytes']:,} B"),
    ]
    cell_w = 220
    for index, (label, value) in enumerate(summary_cells):
        x = 50 + index * 236
        lines.append(svg_rect(x, summary_y, cell_w, 62, fill=COLORS["panel"], rx=8, stroke=COLORS["line"]))
        lines.append(svg_text(x + 12, summary_y + 22, label, size=11, weight=700, fill=COLORS["muted"]))
        lines.append(svg_text(x + 12, summary_y + 47, value, size=14, weight=700))
    lines.append(svg_text(50, 634, "Throughput evidence only: no scientific superiority, sim-to-real, safety, or real-flight claim.", size=13, fill=COLORS["muted"]))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def csv_text(summary: dict[str, Any]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("campaign", "category", "name", "value", "denominator", "passed"))
    for campaign in ("v4", "v5"):
        for arm, metric in summary[campaign]["fault_success"].items():
            writer.writerow((campaign, "fault_success", arm, metric["successes"], metric["episodes"], ""))
    gate_names = (
        "admitted",
        "exact_cal_fallback",
        "rank8",
        "sigma_pass",
        "split_half",
        "delta_v_rmse",
        "rotation_rmse",
        "delta_v_q95",
        "rotation_q95",
    )
    for name in gate_names:
        value = summary["v6"]["gate_counts"][name]
        gate_passed = {
            "admitted": value >= 9,
            "exact_cal_fallback": value == 12,
            "rank8": value == 12,
            "sigma_pass": value == 12,
            "split_half": value == 12,
            "delta_v_rmse": value == 12,
            "rotation_rmse": value == 12,
            "delta_v_q95": value == 12,
            "rotation_q95": value == 12,
        }[name]
        writer.writerow(("v6_cp30", "lane_gate", name, value, 12, str(gate_passed).lower()))
    for row in summary["scaling"]["env_summaries"]:
        writer.writerow(("radeon_scaling", "throughput", row["env_count"], row["mean_transitions_per_s"], row["measured_transitions"], ""))
        writer.writerow(("radeon_scaling", "gpu_mean_percent", row["env_count"], row["gpu_use_percent_mean"], "", ""))
        writer.writerow(("radeon_scaling", "coefficient_of_variation", row["env_count"], row["coefficient_of_variation"], "", ""))
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v4", required=True, type=Path)
    parser.add_argument("--v5", required=True, type=Path)
    parser.add_argument("--v6", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    inputs: dict[str, dict[str, object]] = {}
    values: dict[str, dict[str, Any]] = {}
    for role, path in (("v4", args.v4), ("v5", args.v5), ("v6", args.v6), ("scaling", args.scaling)):
        value, digest = load_verified(role, path)
        values[role] = value
        inputs[role] = {"path": str(path.resolve()), "sha256": digest, "size_bytes": path.stat().st_size}

    summary = extract(values["v4"], values["v5"], values["v6"], values["scaling"])
    summary_document = {
        "schema_version": "flightguard.award_evidence_summary.v1",
        "simulation_only": True,
        "inputs": inputs,
        "results": summary,
        "claim_boundary": {
            "single_t265_development_event": True,
            "causal_only_relative_to_ros_bag_record_time_availability_proxy": True,
            "sim_to_real_claimed": False,
            "safety_claimed": False,
            "real_flight_repair_claimed": False,
            "formal_superiority_claimed": False,
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = [name for name in OUTPUT_NAMES if (args.output_dir / name).exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite outputs: {existing}")

    rendered = {
        "gate-matrix.svg": gate_matrix_svg(summary),
        "v4-v5-fault-success.svg": success_svg(summary),
        "v6-lane-qualification.svg": lane_svg(summary),
        "radeon-scaling.svg": scaling_svg(summary),
        "summary.csv": csv_text(summary),
        "summary.json": json.dumps(summary_document, indent=2, sort_keys=True) + "\n",
    }
    for name in OUTPUT_NAMES:
        write_new(args.output_dir / name, rendered[name])

    report = {
        "inputs": inputs,
        "outputs": {
            name: {
                "path": str((args.output_dir / name).resolve()),
                "sha256": sha256_bytes((args.output_dir / name).read_bytes()),
                "size_bytes": (args.output_dir / name).stat().st_size,
            }
            for name in OUTPUT_NAMES
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
