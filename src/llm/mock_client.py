"""Mock LLM client for local development — no GPU/API access needed.

Simulates an OpenAI-compatible chat response with fake but structurally
correct tool_calls, so the orchestrator loop can be built and tested end
to end before a real backend (Token Factory or local vLLM) is available.

Swap LocalLLMClient -> MockLLMClient in src/orchestrator/agent.py during
development; swap back before the final Radeon GPU demo.
"""
import json


class MockLLMClient:
    def __init__(self, *args, **kwargs):
        self._call_count = 0

    def chat(self, messages: list[dict], tools: list[dict] = None) -> dict:
        """Return a canned response. First call requests a tool; second
        call (after tool result is appended) returns a final answer.
        """
        self._call_count += 1

        if self._call_count == 1 and tools:
            # Simulate the model deciding to call the first available tool
            tool_name = tools[0]["function"]["name"] if tools else "get_recent_alerts"
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "mock_call_1",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps({"limit": 5}),
                        },
                    }
                ],
            }

        # Final turn: canned triage recommendation
        return {
            "role": "assistant",
            "content": (
                "[MOCK RESPONSE] Based on the retrieved alerts, this looks like "
                "a potential brute-force attempt (MITRE T1110). Recommend: "
                "1) block source IP at firewall, 2) check for successful logins "
                "from that IP, 3) escalate if host is in the DMZ."
            ),
            "tool_calls": None,
        }
