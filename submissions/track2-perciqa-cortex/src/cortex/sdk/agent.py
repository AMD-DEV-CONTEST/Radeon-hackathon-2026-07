from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from cortex.sdk.client import CortexClient
from cortex.sdk.exceptions import map_node_error
from cortex.sdk.llm import agent_step
from cortex.sdk.memory import ConversationMemory

if TYPE_CHECKING:
    from cortex.sdk.langchain_adapter import CortexRetriever

_DEFAULT_TOOLS_BUILDER: Callable | None = None


class CortexAgent:
    """Runnable agent: client + retriever + reasoner + persona + memory.

    `run_task(task)` runs the ReAct loop in cortex.sdk.llm.agent_step
    using CortexRetriever + CortexPublishTool. The persona string is
    used verbatim as the LangChain system prompt base.

    `chat(user_input)` appends to conversational memory, runs the
    ReAct loop, and stores the response.
    """

    def __init__(
        self,
        client: CortexClient,
        retriever: CortexRetriever,
        llm,
        persona: str,
        tools_builder: Callable | None = None,
        max_iters: int = 5,
        memory: ConversationMemory | None = None,
    ):
        self.client = client
        self.retriever = retriever
        self.llm = llm
        self.persona = persona
        self.tools_builder = tools_builder or _default_tools_builder
        self.max_iters = max_iters
        self.memory = memory or ConversationMemory()

    def _build_tools(self) -> dict:
        return self.tools_builder(self.retriever, self.client)

    def run_task(self, task: str) -> str:
        try:
            tools = self._build_tools()
            return agent_step(
                system=self.persona,
                user=task,
                tools=tools,
                llm=self.llm,
                max_iters=self.max_iters,
                memory=self.memory,
            )
        except Exception as exc:
            raise map_node_error(exc) from exc

    def chat(self, user_input: str) -> str:
        self.memory.add_turn("user", user_input)
        response = self.run_task(user_input)
        self.memory.add_turn("assistant", response)
        return response


def _default_tools_builder(retriever: object, client: CortexClient) -> dict:
    # Late imports: langchain_adapter is an optional [sdk] dependency.
    from cortex.sdk.langchain_adapter import CortexPublishTool, CortexRetriever  # noqa: F401

    search_tool = retriever.as_tool()
    publish_tool = CortexPublishTool(node=client.node)

    def search_fn(q: str) -> str:
        return search_tool._run(q, config=None)

    def publish_fn(content: str, payload_json: str = "{}", scope: str = "PRIVATE") -> str:
        return publish_tool._run(content=content, payload_json=payload_json, scope=scope)

    return {
        "cortex_search": {
            "name": "cortex_search",
            "description": search_tool.description,
            "func": search_fn,
        },
        "cortex_publish": {
            "name": "cortex_publish",
            "description": "Publish a finding to the Cortex memory fabric.",
            "func": publish_fn,
        },
    }


_DEFAULT_TOOLS_BUILDER = _default_tools_builder
