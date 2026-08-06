"""TriggerFlow five-step business flow orchestration: Insurance Q&A Agent.

Uses Agently TriggerFlow API to implement visible orchestration topology:
- Serial edges (flow.to): understand -> plan -> validate -> fetch -> answer_and_check -> finalize
- Fallback edges (flow.when): retry_plan -> plan, retry_answer -> answer_and_check
- Terminal edges (flow.when): blocked -> finalize

Fix P0-1: The project claimed to use TriggerFlow but did not use any TriggerFlow API at all.
Fix P1-1: Retry loops changed to flow.when() visible fallback edges, no longer hidden inside chunks.
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from agently import TriggerFlow, TriggerFlowRuntimeData

from src.agent.observation import ObservationCollector
from src.agent.pipeline import (
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_PARTIAL,
    step1_understand,
    step2_plan,
    step3_validate,
    step4_fetch,
    step5_answer,
    step5_quality_check,
)
from src.observability.trace_log import (
    TraceLog,
    register_framework_hook,
    save_run,
    unregister_framework_hook,
)
from src.workspace.retrieve import retrieve_context

logger = logging.getLogger(__name__)

# ── Trace output root directory ──
TRACE_ROOT = Path(".agently/runs/insurance/traces")

# ── Retry thresholds ──
MAX_PLAN_RETRIES = 3
MAX_RETRIEVAL_RETRIES = 2
MAX_R2_RETRIES = 2
MIN_RETRIEVAL_ITEMS = 2


def _sanitize_text(text: str) -> str:
    """Remove UTF-16 surrogate characters to prevent SQLite/JSON encoding crashes.

    Surrogate characters (\\udce9, etc.) come from incomplete UTF-16 decoding,
    and trigger UnicodeEncodeError when writing to SQLite or JSON serialization.
    """
    if not isinstance(text, str):
        return text
    # Encode then decode with errors="replace" to replace all illegal surrogates
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _safe_trace_log(trace: TraceLog, **kwargs) -> None:
    """Safely call trace.log, catching Unicode encoding exceptions to prevent logging from crashing the main flow."""
    try:
        # Sanitize all str-type values
        sanitized = {}
        for k, v in kwargs.items():
            if isinstance(v, str):
                sanitized[k] = _sanitize_text(v)
            elif isinstance(v, dict):
                sanitized[k] = _sanitize_dict(v)
            elif isinstance(v, list):
                sanitized[k] = [_sanitize_dict(i) if isinstance(i, dict) else (_sanitize_text(i) if isinstance(i, str) else i) for i in v]
            else:
                sanitized[k] = v
        trace.log(**sanitized)
    except Exception as e:
        logger.warning("[Trace] trace.log failed (ignored): %s", e)


def _sanitize_dict(d: dict) -> dict:
    """Recursively sanitize all string values in a dict."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _sanitize_text(v)
        elif isinstance(v, dict):
            result[k] = _sanitize_dict(v)
        elif isinstance(v, list):
            result[k] = [
                _sanitize_text(i) if isinstance(i, str)
                else (_sanitize_dict(i) if isinstance(i, dict) else i)
                for i in v
            ]
        else:
            result[k] = v
    return result

# ── TriggerFlow definition ──
flow = TriggerFlow(name="insurance-pipeline")


@flow.chunk
async def understand(data: TriggerFlowRuntimeData) -> dict:
    """Step1: Understand natural language -- get Session context + Namespace long-term memory recall."""
    session_registry = data.require_resource("session_registry")
    chat_agent = data.require_resource("chat_agent")
    embedding_agent = data.require_resource("embedding_agent")
    memory_store = data.require_resource("memory_store")

    payload = data.input
    user_input = payload["user_input"]
    session_id = payload["session_id"]

    state = await step1_understand(
        user_input,
        session_id,
        session_registry,
        chat_agent,
        embedding_agent=embedding_agent,
        memory_store=memory_store,
    )

    state["plan_retry_count"] = 0
    state["retrieval_retry_count"] = 0
    state["r2_attempt"] = 0

    # R-16: User correction intent detection -- extract previous user question for plan to re-plan based on corrected expression
    is_correction = _is_correction_query(user_input)
    state["user_correction"] = False
    if is_correction:
        prev_input = ""
        chat_history = (state.get("context") or {}).get("chat_history", [])
        for entry in reversed(chat_history):
            if entry.get("role") == "user":
                prev_input = str(entry.get("content", ""))
                break
        state["user_correction"] = True
        state["previous_input"] = prev_input
        logger.info("[TriggerFlow] Step1 detected user correction intent (session=%s): %s", session_id, user_input[:50])

    await data.async_set_state("pipeline_state", state, emit=False)
    await data.async_set_state("user_input", user_input, emit=False)
    await data.async_set_state("session_id", session_id, emit=False)

    # Trace: Step1 business facts -- session context + memory recall
    trace = data.require_resource("trace")
    context = state.get("context", {})
    long_term_memory = context.get("long_term_memory", [])
    _safe_trace_log(trace,
        layer="business",
        event_type="business.understand.completed",
        status="completed",
        subject_id="understand",
        input={"user_input": user_input, "session_id": session_id},
        output={"context_keys": list(context.keys())},
        facts={
            "has_long_term_memory": bool(long_term_memory),
            "memory_count": len(long_term_memory),
            "chat_history_len": len(context.get("chat_history", [])),
            "user_correction": is_correction,
            "previous_input": state.get("previous_input", "") if is_correction else None,
        },
    )

    # R-16: Trace user correction event -- for demo showcasing "user feedback -> re-plan" chain
    if is_correction:
        _safe_trace_log(trace,
            layer="business",
            event_type="business.user_correction.detected",
            status="completed",
            subject_id="understand",
            input={"user_input": user_input, "session_id": session_id},
            output={"replan": True, "previous_input": state.get("previous_input", "")},
            facts={"corrected": True, "intent": "replan_after_correction"},
        )

    logger.info("[TriggerFlow] Step1 understand completed: session=%s", session_id)
    return state


@flow.chunk
async def plan(data: TriggerFlowRuntimeData) -> dict:
    """Step2: Generate query method -- R1 ModelRequest structured output routing."""
    state = data.get_state("pipeline_state")
    chat_agent = data.require_resource("chat_agent")
    observer = data.require_resource("observer")

    state = await step2_plan(state, chat_agent, observer=observer)
    await data.async_set_state("pipeline_state", state, emit=False)

    # Trace: Step2 business facts -- R1 query routing
    trace = data.require_resource("trace")
    _safe_trace_log(trace,
        layer="business",
        event_type="business.plan.generated",
        status="completed",
        subject_id="plan",
        input={"user_question": state.get("input")},
        output={
            "query_type": state.get("query_type"),
            "needs_reasoning": state.get("needs_reasoning"),
            "sub_query_count": len(state.get("sub_queries", [])),
        },
        facts={
            "query_type": state.get("query_type"),
            "plan_retry_count": state.get("plan_retry_count", 0),
            "sub_query_count": len(state.get("sub_queries", [])),
            "sub_queries": state.get("sub_queries", []),
            "needs_reasoning": state.get("needs_reasoning", False),
        },
    )

    logger.info(
        "[TriggerFlow] Step2 plan completed: query_type=%s, attempt=%d",
        state.get("query_type"),
        state.get("plan_retry_count", 0),
    )
    return state


@flow.chunk
async def validate(data: TriggerFlowRuntimeData) -> dict:
    """Step3: Validate query method -- host deterministic check + visible fallback edge.

    Signals:
    - No signal: validation passed, serial to fetch
    - "retry_plan": validation failed, fallback to plan (retry < MAX_PLAN_RETRIES)
    - "blocked": max retries exceeded, terminate
    """
    state = data.get_state("pipeline_state")
    chat_agent = data.require_resource("chat_agent")

    state = await step3_validate(state, chat_agent)
    await data.async_set_state("pipeline_state", state, emit=False)

    # Trace: Step3 business facts -- host validation result
    trace = data.require_resource("trace")
    _safe_trace_log(trace,
        layer="business",
        event_type="business.validate.checked",
        status="completed" if state.get("validated") else "failed",
        subject_id="validate",
        input={
            "query_type": state.get("query_type"),
            "query_params": state.get("query_params"),
        },
        output={"validated": state.get("validated")},
        facts={
            "validated": state.get("validated"),
            "validation_errors": state.get("validation_errors"),
            "plan_retry_count": state.get("plan_retry_count", 0),
        },
        error=state.get("block_reason") if state.get("status") == STATUS_BLOCKED else None,
    )

    if state.get("validated"):
        # out_of_domain: non-insurance domain question, short-circuit to finalize for friendly reply
        if state.get("query_type") == "out_of_domain":
            logger.info("[TriggerFlow] Step3 validate: out_of_domain detected, jumping to finalize")
            await data.async_emit("out_of_domain")
            return state
        logger.info("[TriggerFlow] Step3 validate passed")
        return state

    # Validation failed
    if state.get("status") == STATUS_BLOCKED:
        logger.error("[TriggerFlow] Step3 validate blocked: %s", state.get("block_reason"))
        await data.async_emit("blocked")
        return state

    retry_count = state.get("plan_retry_count", 0)
    if retry_count >= MAX_PLAN_RETRIES:
        state["status"] = STATUS_BLOCKED
        state["block_reason"] = f"plan validation failed {retry_count} times"
        await data.async_set_state("pipeline_state", state, emit=False)
        logger.error("[TriggerFlow] Step3 validate exceeded max retries %d, terminating", MAX_PLAN_RETRIES)
        await data.async_emit("blocked")
    else:
        logger.info("[TriggerFlow] Step3 validate failed, falling back to plan (retry %d/%d)", retry_count, MAX_PLAN_RETRIES)
        await data.async_emit("retry_plan")

    return state


@flow.chunk
async def fetch(data: TriggerFlowRuntimeData) -> dict:
    """Step4: Fetch query data -- hybrid retrieval + Query rewrite + Workspace packaging.

    Signals:
    - No signal: retrieval sufficient, serial to answer_and_check
    - "retry_plan": retrieval insufficient, fallback to plan (retry < MAX_RETRIEVAL_RETRIES)
    - "blocked": max retrieval retries exceeded, terminate
    """
    state = data.get_state("pipeline_state")
    rag_retriever = data.require_resource("rag_retriever")
    chat_agent = data.require_resource("chat_agent")
    query_rewriter = data.require_resource("query_rewriter")
    observer = data.require_resource("observer")

    state = await step4_fetch(
        state,
        rag_retriever=rag_retriever,
        workspace_retrieve=retrieve_context,
        chat_agent=chat_agent,
        query_rewriter=query_rewriter,
        observer=observer,
    )
    await data.async_set_state("pipeline_state", state, emit=False)

    # Trace: Step4 business facts -- hybrid retrieval + reranking results
    trace = data.require_resource("trace")
    pack = state.get("context_pack", {}) or {}
    pack_items = pack.get("items", []) if pack else []
    faiss_candidates = state.get("faiss_candidates", []) or []
    sq_results = state.get("sub_query_results", []) or []
    _safe_trace_log(trace,
        layer="business",
        event_type="business.fetch.retrieved",
        status="completed",
        subject_id="fetch",
        input={
            "query_type": state.get("query_type"),
            "query": (state.get("query_params") or {}).get("query"),
        },
        output={
            "candidate_count": len(faiss_candidates),
            "packed_item_count": len(pack_items),
            "sub_query_count": len(sq_results),
        },
        facts={
            "query_type": state.get("query_type"),
            "candidate_count": len(faiss_candidates),
            "packed_item_count": len(pack_items),
            "retrieval_retry_count": state.get("retrieval_retry_count", 0),
            "rewritten": bool(state.get("rewritten_query")),
            "rewritten_query": state.get("rewritten_query"),
            "diagnostics": pack.get("diagnostics") if pack else None,
            "sub_query_results": sq_results,
        },
    )

    # Retrieval quality check (rag_query path only)
    if state.get("query_type") == "rag_query":
        items = pack_items

        if len(items) < MIN_RETRIEVAL_ITEMS:
            retry_count = state.get("retrieval_retry_count", 0)
            if retry_count >= MAX_RETRIEVAL_RETRIES:
                state["status"] = STATUS_BLOCKED
                state["block_reason"] = (
                    f"retrieval insufficient after {retry_count} retries: "
                    f"only {len(items)} items (need >= {MIN_RETRIEVAL_ITEMS})"
                )
                await data.async_set_state("pipeline_state", state, emit=False)
                logger.error("[TriggerFlow] Step4 fetch retrieval retries exhausted, terminating")
                await data.async_emit("blocked")
                return state

            # Retrieval insufficient, fallback to plan
            state["retrieval_retry_count"] = retry_count + 1
            state["plan_retry_count"] = 0
            state["validation_errors"] = [
                f"retrieval insufficient: {len(items)} items (need >= {MIN_RETRIEVAL_ITEMS})"
            ]
            # Restore original query (avoid rewrite causing repeated failures)
            if state.get("original_query"):
                state["query_params"] = {"query": state["original_query"]}
            await data.async_set_state("pipeline_state", state, emit=False)
            logger.info(
                "[TriggerFlow] Step4 fetch retrieval insufficient (%d items), falling back to plan (retry %d/%d)",
                len(items), retry_count + 1, MAX_RETRIEVAL_RETRIES,
            )
            await data.async_emit("retry_plan")
            return state

    logger.info(
        "[TriggerFlow] Step4 fetch completed: query_type=%s, candidates=%d",
        state.get("query_type"),
        len(state.get("faiss_candidates", [])),
    )
    return state


@flow.chunk
async def answer_and_check(data: TriggerFlowRuntimeData) -> dict:
    """Step5: Generate answer + quality check -- R2 ModelRequest + visible fallback edge.

    Signals:
    - No signal: quality passed or retries exhausted, serial to finalize
    - "retry_answer": quality failed, fallback to self-retry (retry < MAX_R2_RETRIES)
    """
    state = data.get_state("pipeline_state")
    chat_agent = data.require_resource("chat_agent")
    observer = data.require_resource("observer")
    reasoning_agent = data.require_resource("reasoning_agent")

    # Get fix hint (from previous quality check failure)
    fix_hint = state.pop("fix_hint", "")

    # Generate answer (R2 ModelRequest)
    state = await step5_answer(
        state,
        chat_agent,
        observer=observer,
        fix_hint=fix_hint,
        reasoning_agent=reasoning_agent,
    )
    await data.async_set_state("pipeline_state", state, emit=False)

    # Trace: Step5 business facts -- R2 answer with citations
    trace = data.require_resource("trace")
    citations = state.get("citations", []) or []
    sources = state.get("sources", []) or []
    _safe_trace_log(trace,
        layer="business",
        event_type="business.answer.composed",
        status="completed",
        subject_id="answer_and_check",
        input={
            "user_question": state.get("input"),
            "evidence_count": len((state.get("context_pack") or {}).get("items", [])),
        },
        output={
            "answer_length": len(state.get("answer", "")),
            "citation_count": len(citations),
            "source_count": len(sources),
        },
        facts={
            "r2_attempt": state.get("r2_attempt", 0),
            "citation_count": len(citations),
            "source_count": len(sources),
            "needs_reasoning": state.get("needs_reasoning", False),
            "status": state.get("status"),
        },
    )

    # Quality check
    quality_pass, new_fix_hint = await step5_quality_check(state)

    r2_attempt = state.get("r2_attempt", 0)
    if quality_pass:
        state["status"] = STATUS_COMPLETED
        await data.async_set_state("pipeline_state", state, emit=False)
        logger.info("[TriggerFlow] Step5 answer quality passed (attempt %d)", r2_attempt)
        return state

    # Quality not passed
    if r2_attempt >= MAX_R2_RETRIES:
        state["status"] = STATUS_PARTIAL
        state["failure_reason"] = f"R2 quality fix cannot converge: {new_fix_hint}"
        await data.async_set_state("pipeline_state", state, emit=False)
        logger.warning(
            "[TriggerFlow] Step5 answer quality fix exhausted (%d attempts), terminating with PARTIAL status: %s",
            r2_attempt, new_fix_hint,
        )
        return state

    # Fallback to self-retry
    state["fix_hint"] = new_fix_hint
    await data.async_set_state("pipeline_state", state, emit=False)
    logger.info(
        "[TriggerFlow] Step5 answer quality not passed (attempt %d/%d), falling back to retry: %s",
        r2_attempt, MAX_R2_RETRIES, new_fix_hint,
    )
    await data.async_emit("retry_answer")
    return state


@flow.chunk
async def finalize(data: TriggerFlowRuntimeData) -> dict:
    """Terminal: Session persistence + memory extraction + observation collection."""
    state = data.get_state("pipeline_state")
    session_registry = data.require_resource("session_registry")
    observer = data.require_resource("observer")
    user_input = data.get_state("user_input")
    session_id = data.get_state("session_id")

    # Idempotent guard: prevent TriggerFlow from re-executing finalize (both serial edge and when("blocked") can reach here)
    if state.get("_finalized"):
        logger.debug("[TriggerFlow] finalize already executed, skipping duplicate call")
        return state
    state["_finalized"] = True
    await data.async_set_state("pipeline_state", state, emit=False)

    # out_of_domain: non-insurance domain question, generate friendly guidance reply (skip retrieval and answer generation)
    if state.get("query_type") == "out_of_domain":
        state["answer"] = (
            "Sorry, I am an insurance business Q&A assistant and can only answer insurance-related questions.\n\n"
            "You can try asking me questions like:\n"
            "- What is the coverage scope of Employer Liability Insurance?\n"
            "- What is the claims process?\n"
            "- What is the difference between Employer Liability Insurance A and B?\n"
            "- How is the premium calculated?\n"
            "- What insurance products are available?\n\n"
            "Is there anything insurance-related I can help you with?"
        )
        state["status"] = STATUS_COMPLETED
        state["citations"] = []
        state["sources"] = []
        state["context_pack"] = {"items": [], "diagnostics": {"skipped": "out_of_domain"}}
        state["observations"] = observer.get_all()
        state["observation_summary"] = observer.summary()
        await data.async_set_state("pipeline_state", state, emit=False)
        await data.async_set_state("final_result", state, emit=False)

        trace = data.require_resource("trace")
        _safe_trace_log(trace,
            layer="business",
            event_type="business.finalize.out_of_domain",
            status="completed",
            subject_id="finalize",
            input={"session_id": session_id, "user_input": user_input},
            output={"status": "completed", "reason": "out_of_domain"},
            facts={"query_type": "out_of_domain", "answer_generated": True},
        )

        logger.info("[TriggerFlow] finalize completed (out_of_domain): session=%s", session_id)
        return state

    # Update Session chat history
    if state.get("session"):
        session = state["session"]
        if hasattr(session, "async_add_chat_history"):
            await session.async_add_chat_history([
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": str(state.get("answer", ""))},
            ])

    # Session persistence + memory extraction
    try:
        from src.session.persistence import extract_memo_from_turn

        memo_entry = extract_memo_from_turn(
            user_input=user_input,
            answer=state.get("answer", ""),
            citations=state.get("citations"),
            query_type=state.get("query_type"),
        )
        if state.get("session") and hasattr(session, "memo"):
            memo = session.memo
            if isinstance(memo, dict):
                # Modify dict in-place, do not reassign session.memo (read-only property)
                turn_memos = memo.get("turn_memos", [])
                turn_memos.append(memo_entry)
                memo["turn_memos"] = turn_memos[-20:]
            else:
                logger.debug("Session.memo is not a dict type (%s), skipping memory update", type(memo).__name__)

        if hasattr(session_registry, "save_session"):
            session_registry.save_session(session_id)
            logger.debug("[TriggerFlow] Session persisted: %s", session_id)
    except Exception as e:
        logger.warning("[TriggerFlow] Session persistence/memory extraction failed: %s", e)

    # Ensure terminal status is set
    if not state.get("status"):
        state["status"] = STATUS_COMPLETED

    # Attach observation records
    state["observations"] = observer.get_all()
    state["observation_summary"] = observer.summary()

    await data.async_set_state("pipeline_state", state, emit=False)
    await data.async_set_state("final_result", state, emit=False)

    # Trace: Terminal business facts -- session persistence + memory extraction
    trace = data.require_resource("trace")
    observations = state.get("observations", []) or []
    _safe_trace_log(trace,
        layer="business",
        event_type="business.finalize.completed",
        status="completed",
        subject_id="finalize",
        input={"session_id": session_id},
        output={"status": state.get("status")},
        facts={
            "status": state.get("status"),
            "observation_count": len(observations),
            "session_persisted": True,
            "answer_present": bool(state.get("answer")),
        },
    )

    logger.info(
        "[TriggerFlow] finalize completed: session=%s, status=%s, sources=%s",
        session_id,
        state.get("status"),
        state.get("sources", []),
    )
    return state


# ── Topology definition ──
# Serial main flow: understand -> plan -> validate -> fetch -> answer_and_check -> finalize
flow.to(understand).to(plan).to(validate).to(fetch).to(answer_and_check).to(finalize)

# Visible fallback edge: validation failed -> re-plan
flow.when("retry_plan").to(plan)

# Visible fallback edge: quality not passed -> regenerate answer
flow.when("retry_answer").to(answer_and_check)

# Terminal edge: max retries exceeded -> terminate directly
flow.when("blocked").to(finalize)

# Short-circuit edge: non-insurance domain question -> jump directly to finalize for friendly reply
flow.when("out_of_domain").to(finalize)


# ── Document list query detection ──
# Patterns matching user questions like "list all documents"
_DOCUMENT_LIST_PATTERNS = [
    re.compile(r"list.*(?:all|uploaded).*(?:doc|file)", re.IGNORECASE),
    re.compile(r"list.*(?:document|file).*", re.IGNORECASE),
    re.compile(r"(?:show|list|display).*(?:all|uploaded|available).*(?:documents|files)", re.IGNORECASE),
    re.compile(r"what (?:documents|files) (?:do you )?(?:have|are there|are available)", re.IGNORECASE),
]

# ── Chinese-to-English document title mapping ──
# Source corpus filenames are in Chinese; map to English for the demo
_DOC_TITLE_MAP = {
    "平安产险交通出行意外伤害保险": "Ping An Property Traffic Travel Accident Injury Insurance",
    "平安企业团体综合意外险": "Ping An Enterprise Group Comprehensive Accident Insurance",
    "平安产险交通工具意外伤害保险": "Ping An Property Transport Accident Injury Insurance",
    "财产一切险": "All-Risk Property Insurance",
    "平安境内紧急医疗救援服务": "Ping An Domestic Emergency Medical Rescue Service",
    "平安商业综合责任保险": "Ping An Commercial Comprehensive Liability Insurance",
    "施工保": "Construction Insurance",
    "雇主安心保": "Employer Peace Insurance",
    "雇主责任险": "Employer Liability Insurance",
    "平安装修保": "Ping An Renovation Insurance",
}


def _translate_doc_title(title: str) -> str:
    """Translate a Chinese document title to English using the mapping table."""
    for cn, en in _DOC_TITLE_MAP.items():
        if cn in title:
            return en
    return title


def _is_document_list_query(user_input: str) -> bool:
    """Detect whether this is a document list query.

    Returns True when the user asks "list all documents" type questions.
    These queries read the document list directly from the records directory, bypassing the RAG retrieval pipeline.
    """
    for pattern in _DOCUMENT_LIST_PATTERNS:
        if pattern.search(user_input):
            return True
    return False


# ── User correction intent detection (R-16) ──
# Matches user correction feedback on previous answer/plan, triggers re-planning
_CORRECTION_PATTERNS = [
    # English correction patterns (R-16)
    re.compile(r"\b(no|nope|not quite|wrong|that's not|thats not|i meant|i mean)\b", re.IGNORECASE),
    re.compile(r"\bnot\,?\s*(employer|group|personal|property|construction|renovation|commercial)", re.IGNORECASE),
    re.compile(r"\bi (?:said|meant)\b", re.IGNORECASE),
    re.compile(r"\bcors?rect (?:me|that|it)", re.IGNORECASE),
    re.compile(r"\b(?:you )?misunderstood\b", re.IGNORECASE),
    re.compile(r"\byou (?:got (?:it )?wrong|missed|misread)\b", re.IGNORECASE),
]


def _is_correction_query(user_input: str) -> bool:
    """Detect whether this is a user correction intent.

    Returns True when the user corrects a previous answer/plan (e.g. "No, I meant group accident insurance"),
    triggering understand to record the correction flag and plan to re-plan based on the corrected expression.
    """
    if not user_input:
        return False
    for pattern in _CORRECTION_PATTERNS:
        if pattern.search(user_input):
            return True
    return False


async def run_flow(
    user_input: str,
    session_id: str,
    chat_agent: Any,
    session_registry: Any,
    rag_retriever: Any = None,
    query_rewriter: Any = None,
    reasoning_agent: Any = None,
    embedding_agent: Any = None,
    memory_store: list | None = None,
    request_timeout: int = 30,
) -> dict:
    """Run the TriggerFlow five-step business flow.

    Args:
        user_input: User input
        session_id: Session identifier
        chat_agent: Chat Agent
        session_registry: Session registry
        rag_retriever: RAG retriever (optional)
        query_rewriter: Query rewriter (optional)
        reasoning_agent: Reasoning enhancement Agent (optional)
        embedding_agent: Embedding Agent (optional)
        memory_store: Namespace long-term memory storage (optional)
        request_timeout: Request timeout (seconds)

    Returns:
        Final state dict (containing answer, citations, sources, status, observations, etc.)
    """
    import asyncio

    # Input sanitization: remove UTF-16 surrogate characters to prevent SQLite/JSON encoding crashes
    user_input = _sanitize_text(user_input)

    # Defensive check: session_registry must not be None (step1 needs to call get_or_create)
    if session_registry is None:
        from src.session.registry import SessionRegistry
        session_registry = SessionRegistry()
        logger.warning("[TriggerFlow] session_registry is None, created temporary instance")

    # ── Document list query interception ──
    # When the user asks "list all documents" type questions, read the document list directly from the records directory,
    # bypassing the RAG retrieval pipeline, ensuring the return format is "There are X insurance-related documents:\n1. Document A\n2. Document B"
    if rag_retriever and _is_document_list_query(user_input):
        logger.info("[TriggerFlow] Document list query detected, reading directly from records directory: %s", user_input[:50])
        docs = rag_retriever.list_all_documents()

        if docs:
            doc_lines = "\n".join(
                f"{i + 1}. {_translate_doc_title(d['title'])}" for i, d in enumerate(docs)
            )
            answer = f"There are {len(docs)} insurance-related documents available:\n{doc_lines}"
        else:
            answer = "No insurance documents have been uploaded yet. Please run `python scripts/build_index.py` to build the index."

        # Update Session chat history
        try:
            session = session_registry.get_or_create(session_id)
            if hasattr(session, "async_add_chat_history"):
                await session.async_add_chat_history([
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": answer},
                ])
        except Exception as e:
            logger.warning("[TriggerFlow] Session update failed for document list query: %s", e)

        # Session persistence
        try:
            if hasattr(session_registry, "save_session"):
                session_registry.save_session(session_id)
        except Exception as e:
            logger.warning("[TriggerFlow] Session persistence failed for document list query: %s", e)

        return {
            "answer": answer,
            "citations": [],
            "sources": [_translate_doc_title(d["source"]) for d in docs] if docs else [],
            "source_details": [],
            "status": "completed",
            "query_type": "document_list",
            "observations": [],
            "observation_summary": "document_list_intercepted",
            "task_id": f"insurance-{uuid.uuid4().hex[:12]}",
        }

    observer = ObservationCollector()

    execution = flow.create_execution(
        auto_close=False,
        runtime_resources={
            "chat_agent": chat_agent,
            "session_registry": session_registry,
            "rag_retriever": rag_retriever,
            "query_rewriter": query_rewriter,
            "reasoning_agent": reasoning_agent,
            "embedding_agent": embedding_agent,
            "memory_store": memory_store,
            "observer": observer,
        },
    )

    # Create TraceLog and register framework event Hook (before execution starts)
    task_id = f"insurance-{uuid.uuid4().hex[:12]}"
    trace = TraceLog(task_id, execution.id)
    hook_name = register_framework_hook(trace)
    execution.update_runtime_resources({"trace": trace})

    state = None
    execution_closed = False
    try:
        await asyncio.wait_for(
            execution.async_start({
                "user_input": user_input,
                "session_id": session_id,
            }),
            timeout=request_timeout,
        )
        state = await asyncio.wait_for(
            execution.async_close(),
            timeout=request_timeout,
        )
        execution_closed = True
    except asyncio.TimeoutError:
        logger.error("[TriggerFlow] Execution timeout (%ds): session=%s", request_timeout, session_id)
        result = {
            "answer": f"The request timed out (>{request_timeout}s). Please simplify your question and try again.",
            "citations": [],
            "sources": [],
            "source_details": [],
            "status": "failed",
            "failure_reason": f"timeout_after_{request_timeout}s",
            "observations": observer.get_all(),
            "observation_summary": observer.summary(),
        }
    except Exception as e:
        logger.error("[TriggerFlow] Execution failed: %s", e, exc_info=True)
        error_msg = _sanitize_text(str(e))
        result = {
            "answer": f"Processing failed: {error_msg}",
            "citations": [],
            "sources": [],
            "source_details": [],
            "status": "failed",
            "failure_reason": error_msg,
            "observations": observer.get_all(),
            "observation_summary": observer.summary(),
        }
    finally:
        # C-1 fix: ensure execution is closed, drain pending tasks and runtime stream consumers.
        # If async_start times out or raises an exception, async_close will never be called,
        # leaving execution in an unclosed state (pending tasks, runtime stream consumers not drained).
        if not execution_closed:
            try:
                await asyncio.wait_for(
                    execution.async_close(),
                    timeout=request_timeout,
                )
            except Exception as close_err:
                logger.warning("[TriggerFlow] async_close failed in finally block: %s", close_err)
        # Unregister framework event Hook regardless of success/failure/timeout
        unregister_framework_hook(hook_name)

    # On successful execution, get final result from execution state
    if state is not None:
        result = state.get("pipeline_state", state.get("final_result", state))

    # Inject trace facts into result dict
    result["task_id"] = task_id
    result["execution_id"] = execution.id
    result["trace_events"] = trace.events

    # Save trace data to disk (.agently/runs/insurance/traces/{task_id}/)
    try:
        run_record = {
            "task_id": task_id,
            "execution_id": execution.id,
            "session_id": session_id,
            "user_input": user_input,
            "status": result.get("status"),
            "answer": result.get("answer"),
            "citations": result.get("citations"),
            "sources": result.get("sources"),
            "source_details": result.get("source_details"),
            "query_type": result.get("query_type"),
            "sub_queries": result.get("sub_queries", []),
            "sub_query_results": result.get("sub_query_results", []),
            "context_pack": result.get("context_pack"),
            "faiss_candidates": result.get("faiss_candidates"),
            "observations": result.get("observations"),
            "observation_summary": result.get("observation_summary"),
            "events": trace.events,
        }
        save_run(run_record, TRACE_ROOT / task_id)
        logger.info("[Trace] Run facts saved: %s", TRACE_ROOT / task_id)
    except Exception as e:
        logger.warning("[Trace] Failed to save run facts: %s", e)

    logger.info(
        "[TriggerFlow] Five-step business flow completed: session=%s, status=%s, execution_id=%s, trace_events=%d",
        session_id,
        result.get("status"),
        execution.id,
        len(trace.events),
    )
    return result


__all__ = ["flow", "run_flow"]
