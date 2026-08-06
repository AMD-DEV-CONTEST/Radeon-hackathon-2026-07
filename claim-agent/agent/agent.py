# -*- coding: utf-8 -*-
"""
agent/agent.py — LangChain 1.x Smart Claim Agent

Uses langchain.agents.create_agent (based on langgraph) to assemble a tool-calling Agent:
- LLM: ChatOpenAI connected to local OpenAI-compatible endpoint
- Tools: 4 business tools (OCR / verify / RAG / decision)
- Memory: langgraph InMemorySaver, isolated by thread_id (=session_id) for multi-turn conversations
- Prompt: strongly constrains the "extract -> verify -> search -> decide" workflow

The endpoint supports OpenAI function-calling, so tool-calling is used instead of ReAct.
Agent handles conversational interaction and follow-up; deterministic amount chain see agent/pipeline.py.
"""

import json
import urllib.request
import urllib.error

import agent  # noqa: F401  inject into sys.path
import config as cfg

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from tools.ocr_tool import invoice_ocr_tool
from tools.verify_tool import invoice_verify_tool
from tools.rag_tool import drug_catalog_rag_tool
from tools.decision_tool import claim_decision_tool
from agent.memory import get_store


SYSTEM_PROMPT = """You are the "Smart Claim Review Assistant", responsible for reviewing medical/drug invoices uploaded by users and providing claim decisions.

Available tools:
- invoice_ocr_tool(image_path): extract invoice fields and drug item details
- invoice_verify_tool(fpdm, fphm, date, code): verify invoice authenticity
- drug_catalog_rag_tool(drug_name): search drug reimbursement catalog for category/reimbursement ratio/self-pay/commercial innovative drug
- claim_decision_tool(verified, items): deterministically calculate reimbursable amounts and conclusion

Please strictly follow this workflow:
1. When receiving an invoice image path, call invoice_ocr_tool to extract fields and drug details;
2. Call invoice_verify_tool to verify authenticity; if verification fails, directly reject the claim with reasons and stop;
3. For each drug item, call drug_catalog_rag_tool to search the reimbursement catalog for category / in_catalog /
   commercial_innovative / self_pay_2 / reimburse_ratio / cap;
4. Assemble verified and per-item catalog info into items, call claim_decision_tool to calculate amounts and conclusion;
5. Summarize in English: invoice authenticity, per-item drugs, reimbursable amounts (medical/commercial insurance), overall conclusion and reasons.

Important constraints:
- Do not fabricate drug catalog information or calculate amounts on your own; rely entirely on tool returns;
- Amounts are determined by claim_decision_tool returns; do not mental-math;
- If the user is asking follow-up questions about an already-reviewed invoice (e.g. "why was a drug rejected" or "recalculate as Category B"),
  answer based on existing conclusions or only re-call claim_decision_tool; no need to repeat OCR and verification.
- IMPORTANT: ALL responses MUST be in English. Translate any Chinese content to English."""


_agent = None


def build_llm(streaming: bool = False) -> ChatOpenAI:
    """Build a ChatOpenAI connected to the local endpoint."""
    return ChatOpenAI(
        model=cfg.MODEL_ID,
        base_url=cfg.MODEL_BASE_URL,
        api_key=cfg.MODEL_API_KEY,
        temperature=cfg.LLM_TEMPERATURE,
        timeout=cfg.LLM_TIMEOUT,
        streaming=streaming,
        model_kwargs={"chat_template_kwargs": {"enable_thinking": False}},
    )


def get_agent():
    """Build and cache the Agent (process-level singleton with InMemorySaver)."""
    global _agent
    if _agent is None:
        _agent = create_agent(
            model=build_llm(),
            tools=[invoice_ocr_tool, invoice_verify_tool,
                   drug_catalog_rag_tool, claim_decision_tool],
            system_prompt=SYSTEM_PROMPT,
            checkpointer=InMemorySaver(),
        )
    return _agent


def chat(message: str, session_id: str = "default", image_path: str = None) -> str:
    """Single-turn conversation with the Agent (multi-turn memory via session_id). Returns assistant's final text."""
    user_text = message
    if image_path:
        user_text = f"{message}\n[Invoice image path]: {image_path}"

    config = {"configurable": {"thread_id": session_id}}
    result = get_agent().invoke({"messages": [{"role": "user", "content": user_text}]}, config=config)
    messages = result.get("messages", [])
    for m in reversed(messages):
        content = getattr(m, "content", "")
        if content and getattr(m, "type", "") in ("ai", "assistant"):
            return content
    return messages[-1].content if messages else ""


def _format_claim_context(result: dict) -> str:
    """Compress stored structured claim results into text context for follow-up reference."""
    extract = result.get("extract", {})
    verify = result.get("verify", {})
    decision = result.get("decision", {})
    lines = [
        f"Invoice No.: {extract.get('fphm', '')}, Invoice date: {extract.get('date', '')}",
        f"Authenticity verification: {'Passed' if verify.get('verified') else 'Failed'} ({verify.get('message', '')})",
        f"Conclusion: {decision.get('conclusion', '')}, Total amount {decision.get('total_amount', 0)}, "
        f"Total reimbursable {decision.get('total_reimbursable', 0)} "
        f"(Medical insurance {decision.get('total_medical_insurance', 0)} + Commercial insurance {decision.get('total_commercial', 0)})",
        "Per-item details:",
    ]
    for it in decision.get("items", []):
        lines.append(
            f"  - {it.get('name', '')}: Amount {it.get('amount', 0)}, Category {it.get('category', '')}, "
            f"Medical reimbursable {it.get('medical_reimbursable', 0)}, Commercial reimbursable {it.get('commercial_reimbursable', 0)}, "
            f"Reason: {it.get('reason', '')}"
        )
    return "\n".join(lines)


def _format_batch_context(batch_result: dict) -> str:
    """Compress batch invoice claim results into text context for follow-up reference.

    Output includes: aggregate summary (from ``aggregate.summary_text``), per-invoice
    details (success/duplicate/failure, one line each), and brief failure/duplicate
    count lines. All field access uses defensive ``.get``; batch structure anomalies
    should not crash.
    """
    if not batch_result:
        return ""

    lines = []

    aggregate = batch_result.get("aggregate", {}) or {}
    summary_text = aggregate.get("summary_text", "")
    if summary_text:
        lines.append("[Batch Review Summary]")
        lines.append(summary_text)
        lines.append("")

    lines.append("[Per-Invoice Details]")
    invoices = batch_result.get("invoices", []) or []
    for i, inv in enumerate(invoices):
        if not isinstance(inv, dict):
            continue
        filename = inv.get("filename", "")
        # Duplicate invoices take priority (even if ok=True, treat as duplicate)
        if inv.get("duplicate_of") is not None:
            duplicate_of = inv.get("duplicate_of")
            lines.append(f"  {i+1}. {filename} | ⚠️ Duplicate (same as #{duplicate_of+1})")
            continue
        # Failed invoices
        if not inv.get("ok"):
            stage = inv.get("stage", "") or ""
            message = inv.get("message", "") or ""
            lines.append(f"  {i+1}. {filename} | ❌ Processing failed ({stage}): {message}")
            continue
        # Success and non-duplicate
        extract = inv.get("extract", {}) or {}
        decision = inv.get("decision", {}) or {}
        fphm = extract.get("fphm", "")
        code = extract.get("code", "")
        conclusion = decision.get("conclusion", "")
        total_reimbursable = decision.get("total_reimbursable", 0)
        lines.append(
            f"  {i+1}. {filename} | Invoice No. {fphm} | Total amount {code} | "
            f"{conclusion} | Reimbursable {total_reimbursable}"
        )

    errors = batch_result.get("errors", []) or []
    duplicates = batch_result.get("duplicates", []) or []
    if errors or duplicates:
        lines.append("")
        parts = []
        if errors:
            parts.append(f"{len(errors)} failed")
        if duplicates:
            parts.append(f"{len(duplicates)} duplicates")
        lines.append("(" + ", ".join(parts) + ")")

    return "\n".join(lines)


def answer_followup(message: str, session_id: str = "default") -> str:
    """Answer follow-up questions based on the "already-reviewed invoice claim results" in session memory.

    Three-level fallback:
    1. Batch memory first: if the session has batch invoice claim results, answer based on batch context;
    2. Fallback to single invoice memory: if a single invoice claim result exists, answer based on single context;
    3. Fallback to generic Agent: may autonomously call tools (e.g. drug catalog search).

    Uses structured results to answer directly, avoiding repeated OCR/verification calls.
    """
    # 1. Batch memory first
    batch = get_store().get_batch_claim(session_id)
    if batch and batch.get("ok"):
        context = _format_batch_context(batch)
        prompt = (
            "The following are the batch invoice claim review results completed in the current session "
            "(all amounts calculated by deterministic rules, auditable):\n"
            f"{context}\n\n"
            "Please answer the user's question in concise English based on the above results. "
            "Do not fabricate catalog information or recalculate amounts:\n"
            f"User question: {message}"
        )
        resp = build_llm().invoke(prompt)
        return getattr(resp, "content", "") or ""

    # 2. Fallback to single invoice memory
    claim = get_store().get_last_claim(session_id)
    if claim and claim.get("ok"):
        context = _format_claim_context(claim)
        prompt = (
            "The following is the invoice claim review result completed in the current session "
            "(all amounts calculated by deterministic rules, auditable):\n"
            f"{context}\n\n"
            "Please answer the user's question in concise English based on the above results. "
            "Do not fabricate catalog information or recalculate amounts:\n"
            f"User question: {message}"
        )
        resp = build_llm().invoke(prompt)
        return getattr(resp, "content", "") or ""

    # 3. Fallback to generic Agent
    return chat(message, session_id=session_id)


def stream_followup(message: str, session_id: str = "default"):
    """Streaming follow-up generator: streams LLM responses, separating Qwen3's thinking process from body.

    Three-level fallback for messages (aligned with ``answer_followup``, but all three use streaming LLM, no tool calls):
    1. Batch memory first: if the session has batch invoice claim results, answer based on batch context;
    2. Fallback to single invoice memory: if a single invoice claim result exists, answer based on single context;
    3. None: use generic system prompt.

    Stream POST to ``cfg.MODEL_URL``, parse SSE line by line, separating ``reasoning_content`` (thinking)
    from ``content`` (body) fields.

    yield event format (dict):
        - {"type": "reasoning", "text": <thinking chunk>}  # Qwen3 thinking process increment
        - {"type": "content", "text": <body chunk>}        # body response increment
        - {"type": "done"}                                  # stream ended
        - {"type": "error", "text": <error message>}       # exception case

    This generator does not call any tools (OCR/verify/RAG/decision); it only answers based on stored structured results.
    """
    # 1. Batch memory first
    batch = get_store().get_batch_claim(session_id)
    if batch and batch.get("ok"):
        context = _format_batch_context(batch)
        system_content = (
            "The following are the batch invoice claim review results completed in the current session "
            "(all amounts calculated by deterministic rules, auditable):\n"
            f"{context}\n\n"
            "Please answer the user's question in concise English based on the above results. "
            "Do not fabricate catalog information or recalculate amounts."
        )
    else:
        # 2. Fallback to single invoice memory
        claim = get_store().get_last_claim(session_id)
        if claim and claim.get("ok"):
            context = _format_claim_context(claim)
            system_content = (
                "The following is the invoice claim review result completed in the current session "
                "(all amounts calculated by deterministic rules, auditable):\n"
                f"{context}\n\n"
                "Please answer the user's question in concise English based on the above results. "
                "Do not fabricate catalog information or recalculate amounts."
            )
        else:
            # 3. None: generic prompt
            system_content = "You are the Smart Claim Review Assistant. Answer the user's questions in concise English."

    # 第②层记忆：本会话的多轮对话历史，与理赔结果上下文（第①层 system_content）叠加。
    # 没有这层，每次追问独立，模型不记得上一轮问过什么。
    history = get_store().get_history(session_id)

    messages = [
        {"role": "system", "content": system_content},
    ] + history + [
        {"role": "user", "content": message},
    ]

    body = json.dumps({
        "model": cfg.MODEL_ID,
        "messages": messages,
        "temperature": cfg.LLM_TEMPERATURE,
        # Qwen3 and other thinking-chain models: reasoning_content consumes a lot
        # of tokens; the default 500 would let thinking chain exhaust the budget
        # leaving no room for content. Use max() floor to leave enough room for
        # thinking + body. Complex follow-up thinking chains can reach 4k+ tokens;
        # 8192 floor ensures body can still be generated after thinking.
        "max_tokens": max(cfg.LLM_MAX_TOKENS, 8192),
        "stream": True,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.MODEL_API_KEY}",
    }
    req = urllib.request.Request(cfg.MODEL_URL, data=body, headers=headers, method="POST")

    full_content_parts = []
    try:
        resp = urllib.request.urlopen(req, timeout=cfg.LLM_TIMEOUT)
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()  # strip "data:" prefix, compatible with "data: " and "data:"
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {}) or {}
            rc = delta.get("reasoning_content")
            if rc:
                yield {"type": "reasoning", "text": rc}
            cc = delta.get("content")
            if cc:
                full_content_parts.append(cc)
                yield {"type": "content", "text": cc}
        # 流式成功完成：把本轮问答存入对话历史，供下一轮追问使用（第②层记忆）。
        # reasoning_content 不存入历史（属内部思考，非对话内容）；出错时不存，避免脏数据。
        full_content = "".join(full_content_parts).strip()
        if full_content:
            get_store().add_history(session_id, "user", message)
            get_store().add_history(session_id, "assistant", full_content)
        yield {"type": "done"}
    except urllib.error.HTTPError as e:
        yield {"type": "error", "text": f"LLM request failed: HTTP {e.code}"}
    except Exception as e:
        yield {"type": "error", "text": f"LLM streaming call error: {e}"}



if __name__ == "__main__":
    # Simple interactive self-test: python -m agent.agent
    import sys
    sid = "cli"
    print("Smart Claim Assistant (type exit to quit)")
    while True:
        try:
            q = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in ("exit", "quit"):
            break
        print("Assistant>", chat(q, session_id=sid))
