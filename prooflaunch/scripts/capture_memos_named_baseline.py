#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
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
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/memos"
OLLAMA_URL = "http://127.0.0.1:11434"
LLM_MODEL = "qwen2.5-coder:1.5b"
EMBED_MODEL = "bge-m3:latest"
EMBED_DIMS = 1024
TENANT_A = "prooflaunch-tenant-alpha"
TENANT_B = "prooflaunch-tenant-beta"
MEMORY_ID = "11111111-1111-4111-8111-111111111111"


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
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if isinstance(result, dict) and isinstance(result.get("results"), list):
        return [row for row in result["results"] if isinstance(row, dict)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(OUTPUT))
    parser.add_argument("--memos-source", default="/private/tmp/prooflaunch-memos-v2.0.17")
    parser.add_argument("--deps-dir", default="/private/tmp/prooflaunch-memos-deps")
    args = parser.parse_args()
    output = Path(args.output_dir).expanduser().resolve()
    output.relative_to(ROOT)
    memos_source = Path(args.memos_source).expanduser().resolve()
    deps_dir = Path(args.deps_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    if not (memos_source / "src/memos/__init__.py").is_file() or not deps_dir.is_dir():
        raise SystemExit("MemOS source or isolated dependency directory is missing")
    output.mkdir(parents=True, mode=0o700)
    state = output / "private-state"
    state.mkdir(mode=0o700)
    os.environ["MEMOS_BASE_PATH"] = str(state / "runtime")
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    sys.path.insert(0, str(memos_source / "src"))
    sys.path.insert(0, str(deps_dir))

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    slot = next(
        row for row in manifest["capture_slots"]
        if row["category_id"] == "cross_device_memory" and row["reference_product"] == "MemOS"
    )

    from ollama import Client
    from memos import __version__ as memos_version
    from memos.configs.memory import MemoryConfigFactory
    from memos.memories.factory import MemoryFactory

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

    def memory_for(tenant: str):
        config = MemoryConfigFactory(
            backend="general_text",
            config={
                "extractor_llm": {
                    "backend": "ollama",
                    "config": {
                        "model_name_or_path": LLM_MODEL,
                        "api_base": OLLAMA_URL,
                        "temperature": 0.0,
                        "top_p": 0.1,
                        "top_k": 1,
                        "max_tokens": 1200,
                    },
                },
                "vector_db": {
                    "backend": "qdrant",
                    "config": {
                        "collection_name": f"prooflaunch_memos_{tenant}",
                        "path": str(state / f"qdrant-{tenant}"),
                        "distance_metric": "cosine",
                        "vector_dimension": EMBED_DIMS,
                    },
                },
                "embedder": {
                    "backend": "ollama",
                    "config": {
                        "model_name_or_path": EMBED_MODEL,
                        "api_base": OLLAMA_URL,
                    },
                },
            },
        )
        return MemoryFactory.from_config(config)

    tenant_a = memory_for("tenant_alpha")
    tenant_b = memory_for("tenant_beta")
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
    desktop_item = {
        "id": MEMORY_ID,
        "memory": desktop_fact,
        "metadata": {
            "user_id": TENANT_A,
            "session_id": "desktop-session-001",
            "source": "conversation",
            "visibility": "private",
            "updated_at": "2026-08-03T13:00:00Z",
            "info": {
                "source_id": "desktop-approved-learning-001",
                "source_device": "desktop",
                "authority": "human_approved",
            },
        },
    }
    mobile_item = {
        "id": MEMORY_ID,
        "memory": mobile_update,
        "metadata": {
            "user_id": TENANT_A,
            "session_id": "mobile-session-002",
            "source": "conversation",
            "visibility": "private",
            "updated_at": "2026-08-03T14:00:00Z",
            "covered_history": "desktop-approved-learning-001:primary_channel",
            "info": {
                "source_id": "mobile-approved-learning-002",
                "source_device": "mobile",
                "authority": "human_approved",
                "supersedes": "desktop-approved-learning-001:primary_channel",
            },
        },
    }
    operations: list[dict[str, Any]] = []
    operations.append(call("desktop_add_approved_fact", lambda: tenant_a.add([desktop_item])))
    operations.append(call("desktop_get_after_add", lambda: tenant_a.get(MEMORY_ID)))
    operations.append(call("mobile_search_before_update", lambda: tenant_a.search(
        "What is the approved primary launch channel and which outcome claims are forbidden?",
        top_k=10,
    )))
    operations.append(call("mobile_explicit_approved_update", lambda: tenant_a.update(MEMORY_ID, mobile_item)))
    operations.append(call("desktop_search_after_update", lambda: tenant_a.search(
        "What is the current primary channel for the Claim Trial and what evidence boundary still applies?",
        top_k=10,
    )))
    operations.append(call("tenant_b_isolation_search", lambda: tenant_b.search(
        "What is the current primary channel for the Claim Trial?",
        top_k=10,
    )))
    operations.append(call("tenant_a_get_all_before_delete", tenant_a.get_all))
    operations.append(call("tenant_a_delete_exact", lambda: tenant_a.delete([MEMORY_ID])))
    operations.append(call("tenant_a_get_all_after_delete", tenant_a.get_all))
    operations.append(call("tenant_b_get_all_after_tenant_a_delete", tenant_b.get_all))

    raw = {
        "schema": "ProofLaunchMemOSNamedProductRawRunV1",
        "frozen_task": slot["reference_capability"],
        "task": "Carry one approved insight across desktop and mobile, resolve a newer contradictory fact, expose provenance, then delete it exactly.",
        "requests": {
            "desktop_fact": desktop_fact,
            "mobile_update": mobile_update,
            "tenant_a": TENANT_A,
            "tenant_b": TENANT_B,
            "memory_id": MEMORY_ID,
        },
        "operations": operations,
        "raw_product_output_unedited": True,
        "external_network_calls": 0,
        "conflict_resolution_mode": "explicit_update_from_newer_human_approved_event",
        "tenant_isolation_mode": "separate_MemOS_general_text_memory_collections",
    }
    artifact = output / "memos-raw-baseline.json"
    atomic_write_text(artifact, json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    before_rows = result_rows(operations[6])
    after_rows = result_rows(operations[8])
    tenant_b_search_rows = result_rows(operations[5])
    after_update_text = json.dumps(operations[4].get("result"), ensure_ascii=False).lower()
    source_provenance_present = any(
        isinstance(row.get("metadata"), dict)
        and isinstance(row["metadata"].get("info"), dict)
        and row["metadata"]["info"].get("source_id") == "mobile-approved-learning-002"
        for row in before_rows
    )
    evaluation = {
        "all_operations_succeeded": all(row["ok"] for row in operations),
        "memory_count_before_delete": len(before_rows),
        "memory_count_after_delete": len(after_rows),
        "tenant_b_search_result_count": len(tenant_b_search_rows),
        "newer_channel_retrieved": "youtube shorts" in after_update_text,
        "stale_channel_asserted_as_current": "primary launch channel is linkedin" in after_update_text,
        "evidence_boundary_retrieved": any(term in after_update_text for term in ("virality", "conversion", "revenue")),
        "source_provenance_present": source_provenance_present,
        "exact_deletion_observed": len(before_rows) > 0 and len(after_rows) == 0,
        "tenant_isolation_observed": len(tenant_b_search_rows) == 0,
        "automatic_conflict_history_observed": False,
    }
    source_revision = subprocess.check_output(
        ["git", "-C", str(memos_source), "rev-parse", "HEAD"], text=True
    ).strip()
    provenance = {
        "schema": "ProofLaunchMemOSNamedProductProvenanceV1",
        "capture_slot_id": slot["capture_slot_id"],
        "reference_product": "MemOS",
        "memos_version": memos_version,
        "memos_source_revision": source_revision,
        "llm_model": LLM_MODEL,
        "llm_model_record": model_records[LLM_MODEL],
        "embedding_model": EMBED_MODEL,
        "embedding_model_record": model_records[EMBED_MODEL],
        "embedding_dimensions": actual_dims,
        "offline_except_localhost": True,
        "post_editing_performed": False,
        "memory_write_mode": "verbatim_human_approved_fact",
        "conflict_resolution_mode": "explicit_update_from_newer_human_approved_event",
        "tenant_isolation_mode": "separate_MemOS_general_text_memory_collections",
        "known_limitations": [
            "This run exercises MemOS GeneralTextMemory, not the full MemOS server, scheduler, graph memory or cloud product.",
            "The explicit update preserved a supersedes pointer in metadata; GeneralTextMemory did not expose an automatic version-history record in this run.",
            "Desktop/mobile are simulated handoff events against one local process, not physical cross-device transport.",
        ],
        "evaluation": evaluation,
        "artifact": {"name": artifact.name, "sha256": sha256_file(artifact), "bytes": artifact.stat().st_size},
        "truth_boundary": (
            "This is one local MemOS OSS GeneralTextMemory run using the declared Ollama models and embedded Qdrant stores. "
            "It is a same-task baseline, not a claim about MemOS Cloud, full MemOS, human preference, physical cross-device transport or market effect."
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
        "provider_model_or_version": f"MemOS OSS {memos_version} {source_revision[:12]} / {LLM_MODEL} / {EMBED_MODEL}",
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
