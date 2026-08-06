"""Shared, evidence-safe configuration helpers for RadeonStay evaluators."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from typing import Any

SERVICE_CONFIGURATION_DEFAULTS: dict[str, int | str] = {
    "ctx": 16384,
    "parallel": 1,
    "batch": 512,
    "ubatch": 128,
    "flash_attn": "auto",
    "gpu_layers": 999,
    "cache_type_k": "f16",
    "cache_type_v": "f16",
    "log_verbosity": 5,
}
SERVICE_CONFIGURATION_FIELDS = tuple(SERVICE_CONFIGURATION_DEFAULTS)
INTEGER_SERVICE_FIELDS = {
    "ctx",
    "parallel",
    "batch",
    "ubatch",
    "gpu_layers",
    "log_verbosity",
}
TUNABLE_CONFIGURATION_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "thinking": (("request", "thinking_enabled"),),
    "flash_attention": (("service", "flash_attn"),),
    "batch_sizing": (("service", "batch"), ("service", "ubatch")),
    "fused_plan_evidence": (("request", "fused_plan_evidence"),),
    "context_size": (("service", "ctx"),),
    "parallelism": (("service", "parallel"),),
    "kv_cache_quantization": (
        ("service", "cache_type_k"),
        ("service", "cache_type_v"),
    ),
}


def _environment_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def fused_plan_evidence_enabled(settings: Any) -> bool:
    """Read the application fusion switch while remaining compatible with P0 settings."""

    value = getattr(settings, "fused_plan_evidence", None)
    if type(value) is bool:
        return value
    return _environment_bool("RADEONSTAY_FUSED_PLAN_EVIDENCE")


def request_configuration(settings: Any) -> dict[str, bool]:
    return normalize_request_configuration(
        {
            "thinking_enabled": bool(settings.model_enable_thinking),
            "schema_constrained": True,
            "fused_plan_evidence": fused_plan_evidence_enabled(settings),
        },
        "request configuration",
    )


def normalize_request_configuration(value: Any, label: str) -> dict[str, bool]:
    fields = {"thinking_enabled", "schema_constrained", "fused_plan_evidence"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} must contain the exact request configuration fields")
    if any(type(value[field]) is not bool for field in fields):
        raise ValueError(f"{label} values must be booleans")
    if value["schema_constrained"] is not True:
        raise ValueError(f"{label} must keep schema-constrained generation enabled")
    return {
        "thinking_enabled": value["thinking_enabled"],
        "schema_constrained": value["schema_constrained"],
        "fused_plan_evidence": value["fused_plan_evidence"],
    }


def request_configuration_sha256(value: Any, label: str) -> str:
    """Hash all request-side optimization variables in canonical form."""

    normalized = normalize_request_configuration(value, label)
    canonical = json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def add_service_configuration_arguments(parser: argparse.ArgumentParser) -> None:
    """Add optional launch-binding fields without breaking legacy evaluator CLIs."""

    parser.add_argument("--experiment", default="standalone")
    parser.add_argument("--context-size", type=int, default=16384)
    parser.add_argument("--parallel-slots", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--ubatch-size", type=int, default=128)
    parser.add_argument("--flash-attn", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--gpu-layers", type=int, default=999)
    parser.add_argument("--cache-type-k", default="f16")
    parser.add_argument("--cache-type-v", default="f16")
    parser.add_argument("--log-verbosity", type=int, default=5)


def service_configuration_from_args(args: argparse.Namespace) -> dict[str, Any]:
    raw = {
        "ctx": args.context_size,
        "parallel": args.parallel_slots,
        "batch": args.batch_size,
        "ubatch": args.ubatch_size,
        "flash_attn": args.flash_attn,
        "gpu_layers": args.gpu_layers,
        "cache_type_k": args.cache_type_k,
        "cache_type_v": args.cache_type_v,
        "log_verbosity": args.log_verbosity,
    }
    configuration = normalize_service_configuration(raw, "service configuration")
    experiment = str(args.experiment)
    if not experiment or len(experiment) > 48 or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
        for character in experiment
    ):
        raise ValueError("experiment has an invalid evidence format")
    return {"experiment": experiment, **configuration}


def normalize_service_configuration(value: Any, label: str) -> dict[str, int | str]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = sorted(set(value) - set(SERVICE_CONFIGURATION_FIELDS) - {"experiment"})
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {unknown}")
    normalized: dict[str, int | str] = dict(SERVICE_CONFIGURATION_DEFAULTS)
    for field in SERVICE_CONFIGURATION_FIELDS:
        if field in value:
            normalized[field] = value[field]
    for field in INTEGER_SERVICE_FIELDS:
        item = normalized[field]
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValueError(f"{label}.{field} must be a positive integer")
    flash_attn = normalized["flash_attn"]
    if flash_attn not in {"auto", "on", "off"}:
        raise ValueError(f"{label}.flash_attn must be auto, on, or off")
    for field in ("cache_type_k", "cache_type_v"):
        item = normalized[field]
        if not isinstance(item, str) or not item or len(item) > 32:
            raise ValueError(f"{label}.{field} has an invalid format")
        if any(not (character.isalnum() or character in {"_", "-"}) for character in item):
            raise ValueError(f"{label}.{field} has an invalid format")
    return normalized


def normalized_report_service_configuration(
    report: dict[str, Any], label: str
) -> dict[str, int | str]:
    return normalize_service_configuration(report.get("service_configuration"), label)


def service_configuration_sha256(value: Any, label: str) -> str:
    """Hash the effective llama-server tuning profile, excluding experiment labels."""

    normalized = normalize_service_configuration(value, label)
    canonical = json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def service_configuration_matches_log(
    report_configuration: dict[str, int | str],
    log_configuration: dict[str, str],
) -> bool:
    """Compare typed report fields with the launcher's textual evidence."""

    for field, value in report_configuration.items():
        if field not in log_configuration:
            return False
        if str(value) != log_configuration[field]:
            return False
    return True


def changed_tunable_groups(
    baseline_request: dict[str, Any],
    optimized_request: dict[str, Any],
    baseline_service: dict[str, Any],
    optimized_service: dict[str, Any],
) -> list[str]:
    changed: list[str] = []
    covered: set[tuple[str, str]] = set()
    for group, fields in TUNABLE_CONFIGURATION_GROUPS.items():
        if any(
            (baseline_request if scope == "request" else baseline_service).get(field)
            != (optimized_request if scope == "request" else optimized_service).get(field)
            for scope, field in fields
        ):
            changed.append(group)
        covered.update(fields)
    all_fields = {
        ("request", field)
        for field in set(baseline_request) | set(optimized_request)
    }
    all_fields.update(
        ("service", field)
        for field in set(baseline_service) | set(optimized_service)
    )
    unexpected = sorted(
        f"{scope}.{field}"
        for scope, field in all_fields - covered
        if (baseline_request if scope == "request" else baseline_service).get(field)
        != (optimized_request if scope == "request" else optimized_service).get(field)
    )
    if unexpected:
        raise ValueError(
            "Baseline and optimized reports differ in fixed configuration fields: "
            f"{unexpected}"
        )
    return changed


def validate_percent(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > 100:
        raise ValueError(f"{label} must be greater than 0 and at most 100")
    return number
