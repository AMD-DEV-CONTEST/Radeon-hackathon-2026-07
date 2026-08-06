"""
ReAct Loop — Reason → Act → Observe → Reflect
Core agentic reasoning engine used by all specialist agents.
"""
import json
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable

from inference import qwen_client
from tools.registry import call_tool, TOOL_DEFINITIONS

MAX_ITERATIONS = 5   # prevent infinite loops


async def run_react_loop(
    system_prompt: str,
    initial_observation: str,
    available_tools: List[str],
    max_iterations: int = MAX_ITERATIONS,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute a full ReAct loop.

    Returns:
        {
          "final_answer": str,
          "reasoning_trace": List[str],
          "tools_used": List[str],
          "tokens_generated": int,
          "latency_ms": int,
        }
    """
    trace: List[str] = []
    tools_used: List[str] = []
    total_tokens = 0
    total_latency = 0
    iteration = 0

    # Build tool descriptions for the prompt
    tool_desc_lines = []
    for td in TOOL_DEFINITIONS:
        if td["name"] in available_tools:
            tool_desc_lines.append(f"- {td['name']}: {td['description']}")
    tool_descriptions = "\n".join(tool_desc_lines)

    # Context accumulates observations across iterations
    context = f"Initial Observation:\n{initial_observation}"
    if extra_context:
        context += f"\n\nExtra Context:\n{json.dumps(extra_context, indent=2)}"

    while iteration < max_iterations:
        iteration += 1

        react_prompt = f"""{system_prompt}

Available Tools:
{tool_descriptions}

{context}

Instructions:
- Think step by step about what you know and what you need.
- If you need more information, call a tool by responding with:
  ACTION: tool_name
  ARGS: {{"key": "value"}}
- If you have enough information to give a final answer, respond with:
  FINAL_ANSWER: your complete response here

IMPORTANT: Respond with EITHER an ACTION+ARGS block OR a FINAL_ANSWER. Nothing else."""

        result = await qwen_client.get_completion(
            system_prompt="You are a precise agentic reasoning system. Follow the ReAct format exactly.",
            user_prompt=react_prompt,
            max_tokens=1024,
            temperature=0.3,
        )

        total_tokens += result.get("tokens_generated", 0)
        total_latency += result.get("latency_ms", 0)
        raw = result.get("text", "").strip()

        trace.append(f"[Iteration {iteration}] Thinking...")

        # Parse FINAL_ANSWER
        final_match = re.search(r"FINAL_ANSWER:\s*(.+)", raw, re.DOTALL | re.IGNORECASE)
        if final_match:
            answer = final_match.group(1).strip()
            trace.append(f"[Iteration {iteration}] Final answer generated.")
            return {
                "final_answer": answer,
                "reasoning_trace": trace,
                "tools_used": tools_used,
                "tokens_generated": total_tokens,
                "latency_ms": total_latency,
                "raw_response": raw,
            }

        # Parse ACTION + ARGS
        action_match = re.search(r"ACTION:\s*(\w+)", raw, re.IGNORECASE)
        args_match = re.search(r"ARGS:\s*(\{.*?\})", raw, re.DOTALL | re.IGNORECASE)

        if action_match:
            tool_name = action_match.group(1).strip()
            args_raw = args_match.group(1).strip() if args_match else "{}"

            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                args = {}

            if tool_name in available_tools:
                trace.append(f"[Iteration {iteration}] Calling tool: {tool_name}")
                tools_used.append(tool_name)
                observation = await call_tool(tool_name, args)
                obs_str = json.dumps(observation, indent=2)[:800]  # truncate large outputs
                context += f"\n\nTool: {tool_name}\nObservation: {obs_str}"
                trace.append(f"[Iteration {iteration}] Observed result from {tool_name}")
            else:
                context += f"\n\nError: Tool '{tool_name}' is not available."
                trace.append(f"[Iteration {iteration}] Tool '{tool_name}' not available, correcting...")
        else:
            # Model produced neither ACTION nor FINAL_ANSWER — treat full response as answer
            trace.append(f"[Iteration {iteration}] Treating response as final answer.")
            return {
                "final_answer": raw,
                "reasoning_trace": trace,
                "tools_used": tools_used,
                "tokens_generated": total_tokens,
                "latency_ms": total_latency,
                "raw_response": raw,
            }

    # Max iterations reached — return whatever context we have
    trace.append("[Warning] Max iterations reached. Generating best-effort answer.")
    fallback = await qwen_client.get_completion(
        system_prompt="Summarize the following context into a helpful response for the user.",
        user_prompt=context,
        max_tokens=512,
        temperature=0.5,
    )
    total_tokens += fallback.get("tokens_generated", 0)
    total_latency += fallback.get("latency_ms", 0)

    return {
        "final_answer": fallback.get("text", "I need more information to help you."),
        "reasoning_trace": trace,
        "tools_used": tools_used,
        "tokens_generated": total_tokens,
        "latency_ms": total_latency,
        "raw_response": fallback.get("text", ""),
    }
