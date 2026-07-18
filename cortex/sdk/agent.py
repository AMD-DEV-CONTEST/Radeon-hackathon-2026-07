from __future__ import annotations

from collections.abc import Callable

from cortex.sdk.client import CortexClient
from cortex.sdk.exceptions import map_node_error
from cortex.sdk.langchain_adapter import CortexRetriever
from cortex.sdk.llm import agent_step

_DEFAULT_TOOLS_BUILDER: Callable | None = None


class CortexAgent:
    """Runnable agent: client + retriever + reasoner + persona.

    `run_task(task)` runs the ReAct loop in cortex.sdk.llm.agent_step
    using CortexRetriever + CortexPublishTool. The persona string is
    used verbatim as the LangChain system prompt base.
    """

    def __init__(
        self,
        client: CortexClient,
        retriever: CortexRetriever,
        llm,
        persona: str,
        tools_builder: Callable | None = None,
        max_iters: int = 5,
    ):
        self.client = client
        self.retriever = retriever
        self.llm = llm
        self.persona = persona
        self.tools_builder = tools_builder or _default_tools_builder
        self.max_iters = max_iters

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
            )
        except Exception as exc:
            raise map_node_error(exc) from exc


def _default_tools_builder(retriever: CortexRetriever, client: CortexClient) -> dict:
    # Late import to avoid a circular dep at module load time.
    from cortex.sdk.langchain_adapter import CortexPublishTool

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
