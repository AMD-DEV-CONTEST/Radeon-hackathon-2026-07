#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
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


os.environ["MEM0_TELEMETRY"] = "False"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

MANIFEST = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/mem0"
OLLAMA_URL = "http://127.0.0.1:11434"
LLM_MODEL = "qwen2.5-coder:1.5b"
EMBED_MODEL = "bge-m3:latest"
EMBED_DIMS = 1024
TENANT_A = "prooflaunch-tenant-alpha"
TENANT_B = "prooflaunch-tenant-beta"
AGENT_ID = "prooflaunch-gtm-employee"


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump())
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


def result_rows(operation: dict[str, Any]) -> list[dict[str, Any]]:
    result = operation.get("result")
    if isinstance(result, dict) and isinstance(result.get("results"), list):
        return [row for row in result["results"] if isinstance(row, dict)]
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(OUTPUT))
    args = parser.parse_args()
    output = Path(args.output_dir).expanduser().resolve()
    output.relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    output.mkdir(parents=True, mode=0o700)
    state = output / "private-state"
    state.mkdir(mode=0o700)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    slot = next(
        row for row in manifest["capture_slots"]
        if row["category_id"] == "cross_device_memory" and row["reference_product"] == "Mem0"
    )

    from mem0 import Memory
    from ollama import Client

    ollama = Client(host=OLLAMA_URL, trust_env=False)
    local_models = json_safe(ollama.list()).get("models", [])
    model_records = {
        str(row.get("model") or row.get("name")): row
        for row in local_models if isinstance(row, dict)
    }
    if LLM_MODEL not in model_records or EMBED_MODEL not in model_records:
        raise SystemExit("required Ollama models are not already local; refusing to pull")
    probe = ollama.embed(model=EMBED_MODEL, input="ProofLaunch evidence boundary")
    actual_dims = len(probe.get("embeddings", [[]])[0])
    if actual_dims != EMBED_DIMS:
        raise SystemExit(f"embedding dimension drift: expected {EMBED_DIMS}, got {actual_dims}")

    config = {
        "version": "v1.1",
        "history_db_path": str(state / "history.sqlite"),
        "custom_instructions": (
            "Store only durable, explicitly approved GTM facts and evidence boundaries. "
            "Preserve channel, audience, temporal revision and prohibited-claim wording exactly. "
            "When a newer approved fact contradicts an older one, retain the newer active fact. "
            "Do not invent performance, virality, conversion or revenue evidence."
        ),
        "llm": {
            "provider": "ollama",
            "config": {
                "model": LLM_MODEL,
                "ollama_base_url": OLLAMA_URL,
                "temperature": 0.0,
                "max_tokens": 1200,
                "top_p": 0.1,
                "top_k": 1,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": EMBED_MODEL,
                "ollama_base_url": OLLAMA_URL,
                "embedding_dims": EMBED_DIMS,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "prooflaunch_mem0_named_pk_v1",
                "path": str(state / "qdrant"),
                "embedding_model_dims": EMBED_DIMS,
                "on_disk": True,
            },
        },
    }
    memory = Memory.from_config(config)
    desktop_fact = (
        "APPROVED 2026-08-03T13:00:00Z. ProofLaunch serves founders and growth leaders. "
        "The primary launch channel is LinkedIn. Evidence boundary: never claim virality, conversion, "
        "revenue, 4A quality, or named-product superiority without observed evidence."
    )
    mobile_update = (
        "APPROVED UPDATE 2026-08-03T14:00:00Z. For the current 15-second Claim Trial test, "
        "the primary launch channel is YouTube Shorts, replacing LinkedIn. The evidence boundary remains: "
        "never claim virality, conversion, revenue, 4A quality, or named-product superiority without observed evidence."
    )
    operations: list[dict[str, Any]] = []
    desktop_add = call("desktop_add_approved_fact", lambda: memory.add(
        desktop_fact,
        user_id=TENANT_A,
        agent_id=AGENT_ID,
        metadata={
            "source_id": "desktop-approved-learning-001",
            "source_device": "desktop",
            "approved_at": "2026-08-03T13:00:00Z",
            "authority": "human_approved",
        },
        infer=False,
    ))
    operations.append(desktop_add)
    desktop_memory_ids = [str(row.get("id")) for row in result_rows(desktop_add) if row.get("id")]
    desktop_memory_id = desktop_memory_ids[0] if desktop_memory_ids else ""
    operations.append(call("mobile_search_before_update", lambda: memory.search(
        "What is the approved primary launch channel and which outcome claims are forbidden?",
        filters={"user_id": TENANT_A, "agent_id": AGENT_ID},
        top_k=20,
        threshold=0.05,
        explain=True,
    )))
    def apply_mobile_update() -> Any:
        if not desktop_memory_id:
            raise RuntimeError("desktop approved memory was not created")
        return memory.update(
            desktop_memory_id,
            text=mobile_update,
            metadata={
                "source_id": "mobile-approved-learning-002",
                "source_device": "mobile",
                "approved_at": "2026-08-03T14:00:00Z",
                "supersedes": "desktop-approved-learning-001:primary_channel",
                "authority": "human_approved",
            },
        )

    operations.append(call("mobile_explicit_approved_update", apply_mobile_update))
    operations.append(call("desktop_search_after_update", lambda: memory.search(
        "What is the current primary channel for the Claim Trial and what evidence boundary still applies?",
        filters={"user_id": TENANT_A, "agent_id": AGENT_ID},
        top_k=20,
        threshold=0.05,
        explain=True,
    )))
    operations.append(call("tenant_b_isolation_search", lambda: memory.search(
        "What is the current primary channel for the Claim Trial?",
        filters={"user_id": TENANT_B, "agent_id": AGENT_ID},
        top_k=20,
        threshold=0.05,
        explain=True,
    )))
    operations.append(call("tenant_a_get_all_before_delete", lambda: memory.get_all(
        filters={"user_id": TENANT_A, "agent_id": AGENT_ID},
        top_k=100,
    )))
    before_delete = operations[-1]
    memory_ids = [str(row.get("id")) for row in result_rows(before_delete) if row.get("id")]
    histories = []
    for memory_id in memory_ids:
        histories.append(call(f"history_{memory_id}", lambda memory_id=memory_id: memory.history(memory_id)))
    operations.extend(histories)
    operations.append(call("tenant_a_delete_all", lambda: memory.delete_all(user_id=TENANT_A, agent_id=AGENT_ID)))
    operations.append(call("tenant_a_get_all_after_delete", lambda: memory.get_all(
        filters={"user_id": TENANT_A, "agent_id": AGENT_ID},
        top_k=100,
    )))
    operations.append(call("tenant_b_get_all_after_tenant_a_delete", lambda: memory.get_all(
        filters={"user_id": TENANT_B, "agent_id": AGENT_ID},
        top_k=100,
    )))

    raw = {
        "schema": "ProofLaunchMem0NamedProductRawRunV1",
        "frozen_task": slot["reference_capability"],
        "task": "Carry one approved insight across desktop and mobile, resolve a newer contradictory fact, expose provenance, then delete it exactly.",
        "requests": {
            "desktop_fact": desktop_fact,
            "mobile_update": mobile_update,
            "tenant_a": TENANT_A,
            "tenant_b": TENANT_B,
            "agent_id": AGENT_ID,
        },
        "operations": operations,
        "raw_product_output_unedited": True,
        "external_network_calls": 0,
        "conflict_resolution_mode": "explicit_update_from_newer_human_approved_event",
    }
    artifact = output / "mem0-raw-baseline.json"
    atomic_write_text(artifact, json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    before_rows = result_rows(before_delete)
    after_rows = result_rows(operations[-2])
    tenant_b_rows = result_rows(operations[4])
    after_update_text = json.dumps(operations[3].get("result"), ensure_ascii=False).lower()
    provenance_present = any(
        isinstance(row.get("metadata"), dict) and row["metadata"].get("source_id")
        for row in before_rows
    )
    evaluation = {
        "all_operations_succeeded": all(row["ok"] for row in operations),
        "memory_count_before_delete": len(before_rows),
        "memory_count_after_delete": len(after_rows),
        "tenant_b_search_result_count": len(tenant_b_rows),
        "newer_channel_retrieved": "youtube shorts" in after_update_text,
        "stale_channel_asserted_as_current": "primary launch channel is linkedin" in after_update_text,
        "evidence_boundary_retrieved": any(term in after_update_text for term in ("virality", "conversion", "revenue")),
        "source_provenance_present": provenance_present,
        "exact_deletion_observed": len(before_rows) > 0 and len(after_rows) == 0,
        "tenant_isolation_observed": len(tenant_b_rows) == 0,
    }
    provenance = {
        "schema": "ProofLaunchMem0NamedProductProvenanceV1",
        "capture_slot_id": slot["capture_slot_id"],
        "reference_product": "Mem0",
        "mem0_version": importlib.metadata.version("mem0ai"),
        "qdrant_client_version": importlib.metadata.version("qdrant-client"),
        "ollama_client_version": importlib.metadata.version("ollama"),
        "llm_model": LLM_MODEL,
        "llm_model_record": model_records[LLM_MODEL],
        "embedding_model": EMBED_MODEL,
        "embedding_model_record": model_records[EMBED_MODEL],
        "embedding_dimensions": actual_dims,
        "offline_except_localhost": True,
        "telemetry_disabled": True,
        "post_editing_performed": False,
        "memory_write_mode": "infer_false_verbatim_approved_fact",
        "conflict_resolution_mode": "explicit_update_from_newer_human_approved_event",
        "evaluation": evaluation,
        "artifact": {"name": artifact.name, "sha256": sha256_file(artifact), "bytes": artifact.stat().st_size},
        "truth_boundary": (
            "This is one local Mem0 OSS run using the declared Ollama models and embedded Qdrant store. "
            "It is a same-task baseline, not a claim about Mem0 Cloud, all Mem0 deployments, human preference, "
            "cross-device transport outside this simulated device handoff, or market effect."
        ),
    }
    atomic_write_text(output / "provenance.json", json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if not evaluation["all_operations_succeeded"] or evaluation["memory_count_before_delete"] == 0:
        shutil.rmtree(state)
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
        "provider_model_or_version": f"Mem0 OSS {provenance['mem0_version']} / {LLM_MODEL} / {EMBED_MODEL}",
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
    shutil.rmtree(state)
    print(json.dumps({
        "artifact": str(artifact),
        "capture_slot_id": slot["capture_slot_id"],
        "evaluation": evaluation,
        "sha256": sha256_file(artifact),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
