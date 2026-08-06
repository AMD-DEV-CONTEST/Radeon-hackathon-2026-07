"""Five-step business flow step function library: Insurance intelligent Q&A Agent.

P0-1 fix: TriggerFlow orchestration has been migrated to src/agent/flow.py.
This module keeps the step1~step5 step functions for the chunks in flow.py to call,
and run_pipeline serves as a backward-compatible legacy entrypoint (internally still a for loop).

Topology fix history:
- P0-A: passed workspace_retrieve to fix the Step4 evidence-chain break
- P0-B: added host-side deterministic validation of Step4 data_query parameters
- P1: fall back to Step2 retry when Step4 retrieval is insufficient
- P2-C: stateless context passing in Step1 (does not directly modify chat_agent)
- P2-D: fan-out retrieval for multi-document comparison
- P3: R2 answer-quality repair loop
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from src.agent.observation import ObservationCollector
from src.workspace.retrieve import retrieve_context  # P0-A: explicit import

logger = logging.getLogger(__name__)

# ── Terminal status constants (I5 + M1) ──
STATUS_COMPLETED = "completed"
STATUS_BLOCKED = "blocked"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# ── Citation token regex (I3) ──
CITATION_PATTERN = re.compile(r"\[\[ref:(\w+)\]\]")

# ── Retrieval quality thresholds (P1) ──
MIN_RETRIEVAL_ITEMS = 2
MAX_RETRIEVAL_RETRIES = 2

# ── data_query safe parameter whitelist (P0-B) ──
SAFE_DATA_QUERY_PARAMS = {"query_type", "data_type", "type", "name", "product_id", "status", "query"}



# ── Chinese-to-English document title mapping ──
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

def _translate_title(title):
    if not title:
        return title
    for cn, en in _DOC_TITLE_MAP.items():
        if cn in title:
            return en
    return title

def validate_citations(answer_text: str, offered_keys: set[str]) -> tuple[bool, list[str], list[str]]:
    """Parse the [[ref:xxx]] tokens and verify that each key belongs to the offered set (I3 trusted-choice key validation)."""
    found_keys = CITATION_PATTERN.findall(answer_text)
    valid = [k for k in found_keys if k in offered_keys]
    invalid = [k for k in found_keys if k not in offered_keys]
    return len(invalid) == 0, valid, invalid


async def step1_understand(
    user_input: str,
    session_id: str,
    session_registry: Any,
    chat_agent: Any,
    embedding_agent: Any = None,
    memory_store: list | None = None,
) -> dict:
    """Step1: understand natural language — stateless context passing (P2-C fix).

    P2-C: no longer directly modifies the chat_agent state (set_chat_history);
    instead the context is passed through state.context and loaded by Step2 via input.

    P1-4: integrates Namespace long-term memory recall — the call chain is shown even when memory_store is empty.
    """
    session = session_registry.get_or_create(session_id)
    # P2-C: put context into state, do not modify chat_agent
    context = {
        "chat_history": session.context_window if hasattr(session, "context_window") else [],
        "memo": session.memo if hasattr(session, "memo") else {},
    }

    # P1-4: Namespace long-term memory recall
    recalled_memories = []
    if embedding_agent and memory_store is not None:
        try:
            from src.memory.recall import recall_namespace
            recalled_memories = await recall_namespace(
                embedding_agent=embedding_agent,
                memory_store=memory_store,
                query=user_input,
                top_k=3,
            )
            if recalled_memories:
                logger.info(
                    "Namespace memory recall: %d items (session=%s)",
                    len(recalled_memories), session_id,
                )
                context["long_term_memory"] = [
                    {"summary": m.summary, "body": m.body}
                    for m in recalled_memories
                ]
            else:
                logger.debug("Namespace memory recall: 0 items (memory_store=%d items)", len(memory_store))
        except Exception as e:
            logger.warning("Namespace memory recall failed: %s", e)
    else:
        logger.debug("Namespace memory not enabled (embedding_agent=%s, memory_store=%s)", bool(embedding_agent), memory_store is not None)

    return {
        "session": session,
        "input": user_input,
        "session_id": session_id,
        "context": context,
    }


async def step2_plan(
    state: dict,
    chat_agent: Any,
    observer: ObservationCollector | None = None,
) -> dict:
    """Step2: generate the query method — Agent structured-output routing (R1 node).

    P2-D: the output schema supports the sub_queries field for multi-document comparison fan-out retrieval.
    F3: when the user question involves comparing multiple documents, the LLM decomposes the question into multiple sub-queries,
        each retrieved independently, then executes them concurrently for fan-out and gives a synthesized answer in Step5.
    """
    attempt = state.get("plan_retry_count", 0)
    retry_hint = ""
    if state.get("validation_errors"):
        retry_hint = f"\n\nReason for the previous planning failure: {state['validation_errors']}, please fix it."

    # R-16: user-correction scenario — detect that this turn is a user-feedback correction, re-plan, and do not reuse the previous wrong decomposition
    correction_notice = ""
    if state.get("user_correction"):
        prev_input = state.get("previous_input", "")
        correction_notice = (
            "\n\nThe user corrected the previous answer/planning; this turn must re-plan the query based on the corrected wording. "
            "Rules: "
            "1) do not reuse the previous wrong sub-queries; "
            "2) re-decompose the query based on the user's corrected keywords (e.g., correct 'individual accident insurance' to 'group accident insurance'); "
            "3) if the user only gives the corrective wording this turn (e.g., 'no, I meant group accident insurance'), "
            "infer the complete intent by combining the previous question (%s) before decomposing."
            % (prev_input[:60] if prev_input else "previous question")
        )

    # P2-C: get the context from state.context, not from chat_agent
    context = state.get("context", {})
    input_data = {
        "user_question": state["input"],
        "chat_history": context.get("chat_history", []),
        "memo": context.get("memo", {}),
    }

    t0 = time.perf_counter()
    try:
        intent = await (
            chat_agent
            .input(input_data)
            .info({
                "query_type_enum": ["rag_query", "data_query", "out_of_domain"],
                "rag_query_scope": "insurance-clause Q&A, product comparison, claims-process guidance, coverage scope, premium calculation, deductible, exclusions and other insurance knowledge",
                "data_query_scope": "business data query (product list, claims records)",
                "out_of_domain_scope": (
                    "Non-insurance-domain questions, including but not limited to: recruiting/job seeking, weather, small talk/greetings, "
                    "technical questions, news, entertainment, shopping, travel, education, healthcare (non-insurance), "
                    "food, sports, programming, personal finance (non-insurance), etc. "
                    "Judgment standard: the core of the question does not involve insurance products, insurance clauses, claims, premiums or other insurance business content. "
                ),
                "out_of_domain_examples": [
                    {"query": "Are you hiring salespeople", "type": "out_of_domain", "reason": "recruitment/job seeking, unrelated to insurance business"},
                    {"query": "What are the company benefits like", "type": "out_of_domain", "reason": "job-seeking consultation, unrelated to insurance business"},
                    {"query": "Hello", "type": "out_of_domain", "reason": "greeting/small talk, no insurance business intent"},
                    {"query": "What is the weather like tomorrow", "type": "out_of_domain", "reason": "weather query, unrelated to insurance business"},
                    {"query": "Help me write a piece of Python code", "type": "out_of_domain", "reason": "technical/programming, unrelated to insurance business"},
                    {"query": "What is the coverage of Employer Liability Insurance", "type": "rag_query", "reason": "asks about insurance-clause coverage"},
                    {"query": "What is the claims process", "type": "rag_query", "reason": "asks about the insurance claims process"},
                    {"query": "What insurance products are available", "type": "data_query", "reason": "queries the business product list"},
                ],
                "reasoning_trigger": "complex computation (e.g., premium estimation, payout-ratio calculation, multi-condition logical derivation)",
                "business_boundary": "only handle insurance-domain documents and questions; indicate out-of-scope for non-insurance questions",
                "sub_query_decomposition": (
                    "When the user question involves comparing two or more insurance products (e.g., 'the difference between plan A and plan B', 'compare the coverage of A and B'), "
                    "you MUST decompose the question into multiple sub-queries, each targeting one product. "
                    "Example: 'compare the coverage of Employer Liability Insurance plan A and plan B' → "
                    "[{\"query\": \"Employer Liability Insurance plan A coverage\"}, {\"query\": \"Employer Liability Insurance plan B coverage\"}]. "
                    "Single-product questions do not need decomposition; leave sub_queries empty. "
                ),
            })
            .instruct(
                "Identify the business intent and output the query method. "
                "query_type MUST be one of the values in info.query_type_enum; no other value is accepted. "
                "Decision rules (apply strictly in priority order):\n"
                "1. First decide whether it is out_of_domain: if the core of the question is unrelated to insurance products, "
                "insurance clauses, claims, premiums or other insurance business, you MUST choose out_of_domain. Use the examples in "
                "info.out_of_domain_examples. Recruiting/job seeking, weather, small talk, technical/programming, entertainment, etc. are all out_of_domain.\n"
                "2. Then distinguish rag_query vs data_query: insurance knowledge Q&A (clauses, coverage scope, claims process, product comparison, etc.) "
                "-> rag_query; querying business data (product list, claims records) -> data_query.\n"
                "3. When it cannot be determined whether the question belongs to the insurance domain, prefer out_of_domain to avoid meaningless retrieval.\n"
                "If the user question involves the scenario described by info.reasoning_trigger, "
                "set needs_reasoning=true, otherwise needs_reasoning=false. "
                "F3 multi-step task decomposition: when the question involves multi-document comparison, refer to the example in "
                "info.sub_query_decomposition and decompose the question into multiple independent sub-queries placed in sub_queries. "
                "Each sub-query should be able to independently retrieve the relevant information of one product. "
                "If a sub-query does not retrieve relevant results, subsequent steps will retry or indicate that the product clause is missing. "
                + retry_hint
                + correction_notice
            )
            .output({
                "query_type": (str, "must be 'rag_query', 'data_query' or 'out_of_domain'", "not_null"),
                "query_params": (
                    {
                        "query": (str, "the query text for rag_query", "allow_empty"),
                        "data_type": (str, "the data type for data_query (products/claims)", "allow_empty"),
                    },
                    "query parameters: fill query for rag_query, fill data_type for data_query, leave empty for out_of_domain",
                    "not_null",
                ),
                "needs_reasoning": (bool, "whether deep reasoning is needed (complex computation, logical derivation)", "not_null"),
                "sub_queries": (
                    [{
                        "query": (str, "sub-query text, a retrieval query targeting a single product", "not_null"),
                        "target_doc": (str, "the target document identifier of the sub-query (e.g., product name)", "allow_empty"),
                    }],
                    "the sub-query list when comparing multiple documents. Leave empty for single-product questions.",
                    "allow_empty",
                ),
            }, format="json")
            .async_start()
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if observer:
            observer.record_request(
                node_id="R1",
                input_data=input_data,
                output_data=intent,
                duration_ms=elapsed_ms,
                attempt=attempt + 1,
                status="completed",
                provider_model="Qwen3-8B",
                consumer_edges=[
                    {"field": "query_type", "consumer": "host_branch(Step4)", "validated": True},
                    {"field": "query_params", "consumer": "faiss_retriever", "validated": True},
                    {"field": "needs_reasoning", "consumer": "step5_answer", "validated": True},
                ],
            )
        return {**state, **intent, "validation_errors": None}
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.error("Step2 failed, defaulting to rag_query: %s", e)
        if observer:
            observer.record_request(
                node_id="R1",
                input_data=input_data,
                output_data={"error": str(e)},
                duration_ms=elapsed_ms,
                attempt=attempt + 1,
                status="failed",
                error=str(e),
            )
        return {
            **state,
            "query_type": "rag_query",
            "query_params": {"query": state["input"]},
            "sub_queries": [],
            "needs_reasoning": False,
            "validation_errors": [f"step2_exception: {e}"],
        }


async def step3_validate(state: dict, chat_agent: Any) -> dict:
    """Step3: validate the query method — host-side deterministic validation (C3 termination rule).

    Ownership classification:
        - host-owned deterministic: query_type enum, required fields, type checks
        - (model semantic validation optional, currently disabled to reduce latency)
    """
    query_type = state.get("query_type", "")
    query_params = state.get("query_params", {})
    validation_errors: list[str] = []

    # out_of_domain: non-insurance-domain question, passes validation directly (short-circuited to finalize by the flow layer)
    if query_type == "out_of_domain":
        logger.info("Step3: detected an out_of_domain question, skipping downstream retrieval and replying directly")
        return {**state, "validated": True, "validation_errors": None, "plan_retry_count": state.get("plan_retry_count", 0)}

    # Host deterministic validation 1: query_type enum
    if query_type not in ("rag_query", "data_query"):
        validation_errors.append(f"unknown query_type: {query_type}")

    # Host deterministic validation 2: required fields + type checks (I6)
    if query_type == "rag_query":
        q = query_params.get("query")
        if not q:
            validation_errors.append("rag_query missing required field 'query'")
        elif not isinstance(q, str):
            validation_errors.append(f"rag_query 'query' must be string, got {type(q).__name__}")
    elif query_type == "data_query":
        dt = query_params.get("data_type")
        if not dt:
            validation_errors.append("data_query missing required field 'data_type'")
        elif not isinstance(dt, str):
            validation_errors.append(f"data_query 'data_type' must be string, got {type(dt).__name__}")

    if validation_errors:
        retry_count = state.get("plan_retry_count", 0) + 1
        # C3: terminate after 3 identical failures
        if retry_count >= 3:
            logger.error("Step3 validation failed %d times, terminating: %s", retry_count, validation_errors)
            return {
                **state,
                "validated": False,
                "validation_errors": validation_errors,
                "plan_retry_count": retry_count,
                "status": STATUS_BLOCKED,
                "block_reason": f"query validation failed {retry_count} times: {validation_errors}",
            }
        return {
            **state,
            "validated": False,
            "validation_errors": validation_errors,
            "plan_retry_count": retry_count,
        }

    return {**state, "validated": True, "validation_errors": None, "plan_retry_count": state.get("plan_retry_count", 0)}


async def step4_fetch(
    state: dict,
    rag_retriever: Any = None,
    workspace_retrieve: Any = None,
    chat_agent: Any = None,
    query_rewriter: Any = None,
    observer: ObservationCollector | None = None,
) -> dict:
    """Step4: fetch the query data and organize it.

    P0-A: pass retrieve_context through the workspace_retrieve parameter to fix the evidence-chain break.
    P0-B: add host-side deterministic validation of data_query parameters, passing only known safe fields.
    P2-D: support sub_queries fan-out retrieval.
    R5: integrate Query rewriting — expand fuzzy queries with the LLM to improve retrieval recall.
    """
    if state.get("query_type") == "rag_query":
        query = state["query_params"].get("query", state["input"])

        # R5: Query rewriting (optional) — when the query is fuzzy, the LLM adds context to expand the query
        # C2: QueryRewriter is an independent ModelRequest and needs observation records
        if query_rewriter:
            context = state.get("context", {})
            chat_history = context.get("chat_history", [])
            memo = context.get("memo", {})

            if query_rewriter.should_rewrite(query, chat_history):
                qr_t0 = time.perf_counter()
                rewritten = await query_rewriter.rewrite(query, chat_history, memo)
                qr_elapsed_ms = (time.perf_counter() - qr_t0) * 1000
                state["original_query"] = query
                state["rewritten_query"] = rewritten
                logger.info(
                    "Query rewrite: '%s' → '%s'",
                    query[:50], rewritten[:50],
                )
                # C2: record the R_qr observation
                if observer:
                    observer.record_request(
                        node_id="R_qr",
                        input_data={"original_query": query, "chat_history": chat_history},
                        output_data={"rewritten_query": rewritten},
                        duration_ms=qr_elapsed_ms,
                        status="completed" if rewritten != query else "partial",
                    )
                query = rewritten  # use the rewritten query for retrieval

        sub_queries = state.get("sub_queries", [])

        # P2-D: if there are multi-document comparison sub-queries, fan-out concurrent retrieval — C4 fix
        # F3: each sub-query retrieves independently; record the result count of each sub-query
        #     so that Step5 can determine whether a product clause is missing
        all_candidates = []
        sub_query_results: list[dict] = []  # F3: record the retrieval diagnostics of each sub-query
        queries_to_retrieve = [q["query"] for q in sub_queries] if sub_queries else [query]

        async def _retrieve_one(q: str) -> list[dict]:
            """Retrieval task for a single query."""
            if rag_retriever:
                return await rag_retriever.retrieve(q)
            return []

        if queries_to_retrieve and rag_retriever:
            # C4: concurrent retrieval to reduce the latency of multi-document comparison
            retrieve_tasks = [_retrieve_one(q) for q in queries_to_retrieve]
            retrieve_results = await asyncio.gather(*retrieve_tasks)
            for sq, candidates in zip(queries_to_retrieve, retrieve_results):
                all_candidates.extend(candidates)
                sub_query_results.append({
                    "query": sq,
                    "result_count": len(candidates),
                    "sources": list({c.get("source", c.get("chunk_id", "")) for c in candidates}),
                })
            # F3: store the sub-query diagnostics into state for Step5 and trace
            state["sub_query_results"] = sub_query_results
            if sub_queries:
                logger.info(
                    "F3 multi-step retrieval: %d sub-queries, result counts %s",
                    len(sub_queries),
                    [r["result_count"] for r in sub_query_results],
                )

        if all_candidates:
            # deduplicate
            seen_ids = set()
            unique_candidates = []
            for c in all_candidates:
                cid = c.get("chunk_id", c.get("ref", ""))
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    unique_candidates.append(c)
                elif not cid:
                    unique_candidates.append(c)
            state["faiss_candidates"] = unique_candidates
        else:
            state["faiss_candidates"] = []

        # P0-A: Workspace packaging (via the passed workspace_retrieve)
        if workspace_retrieve and state.get("faiss_candidates"):
            workspace = rag_retriever.workspace if rag_retriever else None
            # C3: build the scope from the session (tenant isolation + permission boundary)
            scope = {}
            session = state.get("session")
            if session and hasattr(session, "tenant_id"):
                scope["tenant_id"] = session.tenant_id
            context_pack = await workspace_retrieve(
                ws=workspace,
                query=query,
                faiss_candidates=state["faiss_candidates"],
                budget_chars=2000,
                scope=scope if scope else None,
            )
            state["context_pack"] = context_pack
        else:
            state["context_pack"] = {
                "items": [],
                "diagnostics": {"representation": "none", "total_candidates": 0, "packed_items": 0},
            }

        return {**state, "data_result": None}

    else:
        # P0-B: data_query host-side deterministic validation
        from src.tools.data_query import query_products, query_claims
        params = state.get("query_params", {})

        # pass only known safe fields, blocking model-hallucinated fields
        safe_params = {k: v for k, v in params.items() if k in SAFE_DATA_QUERY_PARAMS}
        logger.info("data_query parameter validation: %d raw fields, %d safe fields", len(params), len(safe_params))

        if "products" in str(safe_params.get("data_type", "")):
            data_result = await query_products(**safe_params)
        else:
            data_result = await query_claims(**safe_params)

        return {**state, "data_result": data_result, "context_pack": None}


async def step5_answer(
    state: dict,
    chat_agent: Any,
    observer: ObservationCollector | None = None,
    fix_hint: str = "",
    reasoning_agent: Any = None,
) -> dict:
    """Step5: return the natural-language answer — the Agent generates the answer based on evidence (C1 + I3 + I6 + P3 fix).

    P3: supports the fix_hint parameter for the answer-quality repair loop.

    Node Contract (R2):
        - id: R2
        - decision: generate an answer with citations based on the retrieved evidence
        - input: {user_question, retrieved_evidence: [{ref_id, content, summary}]}
        - info: {citation_format, grounding_rule, offered_ref_ids}
        - instruct: answer rules + fix_hint (P3 repair loop)
        - output: {answer: str, citations: [{ref_id, quoted_text}]}
        - consumers: answer → user; citations → host validator + RecordStore
        - failure: ref_id not in the offered set → drop the citation; empty evidence → return 'not found in the documents'
    """
    # extract evidence from context_pack and build the structured input
    pack = state.get("context_pack")
    evidence_items = []
    offered_ref_keys: set[str] = set()

    if pack and pack.get("items"):
        for i, item in enumerate(pack["items"]):
            # I3: assign short citation keys (e1, e2, ...), do not expose chunk_id
            ref_id = f"e{i + 1}"
            offered_ref_keys.add(ref_id)
            evidence_items.append({
                "ref_id": ref_id,
                "content": item.get("content", ""),
                "summary": item.get("summary", ""),
            })

    # if there is a business-data result, also use it as evidence
    if state.get("data_result"):
        ref_id = "d1"
        offered_ref_keys.add(ref_id)
        evidence_items.append({
            "ref_id": ref_id,
            "content": json.dumps(state["data_result"], ensure_ascii=False, indent=2),
            "summary": "business data query result",
        })

    # P3: if there is a repair hint, add it to instruct
    quality_fix = ""
    if fix_hint:
        quality_fix = f"\n\nLast answer quality assessment: {fix_hint}\nPlease improve on the above issues in the current answer."

    # F3: enhance the prompt for multi-document comparison scenarios
    sub_query_diagnostic = ""
    sq_results = state.get("sub_query_results", [])
    is_comparison = bool(sq_results)
    if sq_results:
        empty_sub_queries = [r for r in sq_results if r["result_count"] == 0]
        if empty_sub_queries:
            missing_info = "; ".join(
                f"sub-query '{r['query']}' did not retrieve related content" for r in empty_sub_queries
            )
            sub_query_diagnostic = (
                f"\n\nF3 multi-step retrieval diagnostic: {missing_info}. "
                "Please clearly indicate in the answer which products the clause information is missing for. "
            )
            logger.warning("F3 retrieval incomplete: %d/%d sub-queries had no results", len(empty_sub_queries), len(sq_results))
        else:
            # F3 normal comparison scenario: enhance citation and detail requirements
            sub_query_diagnostic = (
                "\n\nThis is a multi-document comparison question; please follow these rules: "
                "1. cite the document sources of each product separately (e.g., [[ref:e1]] corresponds to product A, [[ref:e2]] corresponds to product B); "
                "2. the answer should be at least 200 characters, detailing the coverage, features and differences of each product; "
                "3. use a table or a bullet-by-bullet comparison form, ensuring every comparison dimension has a citation marker. "
            )

    t0 = time.perf_counter()
    try:
        # C1: choose the reasoning agent (deep-reasoning scenario) or the main agent (regular Q&A)
        agent_to_use = chat_agent
        if state.get("needs_reasoning") and reasoning_agent:
            agent_to_use = reasoning_agent
            logger.info("using the reasoning-enhanced agent (DeepSeek-R1-Distill-Qwen-7B) for complex reasoning")

        if evidence_items:
            result = await (
                agent_to_use
                .input({
                    "user_question": state["input"],
                    "retrieved_evidence": evidence_items,
                })
                .info({
                    "citation_format": "use [[ref:<ref_id>]] to mark sources in the answer, e.g., [[ref:e1]]",
                    "grounding_rule": "every factual statement must have a corresponding [[ref:xxx]] marker; statements without supporting evidence should be marked as 'no related content was found in the available materials'",
                    "quality_rule": "cite all relevant sources to support key facts; if there are multiple relevant sources in the evidence, try to cite at least 2; if there is only 1 relevant source, citing 1 is enough",
                    "offered_ref_ids": sorted(offered_ref_keys),
                })
                .instruct(
                    "Answer the user_question based on the retrieved_evidence. "
                    "Mark the source of every piece of information using the [[ref:<ref_id>]] format. "
                    "Do NOT fabricate information that is not present in the evidence. "
                    "CRITICAL: You MUST answer in English. The evidence may be in Chinese; translate and summarize it into fluent English. "
                    "The final answer shown to the user must be entirely in English."
                    + quality_fix
                    + sub_query_diagnostic
                )
                .output({
                    "answer": (str, "natural-language answer in English for the user, containing [[ref:xxx]] citation markers", "not_null"),
                    "citations": (
                        [{
                            "ref_id": (str, "the cited evidence ref_id (e.g., e1)", "not_null"),
                            "quoted_text": (str, "the quoted original snippet", "not_null"),
                        }],
                        "citation list (may be empty when there is no evidence)",
                        "allow_empty",
                    ),
                }, format="json")
                .async_start()
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            answer_text = result["answer"]
            citations = result.get("citations", [])

            # fix: extract the [[ref:xxx]] markers from the answer text and append them to the citations list
            # Qwen3-8B tends to use [[ref:xxx]] markers in the answer but returns an empty citations list.
            # If not supplemented, after post-processing replaces the markers the citations would still be empty, causing the quality check to fail.
            existing_ref_ids = {c.get("ref_id") for c in citations if isinstance(c, dict)}
            text_ref_keys = CITATION_PATTERN.findall(answer_text)
            for ref_key in text_ref_keys:
                if ref_key in offered_ref_keys and ref_key not in existing_ref_ids:
                    # find the corresponding original snippet from evidence_items
                    matching_item = None
                    for ei in evidence_items:
                        if ei.get("ref_id") == ref_key:
                            matching_item = ei
                            break
                    quoted = ""
                    if matching_item:
                        content = matching_item.get("content", "")
                        quoted = content[:120].replace("\n", " ").strip()
                        if len(content) > 120:
                            quoted += "..."
                    citations.append({
                        "ref_id": ref_key,
                        "quoted_text": quoted,
                    })
                    existing_ref_ids.add(ref_key)
                    logger.info("supplemented citation from answer text: %s", ref_key)

            # I3 host validation: check citation validity
            all_valid, valid_keys, invalid_keys = validate_citations(answer_text, offered_ref_keys)
            if not all_valid:
                logger.warning("found invalid citation keys: %s (valid set: %s)", invalid_keys, sorted(offered_ref_keys))
                # drop the citations of invalid references
                citations = [c for c in citations if c.get("ref_id") in offered_ref_keys]

            # map short keys back to the real source
            ref_to_source: dict[str, str] = {}
            pack_items = (pack or {}).get("items", [])
            for i, item in enumerate(pack_items):
                source_val = item.get("source") or item.get("chunk_id") or f"e{i + 1}"
                ref_to_source[f"e{i + 1}"] = source_val
            if state.get("data_result"):
                ref_to_source["d1"] = "business_data"
            sources = [ref_to_source.get(c["ref_id"], c["ref_id"]) for c in citations]

            # post-processing: replace [[ref:e1]] with readable numbers [1] and build source_details
            ref_to_num: dict[str, int] = {}
            source_details: list[dict] = []
            for ci, cite in enumerate(citations):
                ref_id = cite.get("ref_id", f"e{ci + 1}")
                num = ci + 1
                ref_to_num[ref_id] = num

                # find the corresponding original text from the context_pack items
                item_idx = -1
                if ref_id.startswith("e"):
                    try:
                        item_idx = int(ref_id[1:]) - 1
                    except ValueError:
                        pass
                pack_item = pack_items[item_idx] if 0 <= item_idx < len(pack_items) else {}

                # build the original snippet (truncate the first 120 characters)
                raw_content = pack_item.get("content", "")
                snippet = raw_content[:120].replace("\n", " ").strip()
                if len(raw_content) > 120:
                    snippet += "..."

                # assemble the title: document title · section title
                title_parts = []
                if pack_item.get("title"):
                    title_parts.append(_translate_title(pack_item["title"]))
                if pack_item.get("section_title"):
                    title_parts.append(_translate_title(pack_item["section_title"]))
                display_title = " · ".join(title_parts) if title_parts else _translate_title(pack_item.get("source", ref_id))

                source_details.append({
                    "num": num,
                    "ref_id": ref_id,
                    "title": display_title,
                    "source": pack_item.get("source", ref_id),
                    "quoted_text": cite.get("quoted_text", ""),
                    "snippet": snippet,
                })

            # replace [[ref:ex]] in the answer with [number]
            # refs not in citations are also replaced with numbers, preventing [[ref:xx]] from leaking to the user
            _next_num = len(citations) + 1

            def _replace_ref(match: re.Match) -> str:
                nonlocal _next_num
                ref_key = match.group(1)
                num = ref_to_num.get(ref_key)
                if num:
                    return f"[{num}]"
                # unknown ref: assign a new number and record it, avoiding duplicate assignment
                ref_to_num[ref_key] = _next_num
                source_details.append({
                    "num": _next_num,
                    "ref_id": ref_key,
                    "title": ref_key,
                    "source": ref_key,
                    "quoted_text": "",
                    "snippet": "",
                })
                _next_num += 1
                return f"[{_next_num - 1}]"

            answer_text = CITATION_PATTERN.sub(_replace_ref, answer_text)

            status = STATUS_COMPLETED if citations else STATUS_PARTIAL

            # I6: record the R2 observation
            if observer:
                # I3: mark the model actually used based on needs_reasoning
                r2_model = "DeepSeek-R1-Distill-Qwen-7B" if state.get("needs_reasoning") and reasoning_agent else "Qwen3-8B"
                observer.record_request(
                    node_id="R2",
                    input_data={
                        "user_question": state["input"],
                        "retrieved_evidence": evidence_items,
                    },
                    output_data={"answer": answer_text, "citations": citations},
                    duration_ms=elapsed_ms,
                    status="completed",
                    provider_model=r2_model,
                    consumer_edges=[
                        {"field": "answer", "consumer": "user", "validated": True},
                        {"field": "citations", "consumer": "host_validator(validate_citations)", "validated": all_valid},
                    ],
                )

            return {
                **state,
                "answer": answer_text,
                "citations": citations,
                "sources": sources,
                "source_details": source_details,
                "status": status,
                "r2_attempt": state.get("r2_attempt", 0) + 1,
            }
        else:
            # no-evidence scenario: fail-closed, do not fabricate
            agent_to_use = chat_agent
            if state.get("needs_reasoning") and reasoning_agent:
                agent_to_use = reasoning_agent
            result = await (
                agent_to_use
                .input({
                    "user_question": state["input"],
                    "retrieved_evidence": [],
                })
                .instruct(
                    "No relevant evidence was retrieved. Please tell the user: "
                    "'I couldn't find relevant content in the available insurance documents. Please add documents or try rephrasing your question.' "
                    "Do NOT fabricate an answer. Reply in English."
                )
                .output({
                    "answer": (str, "the reply in English informing the user that no content was found", "not_null"),
                }, format="json")
                .async_start()
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if observer:
                r2_model_no_ev = "DeepSeek-R1-Distill-Qwen-7B" if state.get("needs_reasoning") and reasoning_agent else "Qwen3-8B"
                observer.record_request(
                    node_id="R2",
                    input_data={"user_question": state["input"], "retrieved_evidence": []},
                    output_data={"answer": result["answer"]},
                    duration_ms=elapsed_ms,
                    status="completed",
                    provider_model=r2_model_no_ev,
                )
            return {
                **state,
                "answer": result["answer"],
                "citations": [],
                "sources": [],
                "status": STATUS_PARTIAL,
                "r2_attempt": state.get("r2_attempt", 0) + 1,
            }

    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.error("Step5 answer generation failed: %s", e)
        if observer:
            observer.record_request(
                node_id="R2",
                input_data={"user_question": state["input"], "evidence_count": len(evidence_items)},
                output_data={"error": str(e)},
                duration_ms=elapsed_ms,
                status="failed",
                error=str(e),
            )
        return {
            **state,
            "answer": f"answer generation failed: {e}",
            "citations": [],
            "sources": [],
            "status": STATUS_FAILED,
            "failure_reason": str(e),
            "r2_attempt": state.get("r2_attempt", 0) + 1,
        }


async def step5_quality_check(state: dict) -> tuple[bool, str]:
    """Step5 answer-quality check — host-side deterministic validation (P3).

    Returns:
        (pass: bool, fix_hint: str)
    """
    fix_hints = []
    answer = state.get("answer", "")
    citations = state.get("citations", [])

    # check 1: whether the answer is empty
    if not answer or len(answer.strip()) < 10:
        fix_hints.append("the answer is too short, please provide more detailed information")

    # check whether there is evidence available — skip the citation check without evidence (fail-closed scenarios should not retry)
    pack = state.get("context_pack")
    has_evidence = bool(pack and pack.get("items"))

    if has_evidence:
        # check 2: whether the citation count is sufficient
        # fix: check both the [[ref:xxx]] markers in the answer text and the structured citations list,
        # as well as the [N] numbered markers after post-processing.
        # note: step5_answer post-processing replaces [[ref:xxx]] with [N], so both formats must be supported.
        answer_ref_keys = set(CITATION_PATTERN.findall(answer))
        # also check the [N] numbered markers after post-processing
        numbered_refs = re.findall(r'\[(\d+)\]', answer)
        citation_count = len(citations)
        effective_ref_count = max(len(answer_ref_keys), citation_count, len(numbered_refs))
        if effective_ref_count < 1:
            fix_hints.append("insufficient citations; the answer must contain at least 1 [[ref:xxx]] citation marker, please regenerate the answer with citations based on the evidence")

        # check 3: whether there is a [[ref:]] marker, a [N] number, or structured citations
        has_ref_marker = (
            CITATION_PATTERN.search(answer)
            or len(numbered_refs) > 0
            or citation_count > 0
        )
        if not has_ref_marker:
            fix_hints.append("the answer is missing the [[ref:xxx]] citation marker")
    else:
        # no-evidence scenario: no mandatory citation requirement, avoiding meaningless retries
        logger.info("no-evidence scenario, skipping the citation quality check")

    if fix_hints:
        return False, "; ".join(fix_hints)
    return True, ""


async def run_pipeline(
    user_input: str,
    session_id: str,
    chat_agent: Any,
    session_registry: Any,
    rag_retriever: Any = None,
    query_rewriter: Any = None,
    reasoning_agent: Any = None,
    embedding_agent: Any = None,
    memory_store: list | None = None,
    max_retries: int = 3,
) -> dict:
    """Run the complete five-step business flow.

    P0-A: pass workspace_retrieve (retrieve_context) to fix the Step4 evidence-chain break.
    P1: support falling back to a Step2 retry when Step4 retrieval is insufficient (outer loop).
    P3: support the R2 answer-quality repair loop (inner loop).
    R5: integrate Query rewriting (optional); expand fuzzy queries with the LLM.
    P1-4: integrate Namespace long-term memory recall (optional).

    Args:
        user_input: the user input
        session_id: the session identifier
        chat_agent: the chat Agent
        session_registry: the Session registry
        rag_retriever: the RAG retriever (optional)
        query_rewriter: the query rewriter (optional; skipped when None)
        reasoning_agent: the reasoning-enhanced Agent (optional)
        embedding_agent: the Embedding Agent (optional, used for Namespace memory recall)
        memory_store: the Namespace long-term memory store (optional, list[MemoryRecord])
        max_retries: the maximum number of retries

    Returns:
        the final state dictionary (including answer, citations, sources, status, observations, etc.)
    """
    # I6: create the observation collector
    observer = ObservationCollector()

    # Step1: understand (P1-4: pass embedding_agent + memory_store for Namespace memory recall)
    state = await step1_understand(
        user_input, session_id, session_registry, chat_agent,
        embedding_agent=embedding_agent,
        memory_store=memory_store,
    )

    # P1: outer retry loop (Step2→Step3→Step4→quality check→Step2)
    state["plan_retry_count"] = 0
    state["retrieval_retry_count"] = 0
    state["r2_attempt"] = 0
    max_outer_retries = max_retries + 1  # total outer attempts

    for outer_attempt in range(max_outer_retries):
        # Step2 + Step3: plan + validate (C3: retry loop with termination rule)
        for plan_attempt in range(max_retries):
            state = await step2_plan(state, chat_agent, observer=observer)
            state = await step3_validate(state, chat_agent)

            if state.get("validated"):
                break

            # C3: check whether it has been marked as blocked
            if state.get("status") == STATUS_BLOCKED:
                logger.error("query blocked: %s", state.get("block_reason"))
                state["observations"] = observer.get_all()
                state["observation_summary"] = observer.summary()
                return state

            if plan_attempt < max_retries - 1:
                logger.info(
                    "validation failed, retrying %d/%d: %s",
                    plan_attempt + 1, max_retries, state.get("validation_errors"),
                )

        # if blocked, return directly
        if state.get("status") == STATUS_BLOCKED:
            state["observations"] = observer.get_all()
            state["observation_summary"] = observer.summary()
            return state

        # P0-A: Step4 — fetch data (pass workspace_retrieve=retrieve_context)
        # R5: pass query_rewriter, expand fuzzy queries with the LLM
        state = await step4_fetch(
            state,
            rag_retriever=rag_retriever,
            workspace_retrieve=retrieve_context,
            chat_agent=chat_agent,
            query_rewriter=query_rewriter,
            observer=observer,
        )

        # P1: retrieval quality check — fall back to a Step2 retry when insufficient
        if state.get("query_type") == "rag_query":
            pack = state.get("context_pack", {})
            items = pack.get("items", []) if pack else []
            if len(items) < MIN_RETRIEVAL_ITEMS and state["retrieval_retry_count"] < MAX_RETRIEVAL_RETRIES:
                state["retrieval_retry_count"] += 1
                current_error = f"insufficient retrieval: only {len(items)} results, need ≥ {MIN_RETRIEVAL_ITEMS}"
                # I1: check whether it is the same as the last failure reason
                last_error = state.get("last_retrieval_error", "")
                if current_error == last_error:
                    state["same_retrieval_error_count"] = state.get("same_retrieval_error_count", 0) + 1
                else:
                    state["same_retrieval_error_count"] = 0
                state["last_retrieval_error"] = current_error
                if state.get("same_retrieval_error_count", 0) >= 2:
                    logger.error("retrieval retried 3 times with the same issue, terminating: %s", current_error)
                    state["status"] = STATUS_BLOCKED
                    state["block_reason"] = current_error
                    break
                logger.warning(
                    "insufficient retrieval: %d items (need ≥ %d), retrying planning attempt %d",
                    len(items), MIN_RETRIEVAL_ITEMS, state["retrieval_retry_count"],
                )
                # reset the planning count and restart Step2
                state["plan_retry_count"] = 0
                state["validation_errors"] = [current_error]
                # M3: restore the original query on retrieval retry (avoid repeated failures caused by rewriting)
                if state.get("original_query"):
                    state["query_params"] = {"query": state["original_query"]}
                    logger.info("retrieval retry: restored the original query '%s...'", state["original_query"][:50])
                continue  # back to the start of the outer loop

        # Step5: generate the answer
        state = await step5_answer(state, chat_agent, observer=observer, reasoning_agent=reasoning_agent)

        # P3: answer-quality repair loop (at most 2 repairs)
        max_r2_retries = 2
        last_fix_hint = ""
        for r2_attempt in range(max_r2_retries):
            quality_pass, fix_hint = await step5_quality_check(state)
            if quality_pass:
                break
            # I1: check whether fix_hint is the same as last time
            if fix_hint == last_fix_hint and r2_attempt > 0:
                logger.error("R2 repair loop encountered the same issue, terminating repair: %s", fix_hint)
                state["status"] = STATUS_PARTIAL
                state["failure_reason"] = f"R2 repair failed to converge: {fix_hint}"
                break
            last_fix_hint = fix_hint
            if r2_attempt < max_r2_retries - 1:
                logger.info(
                    "R2 quality check failed (%d/%d): %s",
                    r2_attempt + 1, max_r2_retries, fix_hint,
                )
                state = await step5_answer(state, chat_agent, observer=observer, fix_hint=fix_hint, reasoning_agent=reasoning_agent)

        # successfully generated the answer, break out of the outer loop
        if state.get("status") not in (STATUS_BLOCKED, STATUS_FAILED):
            break

        # if it failed but there are still outer retry attempts left, reset and retry
        if outer_attempt < max_outer_retries - 1:
            logger.info(
                "outer retry %d/%d: status=%s",
                outer_attempt + 1, max_outer_retries, state.get("status"),
            )
            state["plan_retry_count"] = 0
            state["validation_errors"] = [f"outer retry: previous status={state.get('status')}"]
            continue

    # Update Session
    if state.get("session"):
        session = state["session"]
        if hasattr(session, "async_add_chat_history"):
            await session.async_add_chat_history([
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": str(state.get("answer", ""))},
            ])

    # C1: Session persistence + memory extraction
    try:
        from src.session.persistence import extract_memo_from_turn
        memo_entry = extract_memo_from_turn(
            user_input=user_input,
            answer=state.get("answer", ""),
            citations=state.get("citations"),
            query_type=state.get("query_type"),
        )
        # append the extracted memory to the session memo
        # note: Session.memo is a read-only @property (no setter); it must be modified in place
        if state.get("session") and hasattr(session, "memo"):
            memo = session.memo
            if isinstance(memo, dict):
                turn_memos = memo.get("turn_memos", [])
                turn_memos.append(memo_entry)
                memo["turn_memos"] = turn_memos[-20:]
            else:
                logger.debug("Session.memo is not a dict type (%s), skipping memory update", type(memo).__name__)

        # persist to disk
        if hasattr(session_registry, "save_session"):
            session_registry.save_session(session_id)
            logger.debug("Session persisted: %s", session_id)
    except Exception as e:
        logger.warning("Session persistence/memory extraction failed: %s", e)

    # I5: ensure the terminal status is set
    if not state.get("status"):
        state["status"] = STATUS_COMPLETED

    # I6: attach the observation records to the returned result
    state["observations"] = observer.get_all()
    state["observation_summary"] = observer.summary()

    logger.info(
        "five-step business flow completed: session=%s, status=%s, sources=%s, obs=%s",
        session_id, state.get("status"), state.get("sources", []),
        state.get("observation_summary"),
    )
    return state