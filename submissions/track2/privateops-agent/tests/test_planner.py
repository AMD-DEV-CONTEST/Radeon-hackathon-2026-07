import unittest

from privateops.planner import Planner


class PlannerTests(unittest.TestCase):
    def test_startup_question_selects_real_startup_inventory(self):
        steps = Planner().plan("查看一下本机的开机自启有啥？")

        self.assertEqual([step.tool_name for step in steps if step.kind == "tool"], ["startup_inventory"])

    def test_comprehensive_check_selects_all_read_only_system_tools(self):
        steps = Planner().plan("全面检查我的电脑，只读，不要修改任何设置。")

        self.assertEqual(
            [step.tool_name for step in steps if step.kind == "tool"],
            [
                "system_overview",
                "startup_inventory",
                "process_inventory",
                "service_inventory",
                "scheduled_task_inventory",
                "network_listener_inventory",
                "security_status",
            ],
        )

    def test_submission_audit_produces_visible_retrieval_tool_and_report_steps(self):
        steps = Planner().plan("Audit this project for hackathon submission readiness and run safe checks")

        self.assertEqual([step.kind for step in steps], ["retrieve", "tool", "synthesize"])
        self.assertEqual(steps[1].tool_name, "submission_readiness")
        self.assertTrue(all(step.status == "pending" for step in steps))


if __name__ == "__main__":
    unittest.main()
