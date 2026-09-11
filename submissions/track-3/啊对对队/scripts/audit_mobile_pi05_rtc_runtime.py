#!/usr/bin/env python3
"""Audit the installed LeRobot PI0.5 RTC contract without running a policy."""

from __future__ import annotations

import argparse
from dataclasses import fields
import importlib.metadata
import inspect
import json
from pathlib import Path
from typing import Any


def build_rtc_runtime_audit() -> dict[str, Any]:
    from lerobot.policies.pi05.configuration_pi05 import PI05Config
    from lerobot.policies.pi05.modeling_pi05 import PI05Policy, PI05Pytorch
    from lerobot.policies.rtc.configuration_rtc import RTCConfig
    from lerobot.policies.rtc.modeling_rtc import RTCProcessor

    errors: list[str] = []
    pi05_fields = {field.name for field in fields(PI05Config)}
    rtc_fields = {field.name for field in fields(RTCConfig)}
    required_rtc_fields = {
        "enabled",
        "prefix_attention_schedule",
        "max_guidance_weight",
        "execution_horizon",
    }
    if "rtc_config" not in pi05_fields:
        errors.append("pi05_config_missing_rtc_config")
    if not required_rtc_fields <= rtc_fields:
        errors.append("rtc_config_fields_missing")

    predict_signature = inspect.signature(PI05Policy.predict_action_chunk)
    sample_signature = inspect.signature(PI05Pytorch.sample_actions)
    processor_signature = inspect.signature(RTCProcessor.denoise_step)
    sample_source = inspect.getsource(PI05Pytorch.sample_actions)
    select_source = inspect.getsource(PI05Policy.select_action)
    required_forwarded_kwargs = {
        "inference_delay",
        "prev_chunk_left_over",
        "execution_horizon",
    }
    missing_forwarded = sorted(
        name for name in required_forwarded_kwargs if name not in sample_source
    )
    if missing_forwarded:
        errors.append("pi05_sample_actions_missing_rtc_kwargs")
    if "RTC is not supported for select_action" not in select_source:
        errors.append("select_action_rtc_guard_missing")

    processor_parameters = set(processor_signature.parameters)
    missing_processor = sorted(required_forwarded_kwargs - processor_parameters)
    if missing_processor:
        errors.append("rtc_processor_parameters_missing")

    return {
        "schema_version": 1,
        "protocol": "pi05-lerobot-rtc-runtime-audit-v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "lerobot_version": importlib.metadata.version("lerobot"),
        "pi05_predict_action_chunk_signature": str(predict_signature),
        "pi05_sample_actions_signature": str(sample_signature),
        "rtc_processor_denoise_step_signature": str(processor_signature),
        "pi05_rtc_config_field_present": "rtc_config" in pi05_fields,
        "rtc_config_fields": sorted(rtc_fields),
        "required_forwarded_kwargs": sorted(required_forwarded_kwargs),
        "missing_forwarded_kwargs": missing_forwarded,
        "missing_processor_parameters": missing_processor,
        "select_action_rejects_rtc": (
            "RTC is not supported for select_action" in select_source
        ),
        "claim_boundary": (
            "This proves only that the installed LeRobot API exposes the expected "
            "PI0.5 RTC contract. It does not prove timing, action continuity, safety, "
            "or closed-loop capability."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_rtc_runtime_audit()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
