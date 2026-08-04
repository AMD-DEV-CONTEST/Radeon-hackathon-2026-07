from __future__ import annotations

from privateops.models import PlanStep


class Planner:
    def plan(self, message: str) -> list[PlanStep]:
        text = message.lower()
        tools = self._select_tools(text)
        steps = [
            PlanStep("step-1", "Retrieve relevant local evidence", "retrieve"),
        ]
        for index, tool_name in enumerate(tools, 2):
            steps.append(PlanStep(f"step-{index}", f"Run read-only tool: {tool_name}", "tool", tool_name=tool_name))
        steps.append(PlanStep(f"step-{len(steps) + 1}", "Synthesize a cited response", "synthesize"))
        return steps

    @staticmethod
    def _select_tools(text: str) -> list[str]:
        comprehensive_terms = {"全面检查", "整机检查", "检查我的电脑", "检查电脑", "whole computer", "full system", "computer health"}
        if any(term in text for term in comprehensive_terms):
            return [
                "system_overview",
                "startup_inventory",
                "process_inventory",
                "service_inventory",
                "scheduled_task_inventory",
                "network_listener_inventory",
                "security_status",
            ]
        routes = [
            ("startup_inventory", {"startup", "autostart", "boot app", "开机自启", "自启动", "启动项"}),
            ("process_inventory", {"process", "running program", "进程", "正在运行"}),
            ("service_inventory", {"service", "services", "windows 服务", "系统服务"}),
            ("scheduled_task_inventory", {"scheduled task", "task scheduler", "计划任务", "定时任务"}),
            ("system_overview", {"system overview", "system info", "hardware", "cpu", "gpu", "memory", "disk", "系统概况", "系统信息", "硬件", "显卡", "内存", "磁盘"}),
            ("network_listener_inventory", {"listening port", "listening ports", "network listener", "监听端口", "端口监听"}),
            ("security_status", {"defender", "firewall", "security status", "防火墙", "安全状态", "杀毒"}),
        ]
        selected = [name for name, terms in routes if any(term in text for term in terms)]
        if selected:
            return selected
        if any(term in text for term in {"submission", "hackathon", "readiness", "提交", "比赛"}):
            return ["submission_readiness"]
        return ["workspace_inventory"]
