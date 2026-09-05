#!/usr/bin/env python3
"""Generate or check isolated E4/M3 preparation contracts and public examples."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.experience_asset.domain.m3 import (  # noqa: E402
    DecisionEvidenceLedgerV1,
    M3FailureV1,
    M3ProgressV1,
    M3WorkspaceV1,
)
from app.experience_asset.domain.models import model_json_schema  # noqa: E402
from app.experience_asset.workflow.m3_graph import (  # noqa: E402
    M3_MAX_OUTPUT_TOKENS,
    M3_MODEL_TIMEOUT_SECONDS,
)
from app.experience_asset.workflow.m3_state import (  # noqa: E402
    M3_GRAPH_EDGES,
    M3_GRAPH_NODES,
    M3_GRAPH_STATE_ALLOWED_KEYS,
    M3_MODEL_CALL_BUDGET,
    M3_NODE_RETRY_BUDGET,
    M3_REPLAN_BUDGET,
    M3_STRUCTURED_REPAIR_BUDGET,
    M3_TOPOLOGY_HASH,
    M3_WORKFLOW_VERSION,
)

CONTRACT_DIR = ROOT / "contracts"

IDS = {
    "artifact": "00000000-0000-4000-8000-000000000801",
    "asset": "00000000-0000-4000-8000-000000000802",
    "m2_artifact": "00000000-0000-4000-8000-000000000803",
    "canonical_version": "00000000-0000-4000-8000-000000000804",
    "run": "00000000-0000-4000-8000-000000000805",
    "decision": "00000000-0000-4000-8000-000000000806",
    "moment": "00000000-0000-4000-8000-000000000810",
    "source_alternative": "00000000-0000-4000-8000-000000000820",
    "source_reason": "00000000-0000-4000-8000-000000000821",
    "source_decision": "00000000-0000-4000-8000-000000000822",
    "source_action": "00000000-0000-4000-8000-000000000823",
    "source_result": "00000000-0000-4000-8000-000000000824",
    "source_conflict": "00000000-0000-4000-8000-000000000825",
}

NOW = "2026-07-29T08:30:00Z"


def supported_statement(
    *,
    ordinal: int,
    role: str,
    text: str,
    source_statement_id: str,
) -> dict:
    return {
        "statement_id": f"00000000-0000-4000-8000-00000000083{ordinal}",
        "role": role,
        "text": text,
        "status": "SOURCE_FACT",
        "evidence_disposition": "SUPPORTED",
        "evidence_strength": "SELF_REPORTED",
        "confirmation": "CONFIRMED",
        "confirmed_at": NOW,
        "source_moment_ids": [IDS["moment"]],
        "source_statement_ids": [source_statement_id],
        "derived_from_statement_ids": [],
        "unresolved_reason": None,
    }


COMPLETE_STATEMENTS = [
    supported_statement(
        ordinal=0,
        role="ALTERNATIVE",
        text="继续使用网面椅并增加站立休息。",
        source_statement_id=IDS["source_alternative"],
    ),
    supported_statement(
        ordinal=1,
        role="REASON",
        text="长时间坐姿的不适没有通过短暂休息解决。",
        source_statement_id=IDS["source_reason"],
    ),
    {
        **supported_statement(
            ordinal=2,
            role="DECISION",
            text="在退换窗口内更换为软垫人体工学椅。",
            source_statement_id=IDS["source_decision"],
        ),
        "status": "USER_JUDGMENT",
    },
    supported_statement(
        ordinal=3,
        role="ACTION",
        text="提交退换申请并完成新椅安装。",
        source_statement_id=IDS["source_action"],
    ),
    supported_statement(
        ordinal=4,
        role="OBSERVED_RESULT",
        text="用户报告连续工作后的不适减少。",
        source_statement_id=IDS["source_result"],
    ),
]

COMPLETE_LEDGER = {
    "schema_version": "0.1.0",
    "artifact_id": IDS["artifact"],
    "asset_id": IDS["asset"],
    "base_m2_artifact_id": IDS["m2_artifact"],
    "base_canonical_version_id": IDS["canonical_version"],
    "generated_by_run_id": IDS["run"],
    "state": "CONFIRMED",
    "entries": [
        {
            "decision_id": IDS["decision"],
            "title": "是否在退换窗口内更换座椅",
            "source_moment_ids": [IDS["moment"]],
            "statements": COMPLETE_STATEMENTS,
        }
    ],
    "dependency_moment_ids": [IDS["moment"]],
    "dependency_statement_ids": [
        IDS["source_alternative"],
        IDS["source_reason"],
        IDS["source_decision"],
        IDS["source_action"],
        IDS["source_result"],
    ],
    "unresolved_question_ids": [],
    "created_at": NOW,
    "updated_at": NOW,
    "invalidated_by_m2_artifact_id": None,
    "invalidated_by_canonical_version_id": None,
    "invalidation_reason": None,
    "affected_entry_ids": [],
    "affected_dependency_refs": [],
    "reusable_entry_ids": [],
}

INCOMPLETE_LEDGER = deepcopy(COMPLETE_LEDGER)
INCOMPLETE_LEDGER["artifact_id"] = "00000000-0000-4000-8000-000000000841"
INCOMPLETE_LEDGER["state"] = "NEEDS_INPUT"
INCOMPLETE_LEDGER["entries"][0]["statements"][-1] = {
    "statement_id": "00000000-0000-4000-8000-000000000844",
    "role": "OBSERVED_RESULT",
    "text": "尚未提供可观察结果。",
    "status": "UNRESOLVED",
    "evidence_disposition": "UNRESOLVED",
    "evidence_strength": "NONE",
    "confirmation": "UNCONFIRMED",
    "confirmed_at": None,
    "source_moment_ids": [IDS["moment"]],
    "source_statement_ids": [],
    "derived_from_statement_ids": [],
    "unresolved_reason": "当前来源没有说明执行后的实际结果。",
}
INCOMPLETE_LEDGER["dependency_statement_ids"] = INCOMPLETE_LEDGER["dependency_statement_ids"][:-1]

CONFLICTING_LEDGER = deepcopy(COMPLETE_LEDGER)
CONFLICTING_LEDGER["artifact_id"] = "00000000-0000-4000-8000-000000000851"
CONFLICTING_LEDGER["state"] = "NEEDS_INPUT"
CONFLICTING_LEDGER["entries"][0]["statements"][1] = {
    **CONFLICTING_LEDGER["entries"][0]["statements"][1],
    "evidence_disposition": "CONFLICTING",
    "confirmation": "UNCONFIRMED",
    "confirmed_at": None,
    "source_statement_ids": [
        IDS["source_reason"],
        IDS["source_conflict"],
    ],
    "unresolved_reason": "两个来源对更换座椅的主要原因描述不一致。",
}
CONFLICTING_LEDGER["dependency_statement_ids"].append(IDS["source_conflict"])

CORRECTION_LEDGER = deepcopy(COMPLETE_LEDGER)
CORRECTION_LEDGER["artifact_id"] = "00000000-0000-4000-8000-000000000861"
CORRECTION_LEDGER["state"] = "INVALIDATED"
CORRECTION_LEDGER["updated_at"] = "2026-07-29T08:31:00Z"
CORRECTION_LEDGER["invalidated_by_m2_artifact_id"] = "00000000-0000-4000-8000-000000000862"
CORRECTION_LEDGER["invalidated_by_canonical_version_id"] = "00000000-0000-4000-8000-000000000863"
CORRECTION_LEDGER["invalidation_reason"] = (
    "M2 correction changed moment:00000000-0000-4000-8000-000000000810"
)
CORRECTION_LEDGER["affected_entry_ids"] = [IDS["decision"]]
CORRECTION_LEDGER["affected_dependency_refs"] = [f"moment:{IDS['moment']}"]

WORKSPACE_COMPLETE = {
    "artifact": COMPLETE_LEDGER,
    "is_current": True,
    "history_artifact_ids": [IDS["artifact"]],
    "evidence_moments": [
        {
            "moment_id": IDS["moment"],
            "title": "在退换窗口内重新选择座椅",
            "description": "用户比较两种座椅、完成更换并观察长期使用结果。",
        }
    ],
    "evidence_statements": [
        {
            "statement_id": IDS["source_alternative"],
            "text": "原方案是继续使用透气的网面椅并定期站立休息。",
            "source_labels": ["公开改写研究样例"],
        },
        {
            "statement_id": IDS["source_reason"],
            "text": "网面椅前缘偏硬，长时间工作时需要不断调整坐姿。",
            "source_labels": ["公开改写研究样例"],
        },
        {
            "statement_id": IDS["source_decision"],
            "text": "用户决定在退换窗口内更换为可调节的软垫人体工学椅。",
            "source_labels": ["公开改写研究样例"],
        },
        {
            "statement_id": IDS["source_action"],
            "text": "用户提交退换申请并安装了新椅子。",
            "source_labels": ["公开改写研究样例"],
        },
        {
            "statement_id": IDS["source_result"],
            "text": "试用约两周后，支撑更合适，工作时不再频繁挪动。",
            "source_labels": ["公开改写研究样例"],
        },
        {
            "statement_id": IDS["source_conflict"],
            "text": "另一处记录把外观而不是久坐不适列为主要更换原因。",
            "source_labels": ["公开改写研究样例"],
        },
    ],
    "progress": {
        "schema_version": "1.0.0",
        "stage": "TERMINAL",
        "state": "TERMINAL",
        "structured_repairs_used": 0,
        "structured_repair_budget": 2,
        "replans_used": 0,
        "replan_budget": 1,
        "model_calls_used": 1,
        "model_call_budget": 4,
        "last_durable_artifact_id": IDS["artifact"],
        "safe_message": "Decision and Evidence Ledger saved for review.",
        "occurred_at": NOW,
        "terminal_state": "SUCCEEDED",
    },
    "latest_failure": None,
    "allowed_actions": ["EDIT", "CONFIRM"],
}

WORKSPACE_POLICY_BLOCKED = {
    "artifact": INCOMPLETE_LEDGER,
    "is_current": True,
    "history_artifact_ids": [INCOMPLETE_LEDGER["artifact_id"]],
    "evidence_moments": deepcopy(WORKSPACE_COMPLETE["evidence_moments"]),
    "evidence_statements": deepcopy(WORKSPACE_COMPLETE["evidence_statements"]),
    "progress": {
        "schema_version": "1.0.0",
        "stage": "TERMINAL",
        "state": "TERMINAL",
        "structured_repairs_used": 0,
        "structured_repair_budget": 2,
        "replans_used": 0,
        "replan_budget": 1,
        "model_calls_used": 1,
        "model_call_budget": 4,
        "last_durable_artifact_id": INCOMPLETE_LEDGER["artifact_id"],
        "safe_message": "Tool execution was denied; the last saved ledger is unchanged.",
        "occurred_at": NOW,
        "terminal_state": "POLICY_BLOCKED",
    },
    "latest_failure": {
        "code": "PERMISSION_DENIED",
        "terminal_state": "POLICY_BLOCKED",
        "retryable": False,
        "safe_user_message": ("The requested local tool is not permitted for this M3 run."),
        "recovery_action": "Review the explicit permission before starting a new run.",
        "finding_codes": ["PERMISSION_NOT_GRANTED"],
        "occurred_at": NOW,
    },
    "allowed_actions": ["EDIT", "CONFIRM"],
}

NEGATIVE_SCENARIOS = {
    "schema_version": "e4-m3-negative-scenarios/v1",
    "scenarios": [
        {
            "id": "unsupported_claim",
            "input_condition": (
                "A material SOURCE_FACT has no source_statement_ids and no derivation evidence."
            ),
            "expected_behavior": "Reject before persistence and enter bounded repair.",
            "expected_terminal_if_exhausted": "INVALID_MODEL_OUTPUT",
        },
        {
            "id": "invalid_output_repairable",
            "input_condition": "The first local-model result fails the M3 schema.",
            "expected_behavior": "Repair the current node once and revalidate.",
            "expected_terminal_if_exhausted": "INVALID_MODEL_OUTPUT",
        },
        {
            "id": "invalid_output_exhausted",
            "input_condition": "Structured output remains invalid after two repairs.",
            "expected_behavior": "Attempt at most one re-plan, then safe-stop.",
            "expected_terminal_if_exhausted": "INVALID_MODEL_OUTPUT",
        },
        {
            "id": "forged_tool_call",
            "input_condition": "Model output claims permission_granted=true.",
            "expected_behavior": "Reject the proposal as inert and do not dispatch.",
            "expected_terminal_if_exhausted": "POLICY_BLOCKED",
        },
        {
            "id": "permission_denied",
            "input_condition": "A valid proposal lacks Runtime permission.",
            "expected_behavior": "Record a deterministic deny decision and do not dispatch.",
            "expected_terminal_if_exhausted": "POLICY_BLOCKED",
        },
        {
            "id": "correction_invalidation",
            "input_condition": "A new M2 artifact changes one declared M3 dependency.",
            "expected_behavior": "Invalidate only affected M3 output and require regeneration.",
            "expected_terminal_if_exhausted": "NEEDS_USER_INPUT",
        },
    ],
}

CHECKPOINT = {
    "schema_version": "e4-m3-preparation/v1",
    "status": "CHECKPOINT_2_IMPLEMENTED_W7900_EXECUTION_PREPARED",
    "scope_state": "MATERIAL_VERTICAL_SLICE_INTEGRATED",
    "owner": "Eas000n",
    "reviewer": "kinnyuww",
    "issue": 21,
    "upstream_gate": {
        "pull_request": 20,
        "merge_commit": "5c5c84f5209b2f91745924e69d55ea5290880153",
        "observed_status": "MERGED",
        "integration_audit_status": "COMPLETED_LOCAL",
    },
    "required_input": (
        "one exact accepted base_m2_artifact_id plus its current base_canonical_version_id"
    ),
    "artifact": "Decision and Evidence Ledger v0.1",
    "contracts": [
        "app/experience_asset/domain/m3.py",
        "contracts/json-schema/decision-evidence-ledger-v0.1.schema.json",
        "contracts/json-schema/m3-workspace-v1.schema.json",
        "contracts/json-schema/m3-progress-v1.schema.json",
        "contracts/json-schema/m3-failure-v1.schema.json",
    ],
    "interface_contracts": {
        "input": [
            "M3CreateRequestV1 binds exact M2 artifact and canonical version",
            "M3EditRequestV1 uses expected artifact identity and trusted user actions",
            "M3ConfirmRequestV1 makes complete-with-gaps explicit",
        ],
        "output": [
            "DecisionEvidenceLedgerV1",
            "M3WorkspaceV1 with readable evidence_moments and evidence_statements",
        ],
        "error": {
            "contract": "M3FailureV1",
            "stable_codes": [
                "UPSTREAM_STALE",
                "INVALID_MODEL_OUTPUT",
                "STRUCTURED_REPAIR_EXHAUSTED",
                "TOOL_NOT_ALLOWLISTED",
                "INVALID_TOOL_ARGUMENTS",
                "FORGED_TOOL_PERMISSION",
                "PERMISSION_DENIED",
                "STORAGE_ERROR",
                "VERIFICATION_FAILED",
                "REPLAN_EXHAUSTED",
                "MODEL_CALL_BUDGET_EXHAUSTED",
                "MODEL_UNAVAILABLE",
                "MODEL_TIMED_OUT",
                "INTERNAL_ERROR",
            ],
        },
        "progress": {
            "contract": "M3ProgressV1",
            "basis": "real workflow stage and bounded counters only",
            "forbidden": ["fabricated percentage", "fabricated ETA"],
        },
        "invalidation": (
            "invalidate only when a new M2 artifact/canonical pair changes a "
            "declared moment or statement dependency"
        ),
    },
    "quality_mapping": {
        "acceptance_criteria": [
            "AC-02",
            "AC-03",
            "AC-09",
            "AC-10",
            "AC-15",
            "AC-16",
            "AC-18",
            "AC-22",
            "AC-23",
            "AC-24",
            "AC-25",
        ],
        "l1": "M3",
        "l2": [
            "Canonical state",
            "Evidence discipline",
            "Failure behavior",
            "Runtime permission",
            "Observability",
        ],
    },
    "track_2_relevance": [
        "Local private Agent output is evidence-linked and remains editable.",
        "LangGraph orchestrates bounded repair and re-plan without becoming canonical truth.",
        "Model Tool Call output remains inert until deterministic Runtime checks pass.",
        "Failures, denial, exhaustion and correction invalidation are explicit terminal paths.",
    ],
    "workflow": {
        "version": M3_WORKFLOW_VERSION,
        "topology_hash_algorithm": "sha256(canonical-json(nodes,edges))",
        "topology_hash": M3_TOPOLOGY_HASH,
        "nodes": list(M3_GRAPH_NODES),
        "edges": [list(edge) for edge in M3_GRAPH_EDGES],
        "budgets": {
            "structured_repairs": M3_STRUCTURED_REPAIR_BUDGET,
            "node_retries": M3_NODE_RETRY_BUDGET,
            "replans": M3_REPLAN_BUDGET,
            "model_calls": M3_MODEL_CALL_BUDGET,
        },
        "model_request_profile": {
            "entries_per_call": 1,
            "statements_per_entry": 5,
            "entry_source_moment_capacity": "all supplied M2 moments",
            "entry_source_moment_rule": (
                "contains the de-duplicated union of all statement source moments"
            ),
            "max_output_tokens": M3_MAX_OUTPUT_TOKENS,
            "timeout_seconds": M3_MODEL_TIMEOUT_SECONDS,
        },
        "state_allowlist": sorted(M3_GRAPH_STATE_ALLOWED_KEYS),
        "forbidden_state": [
            "raw source text",
            "canonical asset or ledger payload",
            "raw prompt or model response",
            "tool arguments or observations",
            "rendered output",
        ],
        "effect_key": "{run_id}:{node_name}:{node_attempt}",
        "canonical_truth": "SQLite application repository",
        "resume_cursor": "LangGraph AsyncSqliteSaver in a separate workflow SQLite database",
        "compile_policy": "one graph instance compiled at application startup",
    },
    "public_examples": [
        "contracts/examples/m3-ledger-complete.json",
        "contracts/examples/m3-ledger-incomplete.json",
        "contracts/examples/m3-ledger-conflicting.json",
        "contracts/examples/m3-ledger-correction-invalidated.json",
        "contracts/examples/m3-workspace-complete.json",
        "contracts/examples/m3-workspace-policy-blocked.json",
        "contracts/examples/m3-negative-scenarios-v1.json",
    ],
    "affected_shared_files_after_e3_merge": [
        {
            "path": "app/experience_asset/api/main.py",
            "planned_change": "inject one startup-compiled M3 graph and register M3 router",
        },
        {
            "path": "app/experience_asset/persistence/repository.py",
            "planned_change": "append/get current M3 artifact with dual optimistic identity checks",
        },
        {
            "path": "app/experience_asset/persistence/migrations/<next-after-e3>_m3_artifacts.sql",
            "planned_change": (
                "assign the migration number only after E3 merge; add immutable "
                "M3 history and current pointer"
            ),
        },
        {
            "path": "app/experience_asset/workflow/__init__.py",
            "planned_change": "export production M3 graph only after integration",
        },
        {
            "path": "scripts/export_contracts.py",
            "planned_change": "promote reviewed M3 schemas into the shared exporter",
        },
        {
            "path": "contracts/openapi.json",
            "planned_change": "regenerate only after real M3 routes exist",
        },
        {
            "path": "web/src/App.tsx",
            "planned_change": "wire the isolated M3 UI after E3 is accepted",
        },
    ],
    "evidence_templates": [
        "evidence/templates/e4-m3/manifest.template.json",
        "evidence/templates/e4-m3/summary.template.md",
    ],
    "checkpoint_completion": {
        "input_output_error_progress_invalidation_contracts": True,
        "ledger_and_workflow_state_contracts": True,
        "public_fixtures_and_negative_paths": True,
        "shared_integration_impact_recorded_without_modification": True,
        "append_only_evidence_template_and_rollback": True,
    },
    "integration_implemented": [
        "FastAPI routes and queryable run outcomes",
        "SQLite migrations 0006/0007, atomic M2/M3/canonical transitions, "
        "durable sanitized Runtime policy decisions and model metadata",
        "production startup-compiled LangGraph with separate workflow database "
        "and sanitized node traces",
        "React workspace with explicit statement and ledger confirmation",
        "exact-commit W7900 runner, deterministic negative-path capture, "
        "real-model M2-to-M3 capture and sanitized packet finalizer",
    ],
    "external_verification_deferred": [
        "quality-owner promotion",
        "kinnyuww execution of the prepared real W7900/ROCm/vLLM gate",
    ],
    "w7900_handoff": {
        "runner": "scripts/run_e4_w7900_gate.py",
        "real_model_capture": "scripts/capture_e4_m3_evidence.py",
        "negative_path_capture": "scripts/capture_e4_m3_negative_evidence.py",
        "packet_finalizer": "scripts/finalize_e4_w7900_packet.py",
        "instructions": "docs/E4_M3_W7900_HANDOFF.md",
        "implementation_owner_remaining_work": (
            "none after local gates pass; teammate performs only the prepared "
            "physical W7900 execution"
        ),
    },
    "evidence_impact": {
        "checkpoint": "Contract / Schema + Fixture",
        "status": "W7900_EXECUTION_PREPARED_PROMOTION_NOT_VERIFIED",
        "expected_packet": "evidence/milestones/e4-m3-w7900/<run_id>/",
        "storage_tier": "Git for sanitized packet; private/raw data stays outside Git",
        "w7900_required_for_preparation": False,
        "w7900_execution_status": "PENDING_KINNYUWW_PHYSICAL_RUN",
    },
    "rollback": (
        "Before production integration, remove only the isolated E4 preparation "
        "files; do not rewrite shared history or prior evidence."
    ),
}

GENERATED = {
    CONTRACT_DIR / "json-schema" / "decision-evidence-ledger-v0.1.schema.json": model_json_schema(
        DecisionEvidenceLedgerV1
    ),
    CONTRACT_DIR / "json-schema" / "m3-workspace-v1.schema.json": model_json_schema(M3WorkspaceV1),
    CONTRACT_DIR / "json-schema" / "m3-progress-v1.schema.json": model_json_schema(M3ProgressV1),
    CONTRACT_DIR / "json-schema" / "m3-failure-v1.schema.json": model_json_schema(M3FailureV1),
    CONTRACT_DIR / "examples" / "m3-ledger-complete.json": COMPLETE_LEDGER,
    CONTRACT_DIR / "examples" / "m3-ledger-incomplete.json": INCOMPLETE_LEDGER,
    CONTRACT_DIR / "examples" / "m3-ledger-conflicting.json": CONFLICTING_LEDGER,
    CONTRACT_DIR / "examples" / "m3-ledger-correction-invalidated.json": CORRECTION_LEDGER,
    CONTRACT_DIR / "examples" / "m3-workspace-complete.json": WORKSPACE_COMPLETE,
    CONTRACT_DIR / "examples" / "m3-workspace-policy-blocked.json": WORKSPACE_POLICY_BLOCKED,
    CONTRACT_DIR / "examples" / "m3-negative-scenarios-v1.json": NEGATIVE_SCENARIOS,
    CONTRACT_DIR / "checkpoints" / "e4-m3-preparation-v1.json": CHECKPOINT,
}


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[Path] = []
    for path, value in GENERATED.items():
        content = rendered(value)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if stale:
        for path in stale:
            print(f"stale generated M3 preparation contract: {path}")
        return 1
    print("M3 preparation contracts are current" if args.check else "M3 contracts generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
