from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


class vLLMClient:
    """Thin OpenAI-compatible client pointing at a vLLM-on-ROCm server.

    Used by `agent_step` for the ReAct reasoning loop. Default model is
    Llama-3-8B-Instruct (decision D2); Qwen-2.5-7B can be substituted by
    changing `model` at construction time.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000/v1",
        model: str = "meta-llama/Llama-3-8B-Instruct",
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: float = 30.0,
        transport: Any | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        transport_kwargs = {"transport": transport} if transport is not None else {}
        self._client = httpx.Client(timeout=timeout, **transport_kwargs)

    def chat(self, messages: list[dict]) -> str:
        """Return the assistant message content for a chat completion."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"content-type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def close(self) -> None:
        self._client.close()


@dataclass
class ScriptedReasoner:
    """Deterministic reasoner for tests and offline demo scripts.

    `steps` is a list of dicts; each is either:
      {"tool": <tool_name>, "args": <positional arg>}
      {"final": <answer string>}

    Each call to `step` pops the next scripted action. Lets tests run
    without a vLLM server and lets the demo replay deterministically.
    """

    steps: list[dict]
    _idx: int = field(default=0, repr=False)

    def step(self, tools: dict, history: list[dict]) -> dict:
        if self._idx >= len(self.steps):
            return {"final": "<no more scripted steps>"}
        action = self.steps[self._idx]
        self._idx += 1
        if "final" in action:
            return {"final": action["final"]}
        tool_name = action["tool"]
        tool_arg = action["args"]
        tool_fn = tools[tool_name]["func"]
        result = tool_fn(tool_arg)
        return {"tool": tool_name, "args": tool_arg, "tool_result": result}


def agent_step(
    system: str,
    user: str,
    tools: dict,
    llm,
    max_iters: int = 5,
) -> str:
    """Minimal ReAct loop.

    1. Prompt LLM/reasoner with system + user + tool descriptions.
    2. Parse output for tool call OR final answer.
    3. If tool call: dispatch and append result to history.
    4. Repeat up to `max_iters`.
    5. Return final answer string.

    For a vLLMClient the prompt/response roundtrip is delegated to llm.chat;
    for ScriptedReasoner the loop is driven by llm.step(tools, history).
    """
    history: list[dict] = []
    tool_descriptions = "\n".join(
        f"- {name}: {spec['description']}" for name, spec in tools.items()
    )
    system_prompt = (
        f"{system}\n\nYou may use these tools:\n{tool_descriptions}\n\n"
        "Respond with either a tool call or `FINAL: <answer>`."
    )

    if hasattr(llm, "step"):
        for _ in range(max_iters):
            action = llm.step(tools=tools, history=history)
            if "final" in action:
                return action["final"]
            history.append(action)
        return "<max_iters reached>"

    # vLLMClient path
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]
    for _ in range(max_iters):
        out = llm.chat(messages)
        if out.startswith("FINAL:"):
            return out[len("FINAL:"):].strip()
        # naive tool-call parse: "<tool>: <arg>"
        if ":" in out:
            tool_name, arg = out.split(":", 1)
            tool_name = tool_name.strip()
            arg = arg.strip()
            if tool_name in tools:
                result = tools[tool_name]["func"](arg)
                messages.append({"role": "assistant", "content": out})
                messages.append(
                    {"role": "user", "content": f"TOOL_RESULT: {result}"}
                )
                continue
        return out
    return "<max_iters reached>"
