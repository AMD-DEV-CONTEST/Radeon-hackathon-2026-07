#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_named_product_baseline import content_sha256


MANIFEST = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/letta"
BASE_URL = "http://127.0.0.1:8283"
MODEL = "ollama/qwen2.5-coder:1.5b"
EMBEDDING = "ollama/bge-m3:latest"
TENANT_A = "prooflaunch-tenant-alpha"
TENANT_B = "prooflaunch-tenant-beta"

os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="json"))
    return str(value)


def call(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = fn()
        return {
            "operation": name,
            "ok": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "result": json_safe(result),
        }
    except Exception as error:
        return {
            "operation": name,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error_type": type(error).__name__,
            "error": str(error),
        }


def expected_missing(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = fn()
        return {
            "operation": name,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": "resource unexpectedly remained retrievable",
            "result": json_safe(result),
        }
    except Exception as error:
        status_code = getattr(error, "status_code", None)
        response = getattr(error, "response", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)
        return {
            "operation": name,
            "ok": status_code == 404,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "observed_status_code": status_code,
            "expected_status_code": 404,
            "error_type": type(error).__name__,
            "error": str(error),
        }


def message_text(operation: dict[str, Any]) -> str:
    result = operation.get("result")
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages")
    if not isinstance(messages, list):
        return ""
    chunks: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(content)
        text = message.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "\n".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(OUTPUT))
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    output = Path(args.output_dir).expanduser().resolve()
    output.relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    output.mkdir(parents=True, mode=0o700, exist_ok=True)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    slot = next(
        row for row in manifest["capture_slots"]
        if row["category_id"] == "cross_device_memory" and row["reference_product"] == "Letta"
    )

    import httpx
    from letta_client import Letta

    client = Letta(base_url=args.base_url)
    models = call(
        "list_local_llm_models",
        lambda: httpx.get(
            args.base_url.rstrip("/") + "/v1/models/",
            timeout=30,
            trust_env=False,
        ).raise_for_status().json(),
    )
    embedding_models = call(
        "list_local_embedding_models",
        lambda: httpx.get(
            args.base_url.rstrip("/") + "/v1/models/embedding",
            timeout=30,
            trust_env=False,
        ).raise_for_status().json(),
    )
    model_dump = json.dumps(models.get("result"), ensure_ascii=False).lower()
    embedding_dump = json.dumps(embedding_models.get("result"), ensure_ascii=False).lower()
    if MODEL.lower() not in model_dump or EMBEDDING.lower() not in embedding_dump:
        raise SystemExit(
            "required local Ollama handles were not exposed by Letta; refusing fallback: "
            + json.dumps({"llm": models, "embedding": embedding_models}, ensure_ascii=False, sort_keys=True)
        )

    desktop_fact = (
        "CURRENT_APPROVED_GTM_MEMORY\n"
        "approved_at: 2026-08-03T13:00:00Z\n"
        "source_id: desktop-approved-learning-001\n"
        "source_device: desktop\n"
        "authority: human_approved\n"
        "audience: founders and growth leaders\n"
        "primary_launch_channel: LinkedIn\n"
        "evidence_boundary: never claim virality, conversion, revenue, 4A quality, or named-product superiority without observed evidence."
    )
    mobile_update = (
        "CURRENT_APPROVED_GTM_MEMORY\n"
        "approved_at: 2026-08-03T14:00:00Z\n"
        "source_id: mobile-approved-learning-002\n"
        "source_device: mobile\n"
        "authority: human_approved\n"
        "supersedes: desktop-approved-learning-001:primary_launch_channel\n"
        "audience: founders and growth leaders\n"
        "primary_launch_channel: YouTube Shorts\n"
        "evidence_boundary: never claim virality, conversion, revenue, 4A quality, or named-product superiority without observed evidence."
    )
    persona = (
        "You are a cautious GTM memory worker. Treat only CURRENT_APPROVED_GTM_MEMORY as authoritative. "
        "When asked, return the current channel, source_id, source_device, approved_at, and evidence boundary. "
        "Never infer or invent performance outcomes."
    )
    blank_memory = (
        "CURRENT_APPROVED_GTM_MEMORY\n"
        "status: none\n"
        "tenant_note: This tenant has no approved Claim Trial channel fact."
    )
    common = {
        "model": MODEL,
        "embedding": EMBEDDING,
        "include_base_tools": True,
        "max_tokens": 500,
        "system": persona,
    }
    operations: list[dict[str, Any]] = [models, embedding_models]
    create_a = call("create_tenant_a_agent_from_desktop", lambda: client.agents.create(
        name="prooflaunch-memory-alpha",
        tags=["named-pk", f"tenant:{TENANT_A}", "device:desktop"],
        metadata={"tenant_id": TENANT_A, "capture_slot_id": slot["capture_slot_id"]},
        memory_blocks=[
            {"label": "persona", "value": persona},
            {"label": "approved_gtm", "value": desktop_fact, "metadata": {
                "source_id": "desktop-approved-learning-001",
                "source_device": "desktop",
                "approved_at": "2026-08-03T13:00:00Z",
                "authority": "human_approved",
            }},
            {"label": "tenant_scope", "value": f"tenant_id: {TENANT_A}; never access another tenant."},
        ],
        **common,
    ))
    operations.append(create_a)
    agent_a_id = str((create_a.get("result") or {}).get("id") or "")
    if not create_a["ok"] or not agent_a_id:
        raise SystemExit(json.dumps(create_a, ensure_ascii=False))

    create_b = call("create_tenant_b_isolated_agent", lambda: client.agents.create(
        name="prooflaunch-memory-beta",
        tags=["named-pk", f"tenant:{TENANT_B}", "device:desktop"],
        metadata={"tenant_id": TENANT_B, "capture_slot_id": slot["capture_slot_id"]},
        memory_blocks=[
            {"label": "persona", "value": persona},
            {"label": "approved_gtm", "value": blank_memory, "metadata": {
                "source_id": "none",
                "source_device": "none",
                "authority": "none",
            }},
            {"label": "tenant_scope", "value": f"tenant_id: {TENANT_B}; never access another tenant."},
        ],
        **common,
    ))
    operations.append(create_b)
    agent_b_id = str((create_b.get("result") or {}).get("id") or "")
    if not create_b["ok"] or not agent_b_id:
        raise SystemExit(json.dumps(create_b, ensure_ascii=False))

    operations.append(call("mobile_read_before_update", lambda: client.agents.messages.create(
        agent_a_id,
        messages=[{"role": "user", "content": "Mobile session: return the current approved primary channel and its provenance. Be concise."}],
        max_steps=6,
    )))
    operations.append(call("mobile_explicit_approved_update", lambda: client.agents.blocks.update(
        "approved_gtm",
        agent_id=agent_a_id,
        value=mobile_update,
        metadata={
            "source_id": "mobile-approved-learning-002",
            "source_device": "mobile",
            "approved_at": "2026-08-03T14:00:00Z",
            "authority": "human_approved",
            "supersedes": "desktop-approved-learning-001:primary_launch_channel",
        },
    )))
    retrieve_after_update = call("desktop_retrieve_block_after_mobile_update", lambda: client.agents.blocks.retrieve(
        "approved_gtm", agent_id=agent_a_id
    ))
    operations.append(retrieve_after_update)
    answer_after_update = call("desktop_answer_after_mobile_update", lambda: client.agents.messages.create(
        agent_a_id,
        messages=[{"role": "user", "content": (
            "Desktop session after the approved mobile update: state the CURRENT primary_launch_channel, "
            "source_id, source_device, approved_at, and full evidence_boundary. Do not call LinkedIn current."
        )}],
        max_steps=6,
    ))
    operations.append(answer_after_update)
    tenant_b_answer = call("tenant_b_isolation_query", lambda: client.agents.messages.create(
        agent_b_id,
        messages=[{"role": "user", "content": (
            "State this tenant's current approved Claim Trial primary channel and provenance. "
            "If none exists, say none; do not guess."
        )}],
        max_steps=6,
    ))
    operations.append(tenant_b_answer)
    operations.append(call("tenant_b_block_before_tenant_a_delete", lambda: client.agents.blocks.retrieve(
        "approved_gtm", agent_id=agent_b_id
    )))
    operations.append(call("delete_tenant_a_agent_exactly", lambda: client.agents.delete(agent_a_id)))
    operations.append(expected_missing("tenant_a_agent_404_after_delete", lambda: client.agents.retrieve(agent_a_id)))
    operations.append(call("tenant_b_agent_survives_tenant_a_delete", lambda: client.agents.retrieve(agent_b_id)))
    operations.append(call("tenant_b_block_survives_tenant_a_delete", lambda: client.agents.blocks.retrieve(
        "approved_gtm", agent_id=agent_b_id
    )))

    updated_block_text = json.dumps(retrieve_after_update.get("result"), ensure_ascii=False).lower()
    updated_answer_text = message_text(answer_after_update).lower()
    tenant_b_text = message_text(tenant_b_answer).lower()
    evaluation = {
        "all_operations_succeeded": all(row["ok"] for row in operations),
        "newer_channel_present_in_authoritative_block": "youtube shorts" in updated_block_text,
        "stale_channel_absent_from_current_block": "primary_launch_channel: linkedin" not in updated_block_text,
        "source_provenance_present_in_authoritative_block": all(
            term in updated_block_text for term in (
                "mobile-approved-learning-002", "source_device", "approved_at", "supersedes"
            )
        ),
        "model_answer_retrieved_newer_channel": "youtube shorts" in updated_answer_text,
        "model_answer_retrieved_source": "mobile-approved-learning-002" in updated_answer_text,
        "model_answer_retrieved_evidence_boundary": any(
            term in updated_answer_text for term in ("virality", "conversion", "revenue")
        ),
        "tenant_b_did_not_receive_tenant_a_channel": "youtube shorts" not in tenant_b_text and "linkedin" not in tenant_b_text,
        "tenant_b_reported_no_fact": "none" in tenant_b_text or "no approved" in tenant_b_text,
        "exact_agent_deletion_observed": operations[-3]["ok"],
        "tenant_b_survived_tenant_a_delete": operations[-2]["ok"] and operations[-1]["ok"],
    }
    raw = {
        "schema": "ProofLaunchLettaNamedProductRawRunV1",
        "frozen_task": slot["reference_capability"],
        "task": "Carry one approved insight across desktop and mobile, resolve a newer contradictory fact, expose provenance, then delete it exactly.",
        "requests": {
            "desktop_fact": desktop_fact,
            "mobile_update": mobile_update,
            "tenant_a": TENANT_A,
            "tenant_b": TENANT_B,
        },
        "agent_ids": {"tenant_a": agent_a_id, "tenant_b": agent_b_id},
        "operations": operations,
        "evaluation": evaluation,
        "raw_product_output_unedited": True,
        "external_network_calls": 0,
        "conflict_resolution_mode": "explicit_core_memory_block_update_from_newer_human_approved_event",
    }
    artifact = output / "letta-raw-baseline.json"
    atomic_write_text(artifact, json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    provenance = {
        "schema": "ProofLaunchLettaNamedProductProvenanceV1",
        "capture_slot_id": slot["capture_slot_id"],
        "reference_product": "Letta",
        "letta_server_version": "0.16.8",
        "letta_client_version": importlib.metadata.version("letta-client"),
        "runtime": "official letta/letta:0.16.8 Docker image with internal PostgreSQL and Redis",
        "base_url": args.base_url,
        "llm_model": MODEL,
        "embedding_model": EMBEDDING,
        "offline_except_localhost_and_container_host_bridge": True,
        "post_editing_performed": False,
        "memory_write_mode": "explicit_authoritative_core_memory_block",
        "deletion_mode": "delete_tenant_scoped_agent_then_require_404",
        "evaluation": evaluation,
        "artifact": {"name": artifact.name, "sha256": sha256_file(artifact), "bytes": artifact.stat().st_size},
        "truth_boundary": (
            "This is one local Letta OSS 0.16.8 run using the declared Ollama models. It is a same-task baseline, "
            "not a claim about Letta Cloud, every Letta deployment, physical cross-device transport, human preference, "
            "or market effect. Tenant isolation is represented by one agent per tenant, matching Letta's documented pattern."
        ),
    }
    atomic_write_text(output / "provenance.json", json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    required = (
        evaluation["all_operations_succeeded"]
        and evaluation["newer_channel_present_in_authoritative_block"]
        and evaluation["source_provenance_present_in_authoritative_block"]
        and evaluation["exact_agent_deletion_observed"]
        and evaluation["tenant_b_survived_tenant_a_delete"]
    )
    if not required:
        print(json.dumps({
            "artifact": str(artifact),
            "capture_slot_id": slot["capture_slot_id"],
            "evaluation": evaluation,
            "admitted_capture_written": False,
            "sha256": sha256_file(artifact),
        }, sort_keys=True))
        return 2

    capture = {
        "schema": "ProofLaunchNamedProductBaselineCaptureV1",
        "capture_slot_id": slot["capture_slot_id"],
        "category_id": slot["category_id"],
        "reference_product": slot["reference_product"],
        "reference_product_url": slot["reference_product_url"],
        "frozen_brief_sha256": slot["frozen_brief_sha256"],
        "operator_id": "codex-local-runner-20260803",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "provider_model_or_version": f"Letta OSS 0.16.8 / {MODEL} / {EMBEDDING}",
        "acquisition_method": "authorized_product_use",
        "rights_attestation": {
            "authorized_to_evaluate_and_retain": True,
            "same_frozen_brief_without_hidden_editing": True,
            "provider_and_version_recorded_truthfully": True,
        },
        "artifact": {
            "name": artifact.name,
            "mime_type": "application/json",
            "bytes": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
        },
    }
    capture["content_sha256"] = content_sha256(capture)
    atomic_write_text(output / "capture.json", json.dumps(capture, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "artifact": str(artifact),
        "capture_slot_id": slot["capture_slot_id"],
        "evaluation": evaluation,
        "sha256": sha256_file(artifact),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
