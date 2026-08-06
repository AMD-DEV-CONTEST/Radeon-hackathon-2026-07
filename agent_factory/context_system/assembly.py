from __future__ import annotations

from agent_factory.context_system.schema import AssemblyPolicy, ContextCandidate, ContextQuery, LLMContextFrame


def assemble_context_frame(
    *,
    node_id: str,
    query: ContextQuery,
    candidates: list[ContextCandidate],
    policy: AssemblyPolicy,
) -> LLMContextFrame:
    selected: list[ContextCandidate] = []
    source_counts: dict[str, int] = {}
    total_tokens = 0
    seen_content: set[str] = set()
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (float(item.score), -int(item.token_estimate), item.source_id, item.candidate_id),
        reverse=True,
    )
    for candidate in sorted_candidates:
        content_key = " ".join(candidate.content.split()).lower()
        if not content_key or content_key in seen_content:
            continue
        source_limit = int(policy.per_source_limits.get(candidate.source_id, policy.max_items_total))
        if source_counts.get(candidate.source_id, 0) >= source_limit:
            continue
        next_tokens = total_tokens + candidate.token_estimate
        if next_tokens > policy.max_tokens_total and selected:
            continue
        selected.append(candidate)
        seen_content.add(content_key)
        source_counts[candidate.source_id] = source_counts.get(candidate.source_id, 0) + 1
        total_tokens = next_tokens
        if len(selected) >= policy.max_items_total or total_tokens >= policy.max_tokens_total:
            break
    text = _frame_text(selected)
    return LLMContextFrame(
        node_id=node_id,
        query=query.text,
        items=selected,
        token_estimate=total_tokens,
        text=text,
    )


def _frame_text(items: list[ContextCandidate]) -> str:
    if not items:
        return ""
    lines = ["Runtime evidence for this turn. Use only what is directly relevant:"]
    for item in items:
        lines.append(f"- {item.content.strip()}")
    return "\n".join(lines)
