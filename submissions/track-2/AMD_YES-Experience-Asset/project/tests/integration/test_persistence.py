from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.experience_asset.domain.enums import TerminalState
from app.experience_asset.domain.models import ExperienceAssetV1, TerminalResultV1
from app.experience_asset.inference.models import (
    M2SemanticRoleAssignment,
    M2SemanticRoleProposal,
)
from app.experience_asset.persistence import SQLiteAssetRepository, StorageConflictError


def next_version(asset: ExperienceAssetV1, *, reason: str) -> ExperienceAssetV1:
    now = asset.updated_at + timedelta(seconds=1)
    version_id = uuid4()
    payload = asset.model_dump(mode="python")
    payload["version_id"] = version_id
    payload["updated_at"] = now
    payload["goal"] = reason
    payload["lineage"] = {
        "version_id": version_id,
        "parent_version_id": asset.version_id,
        "schema_version": "1.0.0",
        "change_kind": "USER_EDIT",
        "change_reason": reason,
        "created_at": now,
    }
    return ExperienceAssetV1.model_validate(payload)


def test_restart_restores_current_and_keeps_immutable_history(
    tmp_path,
    public_ready_asset,
) -> None:
    database = tmp_path / "asset.sqlite3"
    repository = SQLiteAssetRepository(database)
    repository.initialize()
    repository.create(public_ready_asset)
    second = next_version(public_ready_asset, reason="Clarify the user goal.")
    repository.append(
        second,
        expected_current_version_id=public_ready_asset.version_id,
    )

    restarted = SQLiteAssetRepository(database)
    restarted.initialize()
    with restarted._connect() as connection:
        assert [
            row["version"]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    assert restarted.get_current(public_ready_asset.asset_id) == second
    assert restarted.get_version(public_ready_asset.version_id) == public_ready_asset
    assert restarted.list_version_ids(public_ready_asset.asset_id) == [
        public_ready_asset.version_id,
        second.version_id,
    ]


def test_stale_current_pointer_cannot_overwrite_newer_version(
    tmp_path,
    public_ready_asset,
) -> None:
    repository = SQLiteAssetRepository(tmp_path / "asset.sqlite3")
    repository.initialize()
    repository.create(public_ready_asset)
    second = next_version(public_ready_asset, reason="Accepted edit.")
    repository.append(second, expected_current_version_id=public_ready_asset.version_id)
    stale = next_version(public_ready_asset, reason="Stale edit.")
    with pytest.raises(StorageConflictError, match="current version changed"):
        repository.append(
            stale,
            expected_current_version_id=public_ready_asset.version_id,
        )
    assert repository.get_current(public_ready_asset.asset_id) == second


def test_m2_semantic_proposal_is_durable_and_idempotent(
    tmp_path,
    public_ready_asset,
) -> None:
    repository = SQLiteAssetRepository(tmp_path / "asset.sqlite3")
    repository.initialize()
    repository.create(public_ready_asset)
    run_id = uuid4()
    statement_id = uuid4()
    started = datetime.now(UTC)
    repository.start_run(
        run_id=run_id,
        asset_id=public_ready_asset.asset_id,
        command="E3-M2-semantic-persistence",
        model_id="Qwen2.5-14B-Instruct",
        model_config_hash="b" * 64,
        code_commit="c" * 40,
        started_at=started,
    )
    proposal = M2SemanticRoleProposal(
        assignments=[
            M2SemanticRoleAssignment(
                statement_id=statement_id,
                roles=["CUE", "SURPRISE"],
                reasoning="The observation contradicted the expected outcome.",
            )
        ]
    )
    proposal_hash = "d" * 64

    repository.save_m2_semantic_role_proposal(
        run_id=run_id,
        proposal=proposal,
        proposal_hash=proposal_hash,
        model_id="Qwen2.5-14B-Instruct",
        server_base_url="http://127.0.0.1:8000/v1",
        created_at=started,
    )
    repository.save_m2_semantic_role_proposal(
        run_id=run_id,
        proposal=proposal,
        proposal_hash=proposal_hash,
        model_id="Qwen2.5-14B-Instruct",
        server_base_url="http://127.0.0.1:8000/v1",
        created_at=started,
    )

    assert repository.get_m2_semantic_role_proposal(run_id) == (
        proposal,
        proposal_hash,
    )
    with pytest.raises(StorageConflictError, match="already differs"):
        repository.save_m2_semantic_role_proposal(
            run_id=run_id,
            proposal=proposal,
            proposal_hash="e" * 64,
            model_id="Qwen2.5-14B-Instruct",
            server_base_url="http://127.0.0.1:8000/v1",
            created_at=started,
        )


def test_run_has_exactly_one_visible_terminal_result(tmp_path, public_ready_asset) -> None:
    repository = SQLiteAssetRepository(tmp_path / "asset.sqlite3")
    repository.initialize()
    repository.create(public_ready_asset)
    run_id = uuid4()
    started = datetime.now(UTC)
    repository.start_run(
        run_id=run_id,
        asset_id=public_ready_asset.asset_id,
        command="E1-A-contract-smoke",
        model_id="deterministic-contract-fake",
        model_config_hash="b" * 64,
        code_commit=None,
        started_at=started,
    )
    result = TerminalResultV1(
        run_id=run_id,
        state=TerminalState.SUCCEEDED,
        last_durable_version_id=public_ready_asset.version_id,
        retryable=False,
        safe_user_message="Contract smoke completed.",
        elapsed_ms=1,
        model_call_count=1,
        recovery_action="No recovery required.",
        finished_at=started + timedelta(milliseconds=1),
    )
    repository.finish_run(result)
    with pytest.raises(StorageConflictError, match="already terminal"):
        repository.finish_run(result)
