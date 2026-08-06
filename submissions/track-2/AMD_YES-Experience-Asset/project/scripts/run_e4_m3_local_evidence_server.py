#!/usr/bin/env python3
"""Run the loopback FastAPI app with a deterministic public-fixture M3 model."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.experience_asset.api.main import create_app  # noqa: E402
from app.experience_asset.inference import FakeModelClient  # noqa: E402
from app.experience_asset.inference.models import (  # noqa: E402
    M2SemanticRoleAssignment,
    M2SemanticRoleProposal,
    M2SemanticRoleResult,
    M3LedgerProposal,
    M3LedgerResult,
    ModelMetadata,
)


class E4PublicFixtureModel(FakeModelClient):
    """Deterministic local evidence worker; never used as submitted inference."""

    async def generate_m2_roles(self, request):
        statement_ids = request.canonical_context.get("statement_ids")
        if not isinstance(statement_ids, list) or not statement_ids:
            raise ValueError("M2 public fixture requires canonical statement IDs")
        proposal = M2SemanticRoleProposal(
            assignments=[
                M2SemanticRoleAssignment(
                    statement_id=UUID(str(statement_id)),
                    roles=["CUE", "CHANGE", "SURPRISE"] if index == 0 else [],
                    reasoning="Configured sanitized public-browser fixture.",
                )
                for index, statement_id in enumerate(statement_ids)
            ]
        )
        return M2SemanticRoleResult(
            proposal=proposal,
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/e4-public-fixture",
                model_id="e4-public-fixture-model",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )

    async def generate_m3_ledger(self, request):
        moments = request.canonical_context.get("moments")
        if not isinstance(moments, list) or not moments:
            raise ValueError("M3 public fixture requires current M2 moments")
        moment = moments[0]
        if not isinstance(moment, dict):
            raise ValueError("M3 public fixture moment must be an object")
        moment_id = UUID(str(moment["moment_id"]))
        source_ids = moment.get("source_statement_ids")
        if not isinstance(source_ids, list) or not source_ids:
            raise ValueError("M3 public fixture moment requires source statements")
        statement_id = UUID(str(source_ids[0]))
        affected_ids = request.canonical_context.get("affected_entry_ids")
        prior_decision_id = (
            UUID(str(affected_ids[0]))
            if isinstance(affected_ids, list) and affected_ids
            else None
        )
        proposal = M3LedgerProposal(
            entries=[
                {
                    "prior_decision_id": prior_decision_id,
                    "title": "试坐后的选择与结果",
                    "source_moment_ids": [moment_id],
                    "statements": [
                        {
                            "role": role,
                            "text": f"{role}: 来自公开测试经历的可核对陈述。",
                            "source_moment_ids": [moment_id],
                            "source_statement_ids": [statement_id],
                        }
                        for role in (
                            "ALTERNATIVE",
                            "REASON",
                            "DECISION",
                            "ACTION",
                            "OBSERVED_RESULT",
                        )
                    ],
                }
            ]
        )
        return M3LedgerResult(
            proposal=proposal,
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/e4-public-fixture",
                model_id="e4-public-fixture-model",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--workflow-database", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--code-commit", default="UNCOMMITTED")
    args = parser.parse_args()
    app = create_app(
        database_path=args.database,
        workflow_database_path=args.workflow_database,
        model_client=E4PublicFixtureModel(),
        code_commit=args.code_commit,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
