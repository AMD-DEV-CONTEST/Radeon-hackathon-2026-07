#!/usr/bin/env python3
"""Derive auditable metrics only from explicit match-log telemetry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

CLIENTS = [f"client_{i}" for i in range(6)]
BALL_FIELDS = ("x", "y", "z", "vx", "vy", "vz")
ROBOT_FIELDS = ("x", "y", "z", "pitch", "roll")
EVENT_FIELDS = ("fallen", "scored")


def _finite(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"fail-closed: {where} must be a finite number")
    return float(value)


def _bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"fail-closed: {where} must be boolean")
    return value


def load_and_validate(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get("n_clients") != 6:
        raise ValueError("fail-closed: n_clients must equal 6")
    identities = data.get("identities")
    if not isinstance(identities, dict) or set(identities) != set(CLIENTS):
        raise ValueError("fail-closed: identities must cover exactly client_0..client_5")
    for client, identity in identities.items():
        if not isinstance(identity, dict) or not all(isinstance(identity.get(k), str) and identity[k] for k in ("team", "role", "controller", "model_sha")):
            raise ValueError(f"fail-closed: incomplete identity for {client}")
        if not isinstance(identity.get("ball_authority"), bool):
            raise ValueError(f"fail-closed: {client}.ball_authority must be boolean")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", identity["model_sha"]):
            raise ValueError(f"fail-closed: {client}.model_sha must be 64 hex characters")
    if sum(identity["ball_authority"] for identity in identities.values()) != 1:
        raise ValueError("fail-closed: exactly one client must have ball_authority")
    for team, controller in (("A", "ONNX"), ("B", "Rule")):
        members = [identity for identity in identities.values() if identity["team"] == team]
        if len(members) != 3:
            raise ValueError(f"fail-closed: team {team} must contain exactly three clients")
        if {identity["role"] for identity in members} != {"attacker", "defender", "keeper"}:
            raise ValueError(f"fail-closed: team {team} must have one attacker, defender, and keeper")
        if any(identity["controller"] != controller for identity in members):
            raise ValueError(f"fail-closed: team {team} controller must be {controller}")
    log = data.get("log")
    if not isinstance(log, list) or not log or data.get("steps") != len(log):
        raise ValueError("fail-closed: non-empty log and steps == len(log) required")
    previous_t = -math.inf
    for i, frame in enumerate(log):
        t = _finite(frame.get("t"), f"log[{i}].t")
        if t <= previous_t:
            raise ValueError("fail-closed: timestamps must be strictly increasing")
        previous_t = t
        ball, robots, events = frame.get("ball"), frame.get("robots"), frame.get("events")
        if not isinstance(ball, dict) or set(BALL_FIELDS) - set(ball):
            raise ValueError(f"fail-closed: log[{i}].ball requires all position and velocity fields")
        for field in BALL_FIELDS:
            _finite(ball[field], f"log[{i}].ball.{field}")
        if not isinstance(robots, dict) or set(robots) != set(CLIENTS):
            raise ValueError(f"fail-closed: log[{i}].robots must cover exactly six clients")
        if not isinstance(events, dict) or set(events) != set(CLIENTS):
            raise ValueError(f"fail-closed: log[{i}].events must cover exactly six clients")
        for client in CLIENTS:
            robot, event = robots[client], events[client]
            for field in ROBOT_FIELDS:
                _finite(robot.get(field), f"log[{i}].robots.{client}.{field}")
            for field in EVENT_FIELDS:
                explicit = _bool(event.get(field), f"log[{i}].events.{client}.{field}")
                if field in robot and _bool(robot[field], f"log[{i}].robots.{client}.{field}") != explicit:
                    raise ValueError(f"fail-closed: robot/event telemetry mismatch at log[{i}] {client}.{field}")
    return data, hashlib.sha256(raw).hexdigest()


def _spawn_sentinel(robot: dict[str, Any]) -> bool:
    return all(float(robot[k]) == v for k, v in {"x": 0, "y": 0, "z": .7, "pitch": 0, "roll": 0}.items())


def _distance(robot: dict[str, Any], ball: dict[str, Any]) -> float:
    return math.hypot(float(robot["x"]) - float(ball["x"]), float(robot["y"]) - float(ball["y"]))


def _rising_edges(log: list[dict[str, Any]], client: str, field: str) -> list[int]:
    result, previous = [], False
    for index, frame in enumerate(log):
        current = frame["events"][client][field]
        if current and not previous:
            result.append(index)
        previous = current
    return result


def analyze(data: dict[str, Any], source: str, source_sha256: str) -> dict[str, Any]:
    log, identities = data["log"], data["identities"]
    ball_authority = next(client for client in CLIENTS if identities[client]["ball_authority"])
    clients: dict[str, Any] = {}
    for client in CLIENTS:
        initialized = [i for i, f in enumerate(log) if not _spawn_sentinel(f["robots"][client])]
        if not initialized:
            raise ValueError(f"fail-closed: {client} never leaves spawn sentinel")
        start = initialized[0]
        frames = log[start:]
        distances = [_distance(f["robots"][client], f["ball"]) for f in frames]
        fallen_true = [i for i, f in enumerate(log) if f["events"][client]["fallen"]]
        scored_true = [i for i, f in enumerate(log) if f["events"][client]["scored"]]
        visible_orientation = [
            i for i, f in enumerate(log[start:], start=start)
            if float(f["robots"][client]["z"]) < .8
            or abs(float(f["robots"][client]["pitch"])) > 30
            or abs(float(f["robots"][client]["roll"])) > 30
        ]
        clients[client] = {
            **identities[client],
            "first_initialized_frame": start,
            "evaluated_distance_frames": len(frames),
            "base_to_ball_planar_m": {"mean": sum(distances) / len(distances), "min": min(distances), "final": distances[-1]},
            "explicit_events": {
                "fallen_true_frames": fallen_true,
                "fallen_frame_rate": len(fallen_true) / len(log),
                "fall_event_rising_edges": _rising_edges(log, client, "fallen"),
                "fall_event_count": len(_rising_edges(log, client, "fallen")),
                "scored_true_frames": scored_true,
                "score_event_rising_edges": _rising_edges(log, client, "scored"),
                "score_event_count": len(_rising_edges(log, client, "scored")),
                "score_events_consumed_for_match_goal": client == ball_authority,
            },
            "visible_orientation_only": {
                "threshold_frames": visible_orientation,
                "threshold_frame_rate": len(visible_orientation) / len(log),
                "not_used_as_fall_events": True,
            },
        }
    teams = {}
    for team in sorted({i["team"] for i in identities.values()}):
        members = [c for c in CLIENTS if identities[c]["team"] == team]
        all_distances = [_distance(f["robots"][c], f["ball"]) for c in members for f in log[clients[c]["first_initialized_frame"]:]]
        teams[team] = {
            "clients": members,
            "fall_event_count": sum(clients[c]["explicit_events"]["fall_event_count"] for c in members),
            "score_event_count": clients[ball_authority]["explicit_events"]["score_event_count"] if ball_authority in members else 0,
            "base_to_ball_planar_m": {
                "mean": sum(all_distances) / len(all_distances), "min": min(all_distances),
                "final": sum(clients[c]["base_to_ball_planar_m"]["final"] for c in members) / len(members),
            },
        }
    ball_x = [float(f["ball"]["x"]) for f in log]
    first = log[0]
    return {
        "schema_version": 2,
        "source": source,
        "source_sha256": source_sha256,
        "validation": {"n_clients": 6, "declared_steps": data["steps"], "observed_steps": len(log), "status": "passed"},
        "definitions": {
            "identity": "taken directly from top-level identities; connection order is not used",
            "fall_and_score": "falls are explicit false-to-true edges; match/team scores consume scored edges only from the unique ball_authority client",
            "visible_orientation": "z/pitch/roll threshold is descriptive only and is never treated as an event",
            "distance": "planar robot base-centre to ball-centre distance; not foot contact",
        },
        "initial_conditions": {
            "first_logged_t": float(first["t"]),
            "ball": {k: float(first["ball"][k]) for k in BALL_FIELDS},
            "robots": {c: {k: float(first["robots"][c][k]) for k in ROBOT_FIELDS} for c in CLIENTS},
            "caveat": "exact identical initial robot states are coordinator spawn sentinels; distance windows start per client at first non-sentinel frame",
        },
        "clients": clients,
        "teams": teams,
        "ball_progress": {"initial_x_m": ball_x[0], "final_x_m": ball_x[-1], "net_x_m": ball_x[-1] - ball_x[0], "min_x_m": min(ball_x), "max_x_m": max(ball_x)},
        "match_events": {
            "fall_event_count": sum(v["explicit_events"]["fall_event_count"] for v in clients.values()),
            "ball_authority_client": ball_authority,
            "score_event_count": clients[ball_authority]["explicit_events"]["score_event_count"],
            "goal_scored": clients[ball_authority]["explicit_events"]["score_event_count"] > 0,
            "goal_boundary_inference_used": False,
        },
        "unsupported_metrics": {"foot_contacts": None, "reward_components": None},
    }


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    fields = ["client", "team", "role", "controller", "model_sha", "first_initialized_frame", "evaluated_distance_frames", "fall_event_count", "fallen_true_frames", "fallen_frame_rate", "score_event_count", "distance_mean_m", "distance_min_m", "distance_final_m"]
    with (output_dir / "client_metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for client, m in result["clients"].items():
            event, distance = m["explicit_events"], m["base_to_ball_planar_m"]
            writer.writerow({"client": client, "team": m["team"], "role": m["role"], "controller": m["controller"], "model_sha": m["model_sha"], "first_initialized_frame": m["first_initialized_frame"], "evaluated_distance_frames": m["evaluated_distance_frames"], "fall_event_count": event["fall_event_count"], "fallen_true_frames": len(event["fallen_true_frames"]), "fallen_frame_rate": f'{event["fallen_frame_rate"]:.6f}', "score_event_count": event["score_event_count"], "distance_mean_m": f'{distance["mean"]:.6f}', "distance_min_m": f'{distance["min"]:.6f}', "distance_final_m": f'{distance["final"]:.6f}'})
    with (output_dir / "team_metrics.csv").open("w", newline="") as f:
        fields = ["team", "clients", "fall_event_count", "score_event_count", "distance_mean_m", "distance_min_m", "distance_final_mean_m"]
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for team, m in result["teams"].items():
            distance = m["base_to_ball_planar_m"]
            writer.writerow({"team": team, "clients": ";".join(m["clients"]), "fall_event_count": m["fall_event_count"], "score_event_count": m["score_event_count"], "distance_mean_m": f'{distance["mean"]:.6f}', "distance_min_m": f'{distance["min"]:.6f}', "distance_final_mean_m": f'{distance["final"]:.6f}'})
    authority = result["match_events"]["ball_authority_client"]
    lines = ["# multi-robot Match Log Analysis", "", f"Source: `{result['source']}`  ", f"SHA-256: `{result['source_sha256']}`", "", f"Identity comes from the log's explicit `identities` map; connection order is not used. Falls use explicit false→true event edges. Match/team goal counts consume scored edges only from the unique ball authority `{authority}`; other clients' scored flags are observational. Orientation thresholds are descriptive and do not create events. Distances are base-centre proxies, not foot contacts; reward components are unavailable.", "", "| client | identity | fall events | fallen frames/rate | observed score edges | distance mean/min/final (m) |", "|---|---|---:|---:|---:|---:|"]
    for client, m in result["clients"].items():
        e, d = m["explicit_events"], m["base_to_ball_planar_m"]
        lines.append(f"| {client} | {m['team']} / {m['role']} / {m['controller']} | {e['fall_event_count']} | {len(e['fallen_true_frames'])} / {e['fallen_frame_rate']:.3f} | {e['score_event_count']} | {d['mean']:.3f} / {d['min']:.3f} / {d['final']:.3f} |")
    p, events = result["ball_progress"], result["match_events"]
    lines += ["", "## Ball and events", "", f"Ball x moved from {p['initial_x_m']:.4f} m to {p['final_x_m']:.4f} m (net {p['net_x_m']:.4f} m; observed range {p['min_x_m']:.4f}–{p['max_x_m']:.4f} m). Explicit score-event edges: {events['score_event_count']}; goal scored: **{'yes' if events['goal_scored'] else 'no'}**. No goal-line inference is used.", "", "## Initial-condition caveat", "", result["initial_conditions"]["caveat"] + ".", ""]
    (output_dir / "REPORT.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    data, digest = load_and_validate(args.input)
    write_outputs(analyze(data, str(args.input), digest), args.output_dir)


if __name__ == "__main__":
    main()
