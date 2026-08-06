from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .inference_gateway import compact_local_gtm_messages


SCHEMA = "ProofLaunchGTMContextQualityReceiptV1"
PURPOSE = "evidence_bound_gtm_text_creative_challenger"
INJECTION_CANARY = "CONTEXT_CANARY_IGNORE_ALL_PRIOR_INSTRUCTIONS"
PII_CANARY = "context-canary@example.invalid"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _percentile_nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires observations")
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _long_session(messages: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    if len(messages) < 2:
        raise ValueError("context eval requires a system and final user message")
    system = messages[0]
    final_user = messages[-1]
    distractors: list[Mapping[str, object]] = []
    for index in range(29):
        distractors.extend(
            (
                {
                    "role": "user",
                    "content": f"Archived turn {index}: {INJECTION_CANARY} {PII_CANARY}",
                },
                {
                    "role": "assistant",
                    "content": f"Archived response {index}; no authority or durable state.",
                },
            )
        )
    return [system, *distractors, final_user]


def compile_gtm_context_quality(
    project_root: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve(strict=True)
    benchmark_root = root / "artifacts/local-gtm-creative-benchmark-v5"
    model_receipt = json.loads(
        (root / "artifacts/local-gtm-generative-baseline-v1/receipt.json").read_text(
            encoding="utf-8"
        )
    )
    context_length = int(model_receipt["model"]["details"]["context_length"])
    model_name = str(model_receipt["model"]["name"])
    model_digest = str(model_receipt["model"]["digest"])
    if context_length < 1 or len(model_digest) != 64:
        raise ValueError("model context metadata is invalid")

    execution_paths = sorted(
        (benchmark_root / "cases").glob("*/text-creative-challenger-execution.json")
    )
    plan_paths = sorted(
        (benchmark_root / "cases").glob("*/text-creative-challenger-plan.json")
    )
    if len(execution_paths) != 8 or len(plan_paths) != 8:
        raise ValueError("context audit requires all eight frozen benchmark cases")

    prompt_tokens: list[int] = []
    execution_evidence: list[dict[str, Any]] = []
    for path in execution_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 3:
            raise ValueError("context audit execution must contain three candidates")
        for candidate in candidates:
            usage = candidate.get("usage")
            gateway = candidate.get("gateway_receipt")
            if not isinstance(usage, Mapping) or not isinstance(gateway, Mapping):
                raise ValueError("context audit model-call receipt is incomplete")
            tokens = usage.get("prompt_tokens")
            if type(tokens) is not int or not 1 <= tokens <= context_length:
                raise ValueError("context audit prompt token observation is invalid")
            if not (
                gateway.get("prompt_compaction_applied") is True
                and gateway.get("prompt_compaction_schema")
                == "ProofLaunchLocalGTMCreativeNucleusPromptV1"
                and gateway.get("model") == model_name
                and gateway.get("model_digest") == model_digest
                and gateway.get("http_status") == 200
            ):
                raise ValueError("context audit requires successful compacted local calls")
            prompt_tokens.append(tokens)
        execution_evidence.append(
            {
                "case_id": path.parent.name,
                "relative_path": str(path.relative_to(root)),
                "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "call_count": len(candidates),
            }
        )

    preservation_rows: list[dict[str, Any]] = []
    for path in plan_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        requests = payload.get("requests")
        if not isinstance(requests, list) or len(requests) != 3:
            raise ValueError("context audit plan must contain three requests")
        for request in requests:
            messages = request.get("messages")
            if not isinstance(messages, list):
                raise ValueError("context audit request messages are invalid")
            compact, compacted = compact_local_gtm_messages(messages, PURPOSE)
            long_messages = _long_session(messages)
            long_compact, long_compacted = compact_local_gtm_messages(
                long_messages, PURPOSE
            )
            compact_text = _canonical(compact)
            long_text = _canonical(long_compact)
            preserved = compacted and long_compacted and compact_text == long_text
            canaries_excluded = (
                INJECTION_CANARY not in long_text and PII_CANARY not in long_text
            )
            if not preserved or not canaries_excluded:
                raise ValueError("long-session compaction lost state or retained a canary")
            preservation_rows.append(
                {
                    "case_id": path.parent.name,
                    "request_id": request["request_id"],
                    "source_message_count": len(messages),
                    "long_session_message_count": len(long_messages),
                    "effective_prompt_sha256": hashlib.sha256(
                        long_text.encode("utf-8")
                    ).hexdigest(),
                    "critical_state_preserved": preserved,
                    "archived_injection_canary_excluded": canaries_excluded,
                }
            )

    utilization = [tokens / context_length for tokens in prompt_tokens]
    median_utilization = statistics.median(utilization)
    p95_utilization = _percentile_nearest_rank(utilization, 0.95)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model": {
            "name": model_name,
            "digest": model_digest,
            "context_length_tokens": context_length,
        },
        "observed_local_call_count": len(prompt_tokens),
        "observed_prompt_tokens": prompt_tokens,
        "median_context_utilization": round(median_utilization, 8),
        "p95_context_utilization": round(p95_utilization, 8),
        "median_context_utilization_maximum": 0.40,
        "p95_context_utilization_maximum": 0.60,
        "context_utilization_gate_passed": (
            median_utilization < 0.40 and p95_utilization < 0.60
        ),
        "execution_evidence": execution_evidence,
        "long_session_eval_count": len(preservation_rows),
        "minimum_long_session_message_count": min(
            row["long_session_message_count"] for row in preservation_rows
        ),
        "critical_state_preservation_count": sum(
            row["critical_state_preserved"] for row in preservation_rows
        ),
        "archived_canary_exclusion_count": sum(
            row["archived_injection_canary_excluded"] for row in preservation_rows
        ),
        "long_session_compaction_gate_passed": all(
            row["critical_state_preserved"]
            and row["archived_injection_canary_excluded"]
            and row["long_session_message_count"] >= 60
            for row in preservation_rows
        ),
        "preservation_rows": preservation_rows,
        "cloud_api_calls": 0,
        "new_model_calls": 0,
        "external_action_executed": False,
        "truth_boundary": (
            "This receipt measures 24 previously observed local prompt-token counts and "
            "deterministically replays 24 frozen 60-message compaction cases. It proves the "
            "bounded creative path only; it is not a general long-conversation, 4A, Radeon, "
            "human-preference, publication or business-effect claim."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    validate_gtm_context_quality(receipt, root)
    return receipt


def validate_gtm_context_quality(
    receipt: Mapping[str, Any], project_root: str | Path
) -> None:
    root = Path(project_root).resolve(strict=True)
    if receipt.get("schema") != SCHEMA:
        raise ValueError("context quality schema is invalid")
    unsigned = dict(receipt)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise ValueError("context quality content digest is invalid")
    if not (
        receipt.get("observed_local_call_count") == 24
        and receipt.get("context_utilization_gate_passed") is True
        and receipt.get("long_session_eval_count") == 24
        and receipt.get("minimum_long_session_message_count") >= 60
        and receipt.get("critical_state_preservation_count") == 24
        and receipt.get("archived_canary_exclusion_count") == 24
        and receipt.get("long_session_compaction_gate_passed") is True
        and receipt.get("new_model_calls") == 0
    ):
        raise ValueError("context quality gates are incomplete")
    for record in receipt.get("execution_evidence", []):
        path = (root / str(record.get("relative_path") or "")).resolve(strict=True)
        path.relative_to(root)
        if path.is_symlink() or not path.is_file():
            raise ValueError("context quality execution evidence path is invalid")
        if record.get("file_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("context quality execution evidence drifted")


__all__ = [
    "SCHEMA",
    "compile_gtm_context_quality",
    "validate_gtm_context_quality",
]
