from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from policyseal.agent.copilot_graph import ReviewCopilot
from policyseal.agent.retrieval import HybridEvidenceRetriever
from policyseal.agent.tools import ReviewTools
from policyseal.application.analysis import AnalysisService
from policyseal.application.simulations import SimulationService
from policyseal.audit.models import AuditEventType
from policyseal.documents.base import DocumentAdapter
from policyseal.documents.docx import DocxAdapter
from policyseal.documents.pdf import PdfAdapter
from policyseal.documents.preflight import PreflightService
from policyseal.documents.residual import ResidualScanner
from policyseal.documents.xlsx import XlsxAdapter
from policyseal.domain.enums import FileKind
from policyseal.domain.models import DisclosureContext
from policyseal.evals.assets import EvalAssets, GoldenScenario, load_eval_assets
from policyseal.policy.loader import load_policy_pack
from policyseal.security.fingerprints import KeyedFingerprinter
from policyseal.security.key_store import MasterKeyStore
from policyseal.security.pseudonyms import Pseudonymizer
from policyseal.storage.database import Database
from policyseal.storage.file_store import ControlledFileStore
from policyseal.storage.repositories import PolicySealRepository


@dataclass(frozen=True, slots=True)
class CopilotHarness:
    analysis: AnalysisService
    copilot: ReviewCopilot
    assets: EvalAssets


@pytest.fixture
def copilot_harness(tmp_path: Path) -> CopilotHarness:
    database = Database.from_url(f"sqlite:///{tmp_path / 'copilot.db'}")
    database.create_schema()
    repository = PolicySealRepository(database.session_factory)
    file_store = ControlledFileStore(tmp_path / "files")
    key_store = MasterKeyStore(tmp_path / "secrets" / "master.key")
    fingerprinter = KeyedFingerprinter(key_store)
    residual = ResidualScanner(key_store)
    preflight = PreflightService()
    policy_pack = load_policy_pack(Path("policies/v1"))
    adapters: dict[FileKind, DocumentAdapter] = {
        FileKind.XLSX: XlsxAdapter(preflight, residual),
        FileKind.DOCX: DocxAdapter(preflight, residual, Pseudonymizer(key_store)),
        FileKind.PDF: PdfAdapter(preflight, residual),
    }
    ids = itertools.count(1)

    def clock() -> datetime:
        return datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

    analysis = AnalysisService(
        repository,
        file_store,
        policy_pack,
        adapters,
        fingerprinter,
        clock=clock,
        id_factory=lambda prefix: f"{prefix}-copilot-{next(ids):04d}",
    )
    simulations = SimulationService(analysis)
    retriever = HybridEvidenceRetriever.from_policy_pack(policy_pack)
    copilot = ReviewCopilot(
        ReviewTools(repository, simulations, retriever),
        audit_chain=analysis.audit_chain,
        policy_sha256=policy_pack.sha256,
    )
    return CopilotHarness(analysis, copilot, load_eval_assets())


def _source(scenario: GoldenScenario) -> tuple[Path, str]:
    return {
        "supplier-matrix-hero": (
            Path("demo_data/sources/supplier-matrix-hero.xlsx"),
            ".xlsx",
        ),
        "security-incident-hero": (
            Path("demo_data/sources/security-incident-hero.docx"),
            ".docx",
        ),
        "reference-contract-hero": (
            Path("demo_data/sources/reference-contract-hero.pdf"),
            ".pdf",
        ),
    }[scenario.source_id]


def _analyze_scenario(
    harness: CopilotHarness,
    scenario: GoldenScenario,
) -> tuple[str, str]:
    source, suffix = _source(scenario)
    created = harness.analysis.create_task(
        source.read_bytes(),
        suffix=suffix,
        context=DisclosureContext(**scenario.context.model_dump()),
        requester_id=f"requester-{scenario.id}",
    )
    result = harness.analysis.analyze_revision(created.revision.id)
    assert result.revision.status is scenario.expected_revision_status
    return result.task.id, result.revision.id


def test_all_six_frozen_three_turn_dialogues_are_grounded_and_task_local(
    copilot_harness: CopilotHarness,
) -> None:
    thread_tasks: list[tuple[str, str]] = []
    for dialogue in copilot_harness.assets.copilot_dialogues:
        scenario = next(
            item for item in copilot_harness.assets.scenarios if item.id == dialogue.scenario_id
        )
        task_id, revision_id = _analyze_scenario(copilot_harness, scenario)
        thread = copilot_harness.copilot.start_thread(
            task_id,
            revision_id,
            display_reference=scenario.id,
        )
        thread_tasks.append((thread.thread_id, task_id))

        for turn_number, turn in enumerate(dialogue.turns, start=1):
            reply = copilot_harness.copilot.respond(
                thread.thread_id,
                task_id=task_id,
                message=turn.user,
            )
            cited_rules = {rule_id for citation in reply.citations for rule_id in citation.rule_ids}
            cited_evidence = {
                evidence_id for citation in reply.citations for evidence_id in citation.evidence_ids
            }
            lowered = reply.text.casefold()

            assert reply.turn_number == turn_number
            assert reply.intent.value == turn.intent.value
            assert reply.task_id == task_id
            assert reply.revision_id == revision_id
            assert reply.model_dependent is False
            assert set(turn.expected_rule_ids).issubset(cited_rules)
            assert set(turn.expected_evidence_ids).issubset(cited_evidence)
            assert all(required.casefold() in lowered for required in turn.must_include)
            for forbidden in turn.must_not_include:
                assert forbidden.casefold() not in lowered, (
                    dialogue.id,
                    turn_number,
                    forbidden,
                    reply.text,
                )
            assert "context" in lowered
            assert "rules:" in lowered
            assert "evidence:" in lowered
            assert reply.citations

        saved = copilot_harness.copilot.checkpoints.load(
            thread.thread_id,
            task_id=task_id,
        )
        assert len(saved.turns) == 3
        assert all(turn.user not in repr(saved) for turn in dialogue.turns)

    first_thread, first_task = thread_tasks[0]
    _, second_task = thread_tasks[1]
    assert first_task != second_task
    with pytest.raises(KeyError, match="isolated"):
        copilot_harness.copilot.respond(
            first_thread,
            task_id=second_task,
            message="Why?",
        )
    copilot_events = tuple(
        event
        for event in copilot_harness.copilot.tools.repository.list_audit_events()
        if event.event_type is AuditEventType.COPILOT_USED
    )
    assert len(copilot_events) == 18
    serialized_audit = repr(copilot_events)
    for forbidden in (
        "9900012345678901",
        "Crimson-Falcon-47!",
        "ps_demo_token_7f4b2e91",
        "Blue Peak Systems",
    ):
        assert forbidden not in serialized_audit


def test_exception_draft_is_local_and_cannot_submit_itself(
    copilot_harness: CopilotHarness,
) -> None:
    scenario = next(item for item in copilot_harness.assets.scenarios if item.id == "scenario-18")
    task_id, revision_id = _analyze_scenario(copilot_harness, scenario)
    thread = copilot_harness.copilot.start_thread(task_id, revision_id)

    reply = copilot_harness.copilot.respond(
        thread.thread_id,
        task_id=task_id,
        message="Draft an exception for the custom SLA.",
    )

    assert reply.exception_draft_id is not None
    draft = copilot_harness.copilot.tools.get_exception_draft(reply.exception_draft_id)
    assert draft.status == "draft"
    assert draft.submitted is False
    assert not hasattr(copilot_harness.copilot.tools, "approve")
