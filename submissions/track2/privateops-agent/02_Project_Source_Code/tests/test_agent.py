import tempfile
import unittest
from pathlib import Path

from privateops.agent import PrivateOpsAgent
from privateops.config import Settings
from privateops.models import ToolResult


class PrivateOpsAgentTests(unittest.TestCase):
    def test_comprehensive_check_executes_every_selected_system_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)

            class FakeInspector:
                def collect(self, name):
                    return ToolResult(name, "completed", f"Observed {name}.", {"tool": name})

            class CapturingProvider:
                name = "capturing-provider"

                def __init__(self):
                    self.execution_context = None

                def complete(self, prompt, evidence, memory, execution_context=None):
                    self.execution_context = execution_context
                    return "Grounded in observed system results."

            agent.tools.system_inspector = FakeInspector()
            provider = CapturingProvider()
            agent.provider = provider

            response = agent.ask("全面检查我的电脑，只读，不要修改任何设置。", response_language="zh-CN")

            expected = [
                "system_overview",
                "startup_inventory",
                "process_inventory",
                "service_inventory",
                "scheduled_task_inventory",
                "network_listener_inventory",
                "security_status",
            ]
            self.assertEqual([item.name for item in response.tool_results], expected)
            self.assertEqual(
                [item["name"] for item in provider.execution_context["tool_results"]],
                expected,
            )

    def test_model_context_bounds_large_tool_lists_without_truncating_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)

            class FakeInspector:
                def collect(self, name):
                    items = [{"name": f"item-{index}"} for index in range(100)]
                    return ToolResult(name, "completed", "Observed 100 items.", {"items": items, "count": 100, "truncated": False})

            class CapturingProvider:
                name = "capturing-provider"

                def complete(self, prompt, evidence, memory, execution_context=None):
                    self.execution_context = execution_context
                    return "Bounded synthesis."

            agent.tools.system_inspector = FakeInspector()
            provider = CapturingProvider()
            agent.provider = provider

            response = agent.ask("全面检查我的电脑，只读，不要修改任何设置。")

            self.assertEqual(len(response.tool_results[0].output["items"]), 100)
            model_output = provider.execution_context["tool_results"][0]["output"]
            self.assertEqual(len(model_output["items"]), 25)
            self.assertEqual(model_output["count"], 100)
            self.assertTrue(model_output["model_context_truncated"])

    def test_model_context_bounds_every_list_field_without_mutating_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)
            original = ToolResult(
                "custom",
                "completed",
                "Observed lists.",
                {"arbitrary_rows": list(range(40)), "small": ["a", "b"], "count": 40},
            )

            bounded = agent._tool_result_for_model(original)

            self.assertEqual(len(bounded["output"]["arbitrary_rows"]), 25)
            self.assertEqual(bounded["output"]["small"], ["a", "b"])
            self.assertEqual(bounded["output"]["model_context_truncated_fields"], ["arbitrary_rows"])
            self.assertTrue(bounded["output"]["model_context_truncated"])
            self.assertEqual(len(original.output["arbitrary_rows"]), 40)

    def test_remote_amd_provider_is_not_reported_as_same_instance_rocm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            settings = Settings(
                provider_mode="rocm-local",
                knowledge_dir=knowledge,
                state_dir=root / "state",
                workspace_dir=root,
                model_endpoint="https://developer.amd.com.cn/radeon/api/v1/chat/completions",
                model_name="DeepSeek-V4-Flash",
                model_api_key="rc-test-only",
                allow_remote_model=True,
            )

            status = PrivateOpsAgent(settings=settings).status()

            self.assertEqual(status["runtime_mode"], "amd-cloud-api")
            self.assertEqual(status["provider"], "openai-compatible-amd-cloud")
            self.assertEqual(status["core_inference_location"], "AMD Cloud shared API")
            self.assertEqual(status["inference_runtime"], "OpenAI-compatible HTTPS API")

    def test_public_status_identifies_framework_and_local_inference_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)

            status = agent.status()

            self.assertEqual(status["agent_framework"], "LangChain Core")
            self.assertEqual(status["inference_runtime"], "vLLM OpenAI-compatible")
            self.assertEqual(status["core_inference_location"], "same-instance loopback")

    def test_answer_includes_evidence_permission_and_memory_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "agent.md").write_text(
                "PrivateOps Agent is designed for local RAG, tool permission review, and AMD ROCm deployment.",
                encoding="utf-8",
            )
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")

            response = agent.ask("Remember that my demo focuses on permission review and ROCm.")

            self.assertIn("permission", response.answer.lower())
            self.assertEqual(response.permission.level, "safe")
            self.assertEqual(response.evidence[0].source, "agent.md")
            self.assertIn("demo_focus", response.memory_updates)

    def test_response_language_only_changes_the_inference_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")

            class CapturingProvider:
                name = "capturing-provider"

                def __init__(self):
                    self.prompt = ""

                def complete(self, prompt, evidence, memory, execution_context=None):
                    self.prompt = prompt
                    return "已用中文回答"

            provider = CapturingProvider()
            agent.provider = provider
            original_prompt = "Explain the local permission model."

            response = agent.ask(original_prompt, response_language="zh-CN")

            self.assertEqual(provider.prompt, original_prompt + "\n\n请用中文回答。")
            self.assertEqual(response.answer, "已用中文回答")
            self.assertEqual(agent.audit_trail()[0]["prompt"], original_prompt)

    def test_model_receives_permission_plan_and_real_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (root / "README.md").write_text("PrivateOps", encoding="utf-8")
            agent = PrivateOpsAgent(
                knowledge_dir=knowledge,
                state_dir=root / "state",
                workspace_dir=root,
            )

            class ContextCapturingProvider:
                name = "context-capturing-provider"

                def __init__(self):
                    self.execution_context = {}

                def complete(self, prompt, evidence, memory, execution_context=None):
                    self.execution_context = execution_context or {}
                    return "Model used the inspected execution context."

            provider = ContextCapturingProvider()
            agent.provider = provider

            response = agent.ask("Review the private workspace inventory.")

            self.assertEqual(response.answer, "Model used the inspected execution context.")
            self.assertEqual(provider.execution_context["permission"]["level"], "safe")
            self.assertEqual(len(provider.execution_context["plan"]), 3)
            self.assertEqual(provider.execution_context["tool_results"][0]["name"], "workspace_inventory")
            self.assertEqual(provider.execution_context["tool_results"][0]["status"], "completed")

    def test_deterministic_provider_answers_in_selected_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "agent.md").write_text("PrivateOps keeps local evidence visible.", encoding="utf-8")
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")

            english = agent.ask("Explain local evidence.", response_language="en")
            chinese = agent.ask("Explain local evidence.", response_language="zh-CN")

            self.assertTrue(english.answer.startswith("PrivateOps answer:"))
            self.assertTrue(chinese.answer.startswith("PrivateOps 回答："))

    def test_rocm_profile_can_be_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")

            saved = agent.save_rocm_profile(
                gpu_name="AMD Radeon RX 7900 XTX",
                rocm_version="7.2.4",
                model_endpoint="http://127.0.0.1:8080/v1/chat/completions",
                notes="Validated in Radeon Cloud.",
            )
            loaded = agent.load_rocm_profile()

            self.assertEqual(saved.gpu_name, loaded.gpu_name)
            self.assertEqual(loaded.rocm_version, "7.2.4")
            self.assertIn("Radeon Cloud", loaded.notes)

    def test_submission_audit_returns_plan_tool_result_metrics_and_audit_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "rules.md").write_text("A submission needs source, tests, and Radeon proof.", encoding="utf-8")
            (root / "README.md").write_text("PrivateOps", encoding="utf-8")
            (root / "requirements.txt").write_text("", encoding="utf-8")
            (root / "submission").mkdir()
            (root / "tests").mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)

            response = agent.ask("Audit this project for hackathon submission readiness")

            self.assertEqual([step.status for step in response.plan], ["completed", "completed", "completed"])
            self.assertEqual(response.tool_results[0].name, "submission_readiness")
            self.assertEqual(response.tool_results[0].status, "completed")
            self.assertGreaterEqual(response.metrics["latency_ms"], 0)
            self.assertTrue(response.audit_id.startswith("audit-"))


if __name__ == "__main__":
    unittest.main()
