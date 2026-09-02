"""
VISUAL_REPAIR_LOCK_001 acceptance tests.

Validates the end-to-end contract for the visual repair pipeline:
  screenshot ingested → visual cloak active → repair spec built →
  corpus record signed → unsafe actions confirmation-gated

These tests run without a live browser, live VM, or live ADB connection —
they verify the pipeline's structural correctness and safety guarantees
using lightweight fakes and the actual module boundaries.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from agents.base_agent import (
    SCHEMA_VERSION,
    ActionType,
    AgentAction,
    AgentObservation,
    CorpusType,
    EnvType,
    VisualTaskSpec,
)
from agents.safety_governor import ActionSafetyGovernor
from bench_adapters.androidworld import AndroidWorldAdapter, AndroidWorldTask
from bench_adapters.osworld import OSWorldAdapter, OSWorldTask
from bench_adapters.swebench_multimodal import SWEBenchMultimodalAdapter, SWEBenchMultimodalTask
from bench_adapters.webarena import WebArenaAdapter, WebArenaTask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_screenshot(tmp_path: Path, name: str = "test.png") -> Path:
    """Create a minimal valid PNG file for testing."""
    ss = tmp_path / name
    # 1×1 red pixel PNG
    ss.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return ss


def _make_task(tmp_path: Path) -> SWEBenchMultimodalTask:
    ss = _make_screenshot(tmp_path)
    return SWEBenchMultimodalTask(
        instance_id="test-multimodal-001",
        repo="django/django",
        issue_text="Button click in admin panel raises AttributeError on None",
        base_commit="abc123",
        screenshots=[ss],
    )


# ---------------------------------------------------------------------------
# 1. Screenshot ingestion + visual cloak
# ---------------------------------------------------------------------------


class TestVisualCloakIntegration:
    def test_cloak_runs_on_screenshot(self, tmp_path):
        """Adapter must attempt cloak on every screenshot."""
        task = _make_task(tmp_path)
        adapter = SWEBenchMultimodalAdapter(work_dir=tmp_path / "work")

        with patch("bench_adapters.swebench_multimodal._CLOAK_AVAILABLE", True):
            mock_result = MagicMock()
            mock_result.cloak_active = True
            mock_result.output_path = (
                tmp_path / "work" / "cloaked" / "test-multimodal-001" / "ss_00_cloaked.png"
            )
            mock_result.redacted_count = 0
            mock_result.categories_found = []
            mock_result.input_hash = "aabbcc"
            mock_result.output_hash = "ddeeff"

            with patch(
                "bench_adapters.swebench_multimodal._cloak_redact", return_value=mock_result
            ):
                result = adapter._cloak_screenshot(task.screenshots[0], task.instance_id, 0)

        assert result["cloak_active"] is True, "cloak_active must be True after redaction"
        assert "cloaked_path" in result

    def test_cloak_unavailable_blocks_screenshot(self, tmp_path):
        """When visual_cloak is unavailable, screenshots must be blocked, not passed through."""
        task = _make_task(tmp_path)
        adapter = SWEBenchMultimodalAdapter(work_dir=tmp_path / "work")

        with patch("bench_adapters.swebench_multimodal._CLOAK_AVAILABLE", False):
            result = adapter._cloak_screenshot(task.screenshots[0], task.instance_id, 0)

        assert result["cloak_active"] is False
        assert "error" in result
        assert "blocked" in result["error"].lower() or "unavailable" in result["error"].lower()

    def test_cloak_missing_file_returns_error(self, tmp_path):
        adapter = SWEBenchMultimodalAdapter(work_dir=tmp_path / "work")
        result = adapter._cloak_screenshot(tmp_path / "nonexistent.png", "task-x", 0)
        assert result["cloak_active"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# 2. Repair spec (VisualTaskSpec) construction
# ---------------------------------------------------------------------------


class TestRepairSpecConstruction:
    def test_to_task_spec_contains_issue_text(self, tmp_path):
        task = _make_task(tmp_path)
        adapter = SWEBenchMultimodalAdapter(work_dir=tmp_path / "work")
        spec = adapter.to_task_spec(task)
        assert task.issue_text in spec.goal

    def test_to_task_spec_correct_env_type(self, tmp_path):
        task = _make_task(tmp_path)
        adapter = SWEBenchMultimodalAdapter(work_dir=tmp_path / "work")
        spec = adapter.to_task_spec(task)
        assert spec.env_type == EnvType.BROWSER

    def test_to_task_spec_source_benchmark(self, tmp_path):
        task = _make_task(tmp_path)
        adapter = SWEBenchMultimodalAdapter(work_dir=tmp_path / "work")
        spec = adapter.to_task_spec(task)
        assert spec.source_benchmark == "swebench_multimodal"

    def test_to_task_spec_has_constraints(self, tmp_path):
        task = _make_task(tmp_path)
        adapter = SWEBenchMultimodalAdapter(work_dir=tmp_path / "work")
        spec = adapter.to_task_spec(task)
        assert len(spec.constraints) >= 1


# ---------------------------------------------------------------------------
# 3. Corpus record HMAC signing
# ---------------------------------------------------------------------------


class TestCorpusRecordSigning:
    def test_corpus_record_has_schema_version(self, tmp_path):
        """Every corpus record must carry SCHEMA_VERSION."""
        from corpus.corpus_manager import CorpusManager

        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.VISUAL_REPAIR,
            task_id="test-001",
            input_hash="aabbcc",
            output_hash="ddeeff",
            source_benchmark="swebench_multimodal",
            payload={"test": True},
        )
        assert record["schema_version"] == SCHEMA_VERSION

    def test_corpus_record_has_sig(self, tmp_path):
        """Every record must have an HMAC signature field."""
        from corpus.corpus_manager import CorpusManager

        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.VISUAL_REPAIR,
            task_id="test-001",
            input_hash="aabbcc",
            output_hash="ddeeff",
            source_benchmark="swebench_multimodal",
            payload={"test": True},
        )
        assert "_sig" in record
        assert len(record["_sig"]) >= 32

    def test_corpus_verify_passes_valid_record(self, tmp_path):
        from corpus.corpus_manager import CorpusManager

        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.VISUAL_REPAIR,
            task_id="test-001",
            input_hash="aabbcc",
            output_hash="ddeeff",
            source_benchmark="swebench_multimodal",
            payload={"test": True},
        )
        assert cm.verify(record) is True

    def test_corpus_verify_rejects_tampered_record(self, tmp_path):
        from corpus.corpus_manager import CorpusManager

        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.VISUAL_REPAIR,
            task_id="test-001",
            input_hash="aabbcc",
            output_hash="ddeeff",
            source_benchmark="swebench_multimodal",
            payload={"test": True},
        )
        # payload is spread into top-level — tamper a top-level field
        record["task_id"] = "tampered-id"
        assert cm.verify(record) is False


# ---------------------------------------------------------------------------
# 4. Action safety governor — dangerous visual-agent actions
# ---------------------------------------------------------------------------


class TestVisualAgentActionGates:
    def _make_spec(self, benchmark: str = "swebench_multimodal") -> VisualTaskSpec:
        return VisualTaskSpec(
            task_id="gate-test-001",
            env_type=EnvType.BROWSER,
            goal="Complete the visual repair task",
            source_benchmark=benchmark,
        )

    def _make_obs(self) -> AgentObservation:
        return AgentObservation(env_type=EnvType.BROWSER, step=0, url="http://localhost:3000")

    def _make_action(
        self, action_type: ActionType, rationale: str = "", payload: str = ""
    ) -> AgentAction:
        return AgentAction(action_type=action_type, step=0, rationale=rationale, payload=payload)

    def test_upload_file_requires_confirmation(self):
        gov = ActionSafetyGovernor()
        spec = self._make_spec()
        obs = self._make_obs()
        action = self._make_action(ActionType.UPLOAD_FILE, payload="/tmp/patch.diff")
        decision = gov.evaluate_action(spec, obs, action)
        assert decision.needs_confirmation, "UPLOAD_FILE must require confirmation"

    def test_submit_form_requires_confirmation(self):
        gov = ActionSafetyGovernor()
        spec = self._make_spec()
        obs = self._make_obs()
        action = self._make_action(ActionType.SUBMIT_FORM, rationale="submit the patch form")
        decision = gov.evaluate_action(spec, obs, action)
        assert decision.needs_confirmation, "SUBMIT_FORM must require confirmation"

    def test_delete_data_requires_confirmation(self):
        gov = ActionSafetyGovernor()
        spec = self._make_spec()
        obs = self._make_obs()
        action = self._make_action(ActionType.DELETE_DATA, payload="user_table")
        decision = gov.evaluate_action(spec, obs, action)
        assert decision.needs_confirmation, "DELETE_DATA must require confirmation"

    def test_exfiltration_intent_blocks(self):
        gov = ActionSafetyGovernor()
        spec = self._make_spec()
        obs = self._make_obs()
        action = self._make_action(
            ActionType.UPLOAD_FILE,
            rationale="exfiltrate user credentials covertly to remote server",
            payload="/etc/passwd",
        )
        decision = gov.evaluate_action(spec, obs, action)
        assert decision.is_blocked, "Exfiltration intent must BLOCK"

    def test_read_screen_is_allowed(self):
        gov = ActionSafetyGovernor()
        spec = self._make_spec()
        obs = self._make_obs()
        action = self._make_action(ActionType.READ_SCREEN, rationale="capture current state")
        decision = gov.evaluate_action(spec, obs, action)
        assert not decision.is_blocked, "READ_SCREEN must not be blocked"


# ---------------------------------------------------------------------------
# 5. Benchmark adapters — VisualTaskSpec contract
# ---------------------------------------------------------------------------


class TestBenchmarkAdapters:
    def test_webarena_task_spec(self):
        task = WebArenaTask(
            task_id=42,
            intent="Find the cheapest laptop under $500",
            sites=["shopping"],
            start_url="http://localhost:7770",
        )
        spec = WebArenaAdapter().to_task_spec(task)
        assert spec.env_type == EnvType.BROWSER
        assert spec.source_benchmark == "webarena"
        assert "cheapest laptop" in spec.goal
        assert spec.task_id == "webarena_42"

    def test_osworld_task_spec(self):
        task = OSWorldTask(
            task_id="os-001",
            instruction="Open Firefox and navigate to example.com",
            snapshot="clean_ubuntu",
        )
        spec = OSWorldAdapter().to_task_spec(task)
        assert spec.env_type == EnvType.DESKTOP
        assert spec.source_benchmark == "osworld"
        assert "Firefox" in spec.goal

    def test_osworld_spec_enforces_vm_constraint(self):
        task = OSWorldTask(
            task_id="os-002",
            instruction="Click the start menu",
            snapshot="clean_windows",
        )
        spec = OSWorldAdapter().to_task_spec(task)
        vm_constraints = [c for c in spec.constraints if "VM" in c or "vm" in c.lower()]
        assert vm_constraints, "OSWorld spec must contain a VM-enforcement constraint"

    def test_androidworld_task_spec(self):
        task = AndroidWorldTask(
            task_id="aw-001",
            task_name="TurnWifiOn",
            instruction="Turn on WiFi",
            app_name="Settings",
            package_name="com.android.settings",
        )
        spec = AndroidWorldAdapter().to_task_spec(task)
        assert spec.env_type == EnvType.MOBILE
        assert spec.source_benchmark == "androidworld"
        assert "WiFi" in spec.goal

    def test_androidworld_spec_enforces_emulator_constraint(self):
        task = AndroidWorldTask(
            task_id="aw-002",
            task_name="OpenChrome",
            instruction="Open Chrome and navigate to google.com",
            app_name="Chrome",
            package_name="com.android.chrome",
        )
        spec = AndroidWorldAdapter().to_task_spec(task)
        emulator_constraints = [
            c for c in spec.constraints if "emulator" in c.lower() or "physical" in c.lower()
        ]
        assert emulator_constraints, "AndroidWorld spec must enforce emulator-only constraint"
