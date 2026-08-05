"""Core agent orchestrator.

Owns the tool-calling / planning / memory loop:
1. Receive an alert or analyst question
2. Retrieve relevant context via src.rag.retriever
3. Decide which tools to call for enrichment (handled by the LLM's tool_calls)
4. Call the LLM with context + tool results
5. Return a triage recommendation, keeping conversation state in memory
"""
from src.orchestrator.memory import ConversationMemory
from src.orchestrator.permissions import PermissionManager
from src.rag.retriever import KnowledgeRetriever
from src.tools.wazuh_tool import WazuhTool
from src.tools.suricata_tool import SuricataTool
from src.tools.greenbone_tool import GreenboneTool


class SOCTriageAgent:
    def __init__(self, mode: str = "demo", tool_mode: str = None, llm_client=None):
        self.mode = mode
        # Tool data source defaults to "demo" (sample data) independent of the
        # LLM backend, since live Wazuh/Suricata/Greenbone connectors are not
        # yet implemented (see PROJECT_SPEC.md). This lets --mode live exercise
        # the real GPU-served model with representative sample alert data.
        self.tool_mode = tool_mode or "demo"
        self.memory = ConversationMemory()
        self.permissions = PermissionManager()
        self.retriever = KnowledgeRetriever()

        self.tools = {
            t.name: t
            for t in [WazuhTool(mode=self.tool_mode), SuricataTool(mode=self.tool_mode), GreenboneTool(mode=self.tool_mode)]
        }

        if llm_client is None:
            if mode == "demo":
                from src.llm.mock_client import MockLLMClient
                llm_client = MockLLMClient()
            else:
                from src.llm.client import LocalLLMClient
                llm_client = LocalLLMClient()
        self.llm = llm_client

    def _tool_schemas(self) -> list[dict]:
        return [t.as_tool_schema() for t in self.tools.values()]

    def _call_tool(self, name: str, arguments: dict):
        tool = self.tools[name]
        if hasattr(tool, "get_recent_alerts"):
            return tool.get_recent_alerts(**arguments)
        if hasattr(tool, "get_vulns_for_host"):
            return tool.get_vulns_for_host(**arguments)
        raise ValueError(f"Don't know how to call tool {name}")

    def triage_alert(self, alert: dict, user_role: str = "analyst") -> dict:
        """Given a raw alert dict, return a triage recommendation."""
        alert = self.permissions.redact(alert, user_role)

        query = alert.get("rule", {}).get("description", "") or str(alert)
        kb_hits = self.retriever.retrieve(query, top_k=3)
        kb_context = "\n\n".join(f"[{h['source']}] {h['text']}" for h in kb_hits)

        self.memory.add("user", f"Triage this alert:\n{alert}\n\nRelevant knowledge base context:\n{kb_context}")

        messages = self.memory.as_messages()
        response = self.llm.chat(messages, tools=self._tool_schemas())

        if response.get("tool_calls"):
            for call in response["tool_calls"]:
                import json as _json
                name = call["function"]["name"]
                args = _json.loads(call["function"]["arguments"])
                print(f"  [tool call] {name}({args})")
                result = self._call_tool(name, args)
                self.memory.add("tool", f"{name} result: {result}")

            response = self.llm.chat(self.memory.as_messages(), tools=self._tool_schemas())

        self.memory.add("assistant", response["content"])

        return {
            "alert": alert,
            "knowledge_base_context": kb_hits,
            "recommendation": response["content"],
        }

    def run(self):
        """Interactive demo loop: triage each sample alert in sequence."""
        from src.tools.wazuh_tool import WazuhTool
        alerts = WazuhTool(mode=self.tool_mode).get_recent_alerts(limit=5)

        for alert in alerts:
            print("=" * 60)
            print(f"Alert: {alert['rule']['description']} (level {alert['rule']['level']})")
            result = self.triage_alert(alert)
            print(f"\nRecommendation:\n{result['recommendation']}\n")
