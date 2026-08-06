# -*- coding: utf-8 -*-
"""
underwriting/agent.py — Underwriting Risk Agent & Streaming Follow-up

Aligns with spec.md "Underwriting Agent & Streaming Follow-up": provides
multi-turn follow-up capability based on already-generated underwriting reports,
with streaming output and separate real-time appending of thinking chain
(reasoning_content) and body (content).

Design (mirrors agent/agent.py:stream_followup pattern, reuses urllib + SSE parsing):
- Three-level fallback for system_content (aligned with agent.agent.stream_followup,
  but all three levels use streaming LLM without tool calls):
  1. Batch memory first: ``get_store().get_batch_report(session_id)`` hit and ok ->
     use ``_format_batch_context`` to build context;
  2. Fallback to single report memory: ``get_store().get_last_report(session_id)``
     hit and ok -> use ``_format_report_context`` to build context;
  3. None: generic prompt "You are an intelligent underwriting risk assistant.
     Answer the user's questions in concise English.".
- Stream POST to ``cfg.MODEL_URL``, parse SSE ``data:`` lines line by line,
  separating ``reasoning_content`` (yield ``{"type":"reasoning","text":rc}``)
  from ``content`` (yield ``{"type":"content","text":cc}``), end with
  ``{"type":"done"}``, on error yield ``{"type":"error","text":...}``.
- ``max_tokens`` uses ``max(cfg.LLM_MAX_TOKENS, 8192)`` floor to prevent Qwen3
  thinking chain from exhausting the budget leaving no room for content
  (consistent with agent.agent.stream_followup).

This generator does not call any underwriting tools (extract/abnormality/risk/search);
it only answers based on the stored structured report.
"""

import json
import urllib.request
import urllib.error

import underwriting  # noqa: F401  inject into sys.path
from underwriting import config as cfg
from underwriting.memory import get_store

# build_llm is only used by the synchronous answer_followup; degrades to None
# if langchain_openai is unavailable
try:
    from langchain_openai import ChatOpenAI
except Exception:  # noqa: F841  pragma: no cover
    ChatOpenAI = None


def build_llm(streaming: bool = False):
    """Build a ChatOpenAI connected to the local endpoint (for answer_followup sync version).

    Consistent with agent.agent.build_llm; returns None if langchain_openai is
    not installed, and answer_followup degrades accordingly (returns prompt
    text instead of crashing).
    """
    if ChatOpenAI is None:
        return None
    return ChatOpenAI(
        model=cfg.MODEL_ID,
        base_url=cfg.MODEL_BASE_URL,
        api_key=cfg.MODEL_API_KEY,
        temperature=cfg.LLM_TEMPERATURE,
        timeout=cfg.LLM_TIMEOUT,
        streaming=streaming,
        model_kwargs={"chat_template_kwargs": {"enable_thinking": False}},
    )


# ----------------------------------------------------------------------------
# Context formatting: compress structured underwriting report into text for follow-up reference
# ----------------------------------------------------------------------------

def _format_report_context(report: dict) -> str:
    """Compress a stored single underwriting report into text context for follow-up reference.

    Includes: patient info, report type, exam date, report summary, overall risk,
    recommendation and reason, abnormality details, risk details, medical reference
    summary. All field access uses defensive ``.get``; report structure anomalies
    should not crash.

    Mirrors agent.agent._format_claim_context style (structured -> text line list).
    """
    if not report:
        return ""

    lines = []
    patient = report.get("patient", {}) or {}
    lines.append(
        f"Report type: {report.get('report_type', '')} | "
        f"Patient: {patient.get('name', '')} {patient.get('gender', '')} "
        f"Age {patient.get('age', '')} | Exam date: {report.get('exam_date', '')}"
    )

    summary = report.get("summary", "")
    if summary:
        lines.append(f"Report summary: {summary}")

    # Overall risk and recommendation
    overall_risk = report.get("overall_risk", "")
    recommendation = report.get("recommendation", "")
    lines.append(
        f"Overall risk level: {overall_risk} | Recommendation: {recommendation}"
    )
    recommendation_reason = report.get("recommendation_reason", "")
    if recommendation_reason:
        lines.append(f"Recommendation reason: {recommendation_reason}")
    overall_reasoning = report.get("overall_reasoning", "")
    if overall_reasoning:
        lines.append(f"Comprehensive assessment: {overall_reasoning}")

    # Abnormality details
    abnormalities = report.get("abnormalities", []) or []
    if abnormalities:
        lines.append(f"Abnormalities ({len(abnormalities)} items):")
        for a in abnormalities:
            if not isinstance(a, dict):
                continue
            lines.append(
                f"  - {a.get('name', '')} | {a.get('type', '')} | "
                f"Severity {a.get('severity_hint', '')} | Evidence: {a.get('evidence', '')}"
            )
            detail = a.get("detail", "")
            if detail:
                lines.append(f"      Detail: {detail}")
    else:
        lines.append("Abnormalities: no significant abnormalities")

    # Risk details
    risks = report.get("risks", []) or []
    if risks:
        lines.append(f"Disease risks ({len(risks)} items):")
        for r in risks:
            if not isinstance(r, dict):
                continue
            factors = ", ".join(r.get("risk_factors", []) or [])
            lines.append(
                f"  - {r.get('name', '')} | Risk level {r.get('risk_level', '')} | "
                f"Risk factors: {factors} | Evidence: {r.get('evidence', '')}"
            )
            reasoning = r.get("reasoning", "")
            if reasoning:
                lines.append(f"      Reasoning: {reasoning}")

    # Medical reference summary (only list first few titles/sources to avoid overly long context)
    references = report.get("references", []) or []
    if references:
        lines.append(f"Medical references ({len(references)} items, showing first 5):")
        for ref in references[:5]:
            if not isinstance(ref, dict):
                continue
            lines.append(
                f"  - [{ref.get('source', '')}] {ref.get('title', '')}"
                f" (Disease: {ref.get('disease', '')})"
            )

    # Stage degradation annotations
    if report.get("abnormality_error"):
        lines.append(f"(Note: abnormality detection degraded - {report['abnormality_error']})")
    if report.get("risk_error"):
        lines.append(f"(Note: risk assessment degraded - {report['risk_error']})")
    search_errors = report.get("search_errors", []) or []
    if search_errors and not references:
        lines.append("(Note: online search is currently unavailable, medical evidence is for reference only)")

    return "\n".join(lines)


def _format_batch_context(batch: dict) -> str:
    """Compress batch underwriting results into text context for follow-up reference.

    Output includes: aggregate summary (from ``aggregate.summary_text``), per-report
    details (success/duplicate/failure, one line each), and brief failure/duplicate
    count lines. All field access uses defensive ``.get``; batch structure anomalies
    should not crash.

    Mirrors agent.agent._format_batch_context style; list key uses ``reports``
    (underwriting semantics), also compatible with ``invoices`` (defensive for old structure).
    """
    if not batch:
        return ""

    lines = []

    aggregate = batch.get("aggregate", {}) or {}
    summary_text = aggregate.get("summary_text", "")
    if summary_text:
        lines.append("[Batch Underwriting Summary]")
        lines.append(summary_text)
        lines.append("")
    else:
        # Fallback: build a one-line summary from aggregate count fields
        total = aggregate.get("total_reports", 0)
        ok_cnt = aggregate.get("success_count", 0)
        fail_cnt = aggregate.get("failed_count", 0)
        dup_cnt = aggregate.get("duplicate_count", 0)
        if total:
            lines.append("[Batch Underwriting Summary]")
            lines.append(
                f"Total {total} reports | Success {ok_cnt} | Failed {fail_cnt} | Duplicates {dup_cnt}"
            )
            lines.append("")

    lines.append("[Per-Report Details]")
    # Compatible with reports / invoices key names
    reports = batch.get("reports", []) or batch.get("invoices", []) or []
    for i, rep in enumerate(reports):
        if not isinstance(rep, dict):
            continue
        filename = rep.get("filename", "")
        # Duplicate reports take priority (even if ok=True, treat as duplicate)
        if rep.get("duplicate_of") is not None:
            duplicate_of = rep.get("duplicate_of")
            lines.append(f"  {i+1}. {filename} | ⚠️ Duplicate (same as report #{duplicate_of+1})")
            continue
        # Failed reports
        if not rep.get("ok"):
            stage = rep.get("stage", "") or ""
            message = rep.get("message", "") or ""
            lines.append(f"  {i+1}. {filename} | ❌ Processing failed ({stage}): {message}")
            continue
        # Success and non-duplicate: show patient/report type/overall risk/recommendation
        patient = rep.get("patient", {}) or {}
        report_type = rep.get("report_type", "")
        overall_risk = rep.get("overall_risk", "")
        recommendation = rep.get("recommendation", "")
        # If batch item embeds full result, patient may be empty; try from result
        if not patient and isinstance(rep.get("result"), dict):
            patient = rep["result"].get("patient", {}) or {}
            report_type = report_type or rep["result"].get("report_type", "")
            overall_risk = overall_risk or rep["result"].get("overall_risk", "")
            recommendation = recommendation or rep["result"].get("recommendation", "")
        name = patient.get("name", "") if isinstance(patient, dict) else ""
        lines.append(
            f"  {i+1}. {filename} | {report_type} | Patient {name} | "
            f"Overall risk {overall_risk} | Recommendation {recommendation}"
        )

    errors = batch.get("errors", []) or []
    duplicates = batch.get("duplicates", []) or []
    if errors or duplicates:
        lines.append("")
        parts = []
        if errors:
            parts.append(f"{len(errors)} failed")
        if duplicates:
            parts.append(f"{len(duplicates)} duplicates")
        lines.append("(" + ", ".join(parts) + ")")

    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Synchronous follow-up (backup, non-streaming)
# ----------------------------------------------------------------------------

def answer_followup(message: str, session_id: str = "default") -> str:
    """Answer follow-up questions based on the "already-generated underwriting report" in session memory (sync version).

    Three-level fallback (aligned with ``stream_followup``, all three use
    ``build_llm().invoke``, no tool calls):
    1. Batch memory first: if the session has batch underwriting results, answer based on batch context;
    2. Fallback to single report memory: if a single underwriting report exists, answer based on single context;
    3. None: use generic system prompt.

    Uses the structured report to answer directly, avoiding repeated calls to
    extract/abnormality/risk/search tools.
    If langchain_openai is unavailable or LLM call fails, returns degraded
    prompt text (does not raise).
    """
    # 1. Batch memory first
    batch = get_store().get_batch_report(session_id)
    if batch and batch.get("ok"):
        context = _format_batch_context(batch)
        prompt = (
            "The following are the batch underwriting report results completed in the current session "
            "(risk levels and recommendations are given by deterministic tools and are auditable):\n"
            f"{context}\n\n"
            "Please answer the user's question in concise English based on the above results. "
            "Do not fabricate abnormality indicators or adjust risk levels on your own:\n"
            f"User question: {message}"
        )
        llm = build_llm()
        if llm is None:
            return "(LLM not ready: langchain_openai unavailable, cannot answer follow-up.)"
        try:
            resp = llm.invoke(prompt)
            return getattr(resp, "content", "") or ""
        except Exception as e:
            return f"(LLM call failed: {e})"

    # 2. Fallback to single report memory
    report = get_store().get_last_report(session_id)
    if report and report.get("ok"):
        context = _format_report_context(report)
        prompt = (
            "The following is the underwriting report completed in the current session "
            "(risk level and recommendation are given by deterministic tools and are auditable):\n"
            f"{context}\n\n"
            "Please answer the user's question in concise English based on the above results. "
            "Do not fabricate abnormality indicators or adjust risk levels on your own:\n"
            f"User question: {message}"
        )
        llm = build_llm()
        if llm is None:
            return "(LLM not ready: langchain_openai unavailable, cannot answer follow-up.)"
        try:
            resp = llm.invoke(prompt)
            return getattr(resp, "content", "") or ""
        except Exception as e:
            return f"(LLM call failed: {e})"

    # 3. None: generic prompt
    llm = build_llm()
    if llm is None:
        return "(LLM not ready: langchain_openai unavailable, cannot answer follow-up.)"
    try:
        resp = llm.invoke(
            "You are an intelligent underwriting risk assistant. Answer the user's questions in concise English.\n"
            f"User question: {message}"
        )
        return getattr(resp, "content", "") or ""
    except Exception as e:
        return f"(LLM call failed: {e})"


# ----------------------------------------------------------------------------
# Streaming follow-up generator (core)
# ----------------------------------------------------------------------------

def stream_followup(message: str, session_id: str = "default"):
    """Streaming follow-up generator: streams LLM responses, separating Qwen3's thinking process from body.

    Three-level fallback for system_content (aligned with ``answer_followup``,
    but all three use streaming LLM, no tool calls):
    1. Batch memory first: if the session has batch underwriting results, answer based on batch context;
    2. Fallback to single report memory: if a single underwriting report exists, answer based on single context;
    3. None: use generic system prompt.

    Stream POST to ``cfg.MODEL_URL``, parse SSE line by line, separating
    ``reasoning_content`` (thinking) from ``content`` (body) fields.

    yield event format (dict):
        - {"type": "reasoning", "text": <thinking chunk>}  # Qwen3 thinking process increment
        - {"type": "content", "text": <body chunk>}        # body response increment
        - {"type": "done"}                                  # stream ended
        - {"type": "error", "text": <error message>}       # exception case

    This generator does not call any underwriting tools (extract/abnormality/risk/search);
    it only answers based on the stored structured report.
    """
    # 1. Batch memory first
    batch = get_store().get_batch_report(session_id)
    if batch and batch.get("ok"):
        context = _format_batch_context(batch)
        system_content = (
            "The following are the batch underwriting report results completed in the current session "
            "(risk levels and recommendations are given by deterministic tools and are auditable):\n"
            f"{context}\n\n"
            "Please answer the user's question in concise English based on the above results. "
            "Do not fabricate abnormality indicators or adjust risk levels on your own."
        )
    else:
        # 2. Fallback to single report memory
        report = get_store().get_last_report(session_id)
        if report and report.get("ok"):
            context = _format_report_context(report)
            system_content = (
                "The following is the underwriting report completed in the current session "
                "(risk level and recommendation are given by deterministic tools and are auditable):\n"
                f"{context}\n\n"
                "Please answer the user's question in concise English based on the above results. "
                "Do not fabricate abnormality indicators or adjust risk levels on your own."
            )
        else:
            # 3. None: generic prompt
            system_content = "You are an intelligent underwriting risk assistant. Answer the user's questions in concise English."

    # 第②层记忆：本会话的多轮对话历史，与核保报告上下文（第①层 system_content）叠加。
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
        # leaving no room for content (user sees only thinking, no body).
        # Consistent with agent.agent.stream_followup / ocr_tool, use max() floor
        # to leave enough room for thinking + body. In practice, complex follow-up
        # thinking chains can reach 4k+ tokens; 8192 floor ensures body can still
        # be generated after thinking.
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
    # Simple interactive self-test: python -m underwriting.agent
    sid = "cli"
    print("Intelligent Underwriting Risk Assistant (type exit to quit, thinking chain streams in real-time)")
    while True:
        try:
            q = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in ("exit", "quit"):
            break
        print("Assistant>", end=" ", flush=True)
        for ev in stream_followup(q, session_id=sid):
            t = ev.get("type")
            if t == "reasoning":
                # Thinking chain in gray (terminal may not support ANSI, just for distinction)
                print(f"\033[90m{ev.get('text', '')}\033[0m", end="", flush=True)
            elif t == "content":
                print(ev.get("text", ""), end="", flush=True)
            elif t == "done":
                print("")
            elif t == "error":
                print(f"\n[Error] {ev.get('text', '')}")
