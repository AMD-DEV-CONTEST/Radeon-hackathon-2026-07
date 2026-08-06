#!/usr/bin/env python3
"""Generate or check the reviewed Lane A contracts consumed by Lane B."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.experience_asset.api.main import create_app
from app.experience_asset.domain.m1 import ExperienceBriefV1, M1WorkspaceV1
from app.experience_asset.domain.m2 import CriticalMomentMapV1, M2WorkspaceV1
from app.experience_asset.domain.m4 import InsightBoundaryMapV1, M4WorkspaceV1
from app.experience_asset.domain.models import (
    AgentRunStateV1,
    ExperienceAssetV1,
    PolicyDecision,
    ProgressEventV1,
    TerminalResultV1,
    ToolExecutionRecord,
    VerificationReport,
    WorkPlanV1,
    model_json_schema,
)
from app.experience_asset.domain.relation import (
    DiscoveryAttemptV1,
    DiscoveryFingerprintV1,
    KnowledgeCardReadinessRecordV1,
    RelationCandidateV1,
    RelationWorkspaceV1,
    RoleGraphProjectionV1,
)
from app.experience_asset.inference.models import (
    M2SemanticRoleProposal,
    StructuredProposal,
)

CONTRACT_DIR = ROOT / "contracts"
GENERATED = {
    CONTRACT_DIR / "json-schema" / "experience-asset-v1.schema.json": model_json_schema(
        ExperienceAssetV1
    ),
    CONTRACT_DIR / "json-schema" / "experience-brief-v0.1.schema.json": model_json_schema(
        ExperienceBriefV1
    ),
    CONTRACT_DIR / "json-schema" / "m1-workspace-v1.schema.json": model_json_schema(M1WorkspaceV1),
    CONTRACT_DIR / "json-schema" / "critical-moment-map-v0.1.schema.json": model_json_schema(
        CriticalMomentMapV1
    ),
    CONTRACT_DIR / "json-schema" / "m2-workspace-v1.schema.json": model_json_schema(M2WorkspaceV1),
    CONTRACT_DIR / "json-schema" / "structured-proposal-v1.schema.json": model_json_schema(
        StructuredProposal
    ),
    CONTRACT_DIR
    / "json-schema"
    / "m2-semantic-role-proposal-v1.schema.json": model_json_schema(
        M2SemanticRoleProposal
    ),
    CONTRACT_DIR / "json-schema" / "progress-event-v1.schema.json": model_json_schema(
        ProgressEventV1
    ),
    CONTRACT_DIR / "json-schema" / "terminal-result-v1.schema.json": model_json_schema(
        TerminalResultV1
    ),
    CONTRACT_DIR / "json-schema" / "agent-run-state-v1.schema.json": model_json_schema(
        AgentRunStateV1
    ),
    CONTRACT_DIR / "json-schema" / "work-plan-v1.schema.json": model_json_schema(WorkPlanV1),
    CONTRACT_DIR / "json-schema" / "policy-decision-v1.schema.json": model_json_schema(
        PolicyDecision
    ),
    CONTRACT_DIR / "json-schema" / "tool-execution-record-v1.schema.json": model_json_schema(
        ToolExecutionRecord
    ),
    CONTRACT_DIR / "json-schema" / "verification-report-v1.schema.json": model_json_schema(
        VerificationReport
    ),
    CONTRACT_DIR
    / "json-schema"
    / "insight-boundary-map-v0.1.schema.json": model_json_schema(InsightBoundaryMapV1),
    CONTRACT_DIR / "json-schema" / "m4-workspace-v1.schema.json": model_json_schema(
        M4WorkspaceV1
    ),
    CONTRACT_DIR
    / "json-schema"
    / "knowledge-card-readiness-v1.schema.json": model_json_schema(
        KnowledgeCardReadinessRecordV1
    ),
    CONTRACT_DIR / "json-schema" / "role-graph-projection-v1.schema.json": model_json_schema(
        RoleGraphProjectionV1
    ),
    CONTRACT_DIR / "json-schema" / "discovery-fingerprint-v1.schema.json": model_json_schema(
        DiscoveryFingerprintV1
    ),
    CONTRACT_DIR / "json-schema" / "discovery-attempt-v1.schema.json": model_json_schema(
        DiscoveryAttemptV1
    ),
    CONTRACT_DIR / "json-schema" / "relation-candidate-v1.schema.json": model_json_schema(
        RelationCandidateV1
    ),
    CONTRACT_DIR / "json-schema" / "relation-workspace-v1.schema.json": model_json_schema(
        RelationWorkspaceV1
    ),
    CONTRACT_DIR / "openapi.json": create_app(
        database_path="/tmp/experience-asset-contract.sqlite3"
    ).openapi(),
    CONTRACT_DIR / "examples" / "health.json": {
        "service": "experience-asset-agent",
        "status": "ok",
        "app_version": "0.1.0",
        "canonical_schema_version": "1.0.0",
        "database": "ok",
        "inference_mode": "local_only",
        "model_endpoint": "http://127.0.0.1:8000/v1",
        "model_profile": "Qwen/Qwen2.5-14B-Instruct",
        "gpu_viability": "NOT_VERIFIED",
        "checked_at": "2026-07-24T05:00:00Z",
    },
    CONTRACT_DIR / "examples" / "progress-running.json": {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-4000-8000-000000000011",
        "run_id": "00000000-0000-4000-8000-000000000012",
        "asset_id": "00000000-0000-4000-8000-000000000013",
        "version_id": "00000000-0000-4000-8000-000000000014",
        "sequence": 2,
        "stage": "canonical-validation",
        "state": "RUNNING",
        "percent": 40,
        "percent_basis": "milestones_done/milestones_total",
        "milestones_done": 2,
        "milestones_total": 5,
        "internal_completed_units": 2,
        "internal_total_units": 4,
        "eta_seconds": None,
        "eta_basis": None,
        "eta_history_sample_size": None,
        "message": "正在校验规范化资产。",
        "occurred_at": "2026-07-24T05:00:01Z",
        "terminal_state": None,
    },
    CONTRACT_DIR / "examples" / "terminal-model-unavailable.json": {
        "schema_version": "1.0.0",
        "run_id": "00000000-0000-4000-8000-000000000012",
        "state": "MODEL_UNAVAILABLE",
        "last_durable_version_id": "00000000-0000-4000-8000-000000000014",
        "retryable": True,
        "safe_user_message": "本地模型暂时不可用，已保留最后一次有效版本。",
        "internal_error_class": "LocalModelConnectionError",
        "elapsed_ms": 1200,
        "model_call_count": 1,
        "recovery_action": "检查本地 vLLM 服务后重试当前步骤。",
        "finished_at": "2026-07-24T05:00:02Z",
    },
    CONTRACT_DIR / "examples" / "structured-tool-proposal.json": {
        "schema_version": "1.0.0",
        "summary": "请求读取已保存的规范化版本；执行仍需 Runtime 策略授权。",
        "proposed_statements": [],
        "questions": [],
        "tool_call_proposals": [
            {
                "name": "search_current_experience",
                "arguments": {
                    "asset_id": "00000000-0000-4000-8000-000000000013",
                    "scope": "CURRENT_SOURCE",
                    "query": "synthetic current-source smoke",
                    "top_k": 3,
                },
                "requested_reason": "读取当前规范化状态。",
                "permission_granted": False,
            }
        ],
    },
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
            print(f"stale generated contract: {path}")
        return 1
    print("contracts are current" if args.check else "contracts generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
