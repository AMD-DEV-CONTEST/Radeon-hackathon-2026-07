#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.config import load_config
from parcel_sorter.expert import ScriptedPickPlaceExpert
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.state_machine import ClosedLoopSupervisor, Stage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report robot-parcel contact links for one deterministic expert episode."
    )
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/catalog_v2.toml")
    parser.add_argument("--profile", default="large_narrow_carton")
    parser.add_argument("--episode", type=int, default=7_000_005)
    parser.add_argument("--backend", choices=("cpu", "rocm"), default="rocm")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _link_names(entity: Any) -> dict[int, str]:
    return {
        int(link.idx): str(link.name)
        for link in entity.links
    }


def _flat_list(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "reshape"):
        value = value.reshape(-1)
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def _resolve_contact_pair(
    link_a_index: int,
    link_b_index: int,
    robot_names: dict[int, str],
    parcel_names: dict[int, str],
) -> tuple[int, int]:
    if link_a_index in robot_names and link_b_index in parcel_names:
        return link_a_index, link_b_index
    if link_b_index in robot_names and link_a_index in parcel_names:
        return link_b_index, link_a_index
    raise RuntimeError(
        "robot-parcel contact contains an unmapped link pair: "
        f"{link_a_index}, {link_b_index}"
    )


def _active_contacts(env: GenesisParcelEnv) -> list[dict[str, Any]]:
    contacts = env.robot.get_contacts(with_entity=env.parcel)
    forces = contacts["force_a"]
    magnitudes = env.torch.linalg.vector_norm(forces, dim=-1)
    valid = contacts.get("valid_mask")
    if valid is None:
        valid = magnitudes > 0
    else:
        valid = valid & (magnitudes > 0)
    indices = env.torch.nonzero(valid, as_tuple=False).reshape(-1)
    if int(indices.numel()) == 0:
        return []

    robot_names = _link_names(env.robot)
    parcel_names = _link_names(env.parcel)
    link_a = contacts["link_a"]
    link_b = contacts["link_b"]
    rows = []
    for tensor_index in indices.detach().cpu().tolist():
        index = int(tensor_index)
        link_a_index = int(link_a[index].item())
        link_b_index = int(link_b[index].item())
        robot_index, parcel_index = _resolve_contact_pair(
            link_a_index,
            link_b_index,
            robot_names,
            parcel_names,
        )
        rows.append(
            {
                "robot_link_index": robot_index,
                "robot_link_name": robot_names[robot_index],
                "parcel_link_index": parcel_index,
                "parcel_link_name": parcel_names[parcel_index],
                "force_n": float(magnitudes[index].item()),
            }
        )
    return rows


def _step_with_substep_contacts(
    env: GenesisParcelEnv,
    action: Any,
    frame: int,
    stage: str,
    command: str,
) -> list[dict[str, Any]]:
    """Mirror the environment step while observing every 240 Hz physics substep."""
    env._action_queue.append(action)
    delayed_action = env._action_queue.popleft()
    if delayed_action is not None:
        env._apply_action(delayed_action)

    events = []
    physics_steps = env.config.simulation.physics_hz // env.config.simulation.control_hz
    for substep in range(physics_steps):
        env.scene.step()
        ee_position = _flat_list(env.end_effector.get_pos())
        parcel_position = _flat_list(env.parcel.get_pos())
        for contact in _active_contacts(env):
            events.append(
                {
                    "frame": frame,
                    "physics_substep": substep,
                    "stage": stage,
                    "command": command,
                    "ee_position_m": ee_position,
                    "parcel_position_m": parcel_position,
                    **contact,
                }
            )
    env.control_step += 1
    return events


def run_diagnostic(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    sample = randomizer.sample_profile(args.profile, args.episode)
    expert = ScriptedPickPlaceExpert(config, sample)
    supervisor = ClosedLoopSupervisor(
        config.task.max_grasp_retries,
        grasp_settle_steps=config.task.grasp_settle_steps,
        release_settle_steps=config.task.release_settle_steps,
        grasp_stability_steps=sample.grasp_stability_steps or config.task.grasp_stability_steps,
    )
    contacts_by_link: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []

    initialization_events: list[dict[str, Any]] = []
    with GenesisParcelEnv(
        config,
        sample,
        backend=args.backend,
        defer_initialization_settle=True,
    ) as env:
        for substep in range(env.initialization_settle_steps):
            env.scene.step()
            ee_position = _flat_list(env.end_effector.get_pos())
            parcel_position = _flat_list(env.parcel.get_pos())
            for contact in _active_contacts(env):
                initialization_events.append(
                    {
                        "physics_substep": substep,
                        "ee_position_m": ee_position,
                        "parcel_position_m": parcel_position,
                        **contact,
                    }
                )
        initial_state = env.state()
        robot_links = [
            {
                "index": int(link.idx),
                "name": str(link.name),
                "aabb_m": [_flat_list(corner) for corner in link.get_AABB()],
            }
            for link in env.robot.links
        ]
        max_steps = int(config.task.episode_seconds * config.simulation.control_hz)
        for frame in range(max_steps):
            state = env.state()
            observation = env.observation(state)
            decision = supervisor.step(observation)
            if supervisor.stage in {Stage.COMPLETE, Stage.ABORT}:
                break
            action = expert.action(decision, state)
            step_contacts = _step_with_substep_contacts(
                env,
                action,
                frame,
                decision.stage,
                decision.command,
            )
            for contact in step_contacts:
                name = contact["robot_link_name"]
                aggregate = contacts_by_link.setdefault(
                    name,
                    {
                        "robot_link_index": contact["robot_link_index"],
                        "first_frame": frame,
                        "last_frame": frame,
                        "samples": 0,
                        "peak_force_n": 0.0,
                    },
                )
                aggregate["last_frame"] = frame
                aggregate["samples"] += 1
                aggregate["peak_force_n"] = max(
                    aggregate["peak_force_n"], contact["force_n"]
                )
                events.append(
                    contact
                )

        final_state = env.state()
        result = {
            "config": str(args.config.resolve()),
            "backend": args.backend,
            "profile": args.profile,
            "episode": args.episode,
            "sample": asdict(sample),
            "terminal_stage": supervisor.stage.value,
            "retry_count": supervisor.retry_count,
            "initial_state": asdict(initial_state),
            "final_state": asdict(final_state),
            "initialization_contact_events": initialization_events,
            "robot_links": robot_links,
            "contacts_by_robot_link": contacts_by_link,
            "contact_events": events,
        }
    return result


def main() -> int:
    args = parse_args()
    result = run_diagnostic(args)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
