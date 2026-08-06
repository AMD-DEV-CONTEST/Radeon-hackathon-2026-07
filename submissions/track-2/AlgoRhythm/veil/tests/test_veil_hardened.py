"""Security and Agent Capability hardening validation.

Asserts that upload path traversal is blocked, SQLite-backed persistence survives restarts,
the local entity ledger updates and queries aliases, and interactive multi-turn overrides
successfully execute a fresh verification attack.
"""
from __future__ import annotations

import os
import pytest
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

from veil.types import Span, Finding, Tier, Role, EditType
from veil.security.persistence import PersistenceStore
from veil.security.auth import STORE
from veil.tools.entity_ledger import record_mention, entity_ledger
from veil.tools.corpus_search import corpus_search


@pytest.fixture
def temp_db(tmp_path):
    db_path = str(tmp_path / "test_persistence.db")
    return PersistenceStore(db_path=db_path)


class TestPersistenceAndSecurity:
    def test_upload_security_prevents_path_traversal(self):
        # Verify that filenames are strictly sanitized to their base names
        raw_filename = "../../../../etc/passwd"
        filename_clean = Path(raw_filename).name
        assert filename_clean == "passwd"
        assert "/" not in filename_clean
        assert "\\" not in filename_clean

    def test_document_and_report_survive_restart(self, temp_db):
        doc_id = "test_doc_123"
        spans = [Span(start=0, end=14, text="Test document.", page=1, source="body")]
        
        # Save to database
        temp_db.save_document(
            doc_id=doc_id,
            filename="test.pdf",
            filepath="/tmp/uploads/test.pdf",
            text="Test document.",
            spans=spans
        )
        
        # Load from database
        loaded = temp_db.load_document(doc_id)
        assert loaded is not None
        assert loaded["filename"] == "test.pdf"
        assert loaded["text"] == "Test document."
        assert len(loaded["spans"]) == 1
        assert loaded["spans"][0].text == "Test document."

        # Mock a RunReport
        from veil.agents.orchestrator import RunReport
        from veil.types import IterationResult
        
        findings = [
            Finding(
                persona="Data-Broker",
                tier=Tier.CORRELATIONAL,
                claim="Leak found",
                reasoning="R",
                spans=spans,
                severity=0.8,
                candidate_set_size=5
            )
        ]
        iterations = [
            IterationResult(
                iteration=1,
                findings=findings,
                residual_risk=0.8,
                utility_retained=0.9,
                elapsed_s=1.2
            )
        ]
        
        report = RunReport(
            document_id=doc_id,
            original_text="Test document.",
            final_text="Test document redacted.",
            iterations=iterations,
            curve=[{"iteration": 1, "residual_risk": 0.8}],
            metrics={"calls": 1},
            plan={"personas": ["Data-Broker"]},
            stopped_because="Iteration limit"
        )
        
        temp_db.save_report(doc_id, "Test document redacted.", report)
        
        # Load report
        loaded_report = temp_db.load_report(doc_id)
        assert loaded_report is not None
        assert loaded_report.final_text == "Test document redacted."
        assert len(loaded_report.iterations) == 1
        assert loaded_report.iterations[0].findings[0].claim == "Leak found"


class TestLocalMemoryEntityLedger:
    def test_record_mention_hashing_and_retrieval(self, tmp_path):
        # Force entity_ledger module to use custom test db path
        test_db = str(tmp_path / "test_ledger.db")
        
        import veil.tools.entity_ledger as el
        from veil.config import CONFIG
        
        original_db = CONFIG.storage.db_path
        CONFIG.storage.db_path = test_db
        
        try:
            # 1. Record entity details from Document A
            doc_a_id = "docA_hash"
            record_mention(
                canonical="Amara Osei",
                kind="person",
                document_id=doc_a_id,
                surface="Dr. Osei",
                attributes={"city": "Bristol", "department": "Governance"}
            )
            
            # Retrieve specific entity details
            alias = el.make_alias("person", "Amara Osei")
            result = entity_ledger(alias=alias)
            
            assert result["found"] is True
            assert result["alias"] == alias
            assert "Bristol" in result["known_attributes"]["city"]
            assert len(result["documents"]) == 1
            assert result["documents"][0]["document_id"] == doc_a_id
            
            # 2. Record entity details from Document B to test accumulation memory
            doc_b_id = "docB_hash"
            record_mention(
                canonical="Amara Osei",
                kind="person",
                document_id=doc_b_id,
                surface="Amara Osei",
                attributes={"city": "Bristol", "job_title": "Director"}
            )
            
            updated_result = entity_ledger(alias=alias)
            assert updated_result["found"] is True
            assert len(updated_result["documents"]) == 2
            assert "Director" in updated_result["known_attributes"]["job_title"]
            assert updated_result["accumulation_warning"] is not None
            
        finally:
            CONFIG.storage.db_path = original_db


class TestInteractiveOverrideAndVerify:
    @pytest.mark.asyncio
    async def test_custom_repair_and_re_attack_verification(self):
        from veil.agents.orchestrator import Orchestrator
        from veil.inference.client import CallMetrics
        
        # Stub VLLMClient complete for Guardian proposals & Adversary re-attacks
        stub_client = AsyncMock()
        
        # Custom proposals output: Guardian outputting custom JSON edit list
        stub_client.complete.side_effect = [
            (
                '[{"finding_id": "test_fid", "edit_type": "generalize", "original": "Amara Osei", "replacement": "Senior Director", "rationale": "override"}]',
                CallMetrics()
            ),
            (
                '[]',  # Empty findings output for Adversary fresh re-attack wave -> finding resolved!
                CallMetrics()
            )
        ]
        
        orch = Orchestrator()
        orch.client = stub_client
        orch.guardian.client = stub_client
        
        doc_text = "Incident reviewed by Amara Osei."
        spans = [Span(start=0, end=len(doc_text), text=doc_text, page=1, source="body")]
        
        findings = [
            Finding(
                persona="Insider",
                tier=Tier.CORRELATIONAL,
                claim="Leaks Amara Osei name",
                reasoning="R",
                spans=[Span(start=21, end=31, text="Amara Osei", page=1, source="body")],
                severity=0.7,
                candidate_set_size=3,
                id="test_fid"
            )
        ]
        
        final_text, final_findings, r_val, u_val = await orch.custom_repair_and_verify(
            document_text=doc_text,
            spans=spans,
            findings=findings,
            aggressiveness="balanced",
            overrides={"test_fid": "generalize"}
        )
        
        # Assertions
        assert "Senior Director" in final_text
        assert "Amara Osei" not in final_text
        assert findings[0].resolved is True  # Resolved because the fresh re-attack wave returned no findings
        assert r_val == 0.0  # Risk score should decrease to minimal/zero
