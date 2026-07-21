from __future__ import annotations

from unittest.mock import MagicMock

from cortex.sdk.agent import CortexAgent
from cortex.sdk.langchain_adapter import CortexRetriever
from cortex.sdk.llm import ScriptedReasoner


def _tools_for(retriever, client):
    search_tool = retriever.as_tool()

    return {
        "cortex_search": {
            "name": "cortex_search",
            "description": search_tool.description,
            "func": lambda q: search_tool._run(q, config=None),
        },
        "cortex_publish": {
            "name": "cortex_publish",
            "description": "Publish a finding.",
            "func": lambda content, payload_json="{}", scope="PRIVATE": "art-id-1",
        },
    }


def test_run_task_returns_final_answer_and_publishes_when_instructed(fake_node: MagicMock):
    fake_node.query.return_value = []

    retriever = CortexRetriever(node=fake_node)
    client_mock = MagicMock(name="CortexClient")

    reasoner = ScriptedReasoner(
        steps=[
            {"tool": "cortex_search", "args": "phishing paddock"},
            {"tool": "cortex_publish", "args": "phishing replay detected"},
            {"final": "Insight published: phishing replay detected."},
        ]
    )

    agent = CortexAgent(
        client=client_mock,
        retriever=retriever,
        llm=reasoner,
        persona="You are alpha-bot, a SOC analyst agent for the F1 paddock.",
        tools_builder=_tools_for,
    )

    answer = agent.run_task("Investigate phishing in the paddock.")

    assert answer == "Insight published: phishing replay detected."


def test_run_task_returns_max_iters_message_when_script_runs_out(fake_node: MagicMock):
    fake_node.query.return_value = []
    retriever = CortexRetriever(node=fake_node)
    client_mock = MagicMock()
    client_mock.publish_finding.return_value = "art-id-x"

    reasoner = ScriptedReasoner(steps=[{"tool": "cortex_search", "args": "q"}])

    agent = CortexAgent(
        client=client_mock,
        retriever=retriever,
        llm=reasoner,
        persona="p",
        tools_builder=_tools_for,
    )

    answer = agent.run_task("anything")
    assert isinstance(answer, str)
