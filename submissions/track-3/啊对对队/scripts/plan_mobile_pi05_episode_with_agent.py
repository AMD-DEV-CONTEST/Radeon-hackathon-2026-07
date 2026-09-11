#!/usr/bin/env python3
"""Create one audited high-level Agent directive for a PI0.5 episode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parcel_sorter.checkpoint_registry import sha256_file
from parcel_sorter.harness_agent import HarnessAgentConfig, plan_task_with_agent
from parcel_sorter.harness_task_bridge import compile_task_directive_for_pi05
from parcel_sorter.responses_task_agent import (
    OpenAICompatibleResponsesTaskAgent,
    ResponsesClientConfig,
    ResponsesTaskAgentError,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Call a bounded Responses task Agent, validate its directive, and "
            "compile task conditioning for PI0.5. No robot action is executed."
        )
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config_payload = _read_json(args.config)
    observation = _read_json(args.observation)
    harness_config = HarnessAgentConfig.from_dict(config_payload)
    client_payload = config_payload.get("responses_client")
    if not isinstance(client_payload, dict):
        raise ValueError("config must contain responses_client")
    if client_payload.get("store") is not False:
        raise ValueError("Responses storage must be explicitly disabled")
    client_config = ResponsesClientConfig(
        base_url=str(client_payload["base_url"]),
        model=str(client_payload["model"]),
        api_key_env=str(client_payload.get("api_key_env") or "OPENAI_API_KEY"),
        timeout_s=float(client_payload.get("timeout_s", 90.0)),
        fallback_timeout_s=(
            float(client_payload["fallback_timeout_s"])
            if client_payload.get("fallback_timeout_s") is not None
            else None
        ),
        reasoning_effort=str(client_payload.get("reasoning_effort") or "xhigh"),
        max_output_tokens=int(client_payload.get("max_output_tokens", 512)),
        fallback_model=(
            str(client_payload["fallback_model"])
            if client_payload.get("fallback_model")
            else None
        ),
        primary_attempts=int(client_payload.get("primary_attempts", 1)),
    )
    planner = OpenAICompatibleResponsesTaskAgent(
        harness_config.task_agent, client_config
    )
    try:
        directive = plan_task_with_agent(
            observation,
            planner=planner,
            config=harness_config,
        )
    except ResponsesTaskAgentError:
        failed = {
            "schema_version": 1,
            "protocol": "parcel-agent-pi05-episode-plan-v1",
            "status": "failed_closed",
            "config_sha256": sha256_file(args.config),
            "observation_sha256": sha256_file(args.observation),
            "agent_trace": planner.last_trace,
        }
        _write_json_atomic(args.output, failed)
        print(json.dumps(failed, indent=2))
        return 2
    bridge = compile_task_directive_for_pi05(
        directive, task_agent=harness_config.task_agent
    )
    result = {
        "schema_version": 1,
        "protocol": "parcel-agent-pi05-episode-plan-v1",
        "status": "passed",
        "config_sha256": sha256_file(args.config),
        "observation_sha256": sha256_file(args.observation),
        "agent_trace": planner.last_trace,
        "directive": directive,
        "pi05_task_bridge": bridge,
        "claim_boundary": (
            "Agent supplies task conditioning only; PI0.5 and the safety harness "
            "retain their separately audited runtime attribution"
        ),
    }
    _write_json_atomic(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "actual_model": result["agent_trace"]["actual_model"],
                "fallback_used": result["agent_trace"]["fallback_used"],
                "grasp_mode": directive["grasp_mode"],
                "recovery_strategy": directive["recovery_strategy"],
                "output": str(args.output.resolve()),
            },
            indent=2,
        )
    )
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
