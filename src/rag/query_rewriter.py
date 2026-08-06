"""LLM Query rewriting: when the user question is vague, add context to expand the query.

Trigger conditions (optional):
1. the query is too short (< 5 characters)
2. the query contains a pronoun but lacks context ("how is that claimed")
3. the query contains an ambiguous word ("it", "this", "that")
4. automatically triggered when the outer retrieval is insufficient (called in the P1 loop)

Rewriting strategy:
- add context based on the conversation history (e.g., replace "that" with the specific product name mentioned earlier)
- expand abbreviations (e.g., "employer insurance" → "employer liability insurance")
- add synonyms (e.g., "claims" → "claims claims process claims conditions")
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _is_query_vague(query: str, chat_history: list | None = None) -> bool:
    """Determine whether the query is vague and needs rewriting.

    Args:
        query: the user query
        chat_history: the conversation history (optional)

    Returns:
        True if the query is vague and needs rewriting
    """
    # rule 1: the query is too short
    if len(query.strip()) < 5:
        return True

    # rule 2: contains a pronoun but lacks context
    vague_pronouns = ["that", "this", "it", "the", "its", "mentioned before", "just said"]
    if any(pronoun in query for pronoun in vague_pronouns):
        if chat_history and len(chat_history) > 0:
            return True

    # rule 3: contains an ambiguous abbreviation
    ambiguous_terms = ["employer insurance", "liability insurance", "accident insurance", "medical insurance", "social insurance"]
    if any(term in query for term in ambiguous_terms):
        return True

    return False


class QueryRewriter:
    """LLM query rewriter.

    Rewrites/expands the user query before RAG retrieval to improve retrieval recall.
    Rewriting is optional and only triggered when the query is vague or the retrieval is insufficient.
    """

    def __init__(self, chat_agent: Any = None, enabled: bool = True):
        self.chat_agent = chat_agent
        self.enabled = enabled

    def should_rewrite(self, query: str, chat_history: list | None = None) -> bool:
        """Determine whether the query needs rewriting."""
        if not self.enabled or not self.chat_agent:
            return False
        return _is_query_vague(query, chat_history)

    async def rewrite(
        self,
        query: str,
        chat_history: list | None = None,
        memo: dict | None = None,
    ) -> str:
        """Use the LLM to rewrite/expand the user query.

        Args:
            query: the original query
            chat_history: the conversation history (used to add context)
            memo: the Session memo (structured summary)

        Returns:
            the rewritten query (if rewriting fails, the original query is returned)
        """
        if not self.chat_agent:
            return query

        # build the context
        recent_history = ""
        if chat_history:
            # take the most recent 3 turns
            recent = chat_history[-6:] if len(chat_history) > 6 else chat_history
            recent_history = "\n".join(
                f"{'User' if msg.get('role') == 'user' else 'Assistant'}: {msg.get('content', '')[:200]}"
                for msg in recent
            )

        memo_str = ""
        if memo:
            memo_str = str(memo)[:500]

        try:
            result = await (
                self.chat_agent
                .input({
                    "original_query": query,
                    "chat_history": recent_history,
                    "memo": memo_str,
                })
                .instruct(
                    "You are a business query-rewriting assistant. Based on the conversation history and context, rewrite the user's query to make it clearer and more specific. "
                    "Rewriting rules:\n"
                    "1. replace pronouns (that, it, this) with the specific insurance product name mentioned earlier\n"
                    "2. expand abbreviations (employer insurance → employer liability insurance)\n"
                    "3. add synonyms to improve retrieval recall (claims → claims process claims conditions claims criteria)\n"
                    "4. keep the core intent of the original query unchanged\n"
                    "5. if the original query is already clear enough, return it verbatim\n"
                    "Return only the rewritten query text, without explanation."
                )
                .output({
                    "rewritten_query": (str, "the rewritten query text", "not_null"),
                    "rewrite_reason": (str, "the rewrite reason (brief)", "allow_empty"),
                }, format="json")
                .async_start()
            )

            rewritten = result.get("rewritten_query", query)
            reason = result.get("rewrite_reason", "")

            if rewritten.strip() and rewritten.strip() != query.strip():
                logger.info(
                    "query rewrite: '%s' → '%s' (reason: %s)",
                    query[:50], rewritten[:50], reason,
                )
                return rewritten.strip()
            else:
                logger.debug("query does not need rewriting: %s", query[:50])
                return query

        except Exception as e:
            logger.warning("query rewrite failed, using the original query: %s", e)
            return query