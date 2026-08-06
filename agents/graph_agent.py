"""GraphVoice Agent - conversational agent with memory and session management."""

import uuid
from dataclasses import dataclass, field

from config.settings import MAX_CONVERSATION_HISTORY
from database.schema_loader import format_schema_for_llm, get_schema
from utils.logger import setup_logging
from utils.timing import timing

logger = setup_logging(__name__)

# Cached schema (shared across sessions)
_CACHED_SCHEMA: str = ""


DIRECTOR_SYSTEM_PROMPT = """You are a natural, conversational agent named GraphVoice.
You can chat casually AND query a movie database.

Your personality: warm, concise, helpful. Like a knowledgeable friend.

## Capabilities
1. **Casual Chat**: Respond naturally to greetings, thanks, small talk
2. **Database Query**: When the user asks about actors, movies, directors, use cypher
3. **Memory Reference**: You have access to conversation history and known facts

## Rules
- Be conversational, not robotic
- When the user asks a DB question, respond with "QUERY_DB"
- For everything else, respond naturally in 1-3 sentences
- Reference past conversations when relevant
- Respond in the same language as the user
- If user asks "what do you remember" or "what did we talk about", summarize memory

## Memory Context
{memory_context}

## User Says
{user_query}

Respond naturally, or "QUERY_DB" if this is a database query that needs Cypher."""


@dataclass
class AgentState:
    """Per-session conversation state."""

    session_id: str = ""
    messages: list[dict] = field(default_factory=list)
    conversation_history: list[str] = field(default_factory=list)


class GraphVoiceAgent:
    """Conversational agent with memory, session management, and dual-mode response.

    Two modes:
      - Chat mode: casual conversation driven by Director LLM
      - Query mode: database pipeline (cypher → execute → interpret)
    """

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.state = AgentState(session_id=self.session_id)
        self._ensure_schema()

    @staticmethod
    def _ensure_schema():
        global _CACHED_SCHEMA
        if not _CACHED_SCHEMA:
            try:
                schema_data = get_schema()
                _CACHED_SCHEMA = format_schema_for_llm(schema_data)
                logger.info("Schema cached: %d entries", len(schema_data))
            except Exception as e:
                logger.warning("Schema load failed: %s", e)
                _CACHED_SCHEMA = "(database schema unavailable)"

    @property
    def db_schema(self) -> str:
        return _CACHED_SCHEMA

    @timing(name="agent_process")
    def process(self, user_query: str) -> str:
        """Process user input end-to-end with memory context.

        Returns natural language response.
        """
        if not user_query or not user_query.strip():
            return "请问有什么可以帮您的？"

        self.state.messages.append({"role": "user", "content": user_query})

        # Step 1: Load memory context from Neo4j
        memory_context = self._load_memory()

        # Step 2: Director LLM decides action
        action = self._direct(user_query, memory_context)

        if action == "QUERY_DB":
            reply = self._run_query_pipeline(user_query)
        else:
            reply = action

        # Step 3: Store in memory graph
        self._save_to_memory(user_query, reply)

        # Step 4: Update in-memory history
        self._add_to_history(user_query, reply)
        self.state.messages.append({"role": "assistant", "content": reply})

        return reply

    # ─── Director LLM ────────────────────────────────────────────

    def _direct(self, user_query: str, memory_context: str) -> str:
        """Ask the LLM whether to chat or query the database."""
        from openai import OpenAI

        from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL

        if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
            # Fallback: simple keyword + cypher check
            return self._fallback_direct(user_query)

        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

        prompt = DIRECTOR_SYSTEM_PROMPT.format(
            memory_context=memory_context or "(no memory yet)",
            user_query=user_query,
        )

        try:
            resp = client.chat.completions.create(
                model=QWEN_LLM_MODEL,
                messages=[{"role": "system", "content": prompt}],
                temperature=0.3,
                max_tokens=100,
            )
            result = resp.choices[0].message.content.strip()

            if result == "QUERY_DB":
                logger.debug("Director: QUERY_DB for '%s'", user_query[:60])
                return "QUERY_DB"
            else:
                logger.debug("Director: chat for '%s'", user_query[:60])
                return result

        except Exception as e:
            logger.warning("Director LLM failed: %s, using fallback", e)
            return self._fallback_direct(user_query)

    def _fallback_direct(self, query: str) -> str:
        """Fallback keyword-based director (no API key)."""
        from agents.tools.cypher_generator import generate_cypher

        query_lower = query.lower().strip()

        # Obvious chitchat
        simple_chat = [
            "你好",
            "嗨",
            "hello",
            "hi",
            "hey",
            "good morning",
            "早上好",
            "good night",
            "晚安",
            "谢谢",
            "感谢",
            "再见",
            "bye",
            "who are you",
            "你是谁",
            "what can you do",
            "你能做什么",
        ]
        if any(kw in query_lower for kw in simple_chat):
            return self._legacy_handle_chitchat(query)

        # Try DB: if cypher generator produces a real query, it's a DB question
        cypher = generate_cypher(
            user_query=query,
            db_schema=self.db_schema,
            conversation_history=self.state.conversation_history,
        )

        if cypher != "NOT_A_QUERY":
            return "QUERY_DB"

        # Otherwise, natural chitchat
        return self._legacy_handle_chitchat(query)

    # ─── Query Pipeline (GraphRAG + safe templates) ──────────────

    def _run_query_pipeline(self, user_query: str) -> str:
        """Run query using GraphRAG-style retrieval + safe Cypher templates."""
        from agents.tools.cypher_templates import graph_rag_query
        from agents.tools.result_interpreter import interpret_result

        # Try GraphRAG: keyword search + neighborhood traversal
        context = graph_rag_query(user_query, top_k=3, hop_distance=2)

        if context:
            # Format retrieved context for the LLM
            context_text = "Retrieved from graph:\n"
            for item in context:
                entry = item["entry"]
                context_text += f"\nEntity: {entry['name']} ({entry['type']})\n"
                for n in item.get("neighbors", [])[:5]:
                    context_text += (
                        f"  -[{n['relation']}]-> {n['target_name']} ({n['target_type']})\n"
                    )
                for ev in item.get("events", [])[:3]:
                    participants = ", ".join(ev.get("co_participants", []))
                    context_text += (
                        f"  Event: {ev['event']} [{ev.get('time_period', '')}] ({participants})\n"
                    )

            # Use interpreter over the graph-context
            from openai import OpenAI

            from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL

            client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
            resp = client.chat.completions.create(
                model=QWEN_LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "Answer the user's question based on the graph context. "
                        "Be concise and warm. Answer in the language the user used.",
                    },
                    {
                        "role": "user",
                        "content": f"Graph context:\n{context_text}\n\nQuestion: {user_query}",
                    },
                ],
                temperature=0.3,
                max_tokens=300,
            )
            answer = resp.choices[0].message.content.strip()
            if answer:
                return answer

        # Fallback to legacy Cypher generation if GraphRAG finds nothing
        from agents.tools.cypher_generator import generate_cypher
        from agents.tools.db_executor import execute_db

        cypher = generate_cypher(
            user_query=user_query,
            db_schema=self.db_schema,
            conversation_history=self.state.conversation_history,
        )

        if cypher == "NOT_A_QUERY":
            return "我主要可以帮您查询电影数据库和已有的故事记忆。您想问什么？"

        db_output = execute_db(cypher)
        if not db_output["success"]:
            return db_output["error"] or "查询执行失败，请重试。"

        return interpret_result(db_output["data"], user_query)

    # ─── Memory Integration ──────────────────────────────────────

    def _load_memory(self) -> str:
        """Load memory context from Neo4j for this session."""
        try:
            from memory.memory_graph import get_session_summary

            return get_session_summary(self.session_id)
        except Exception as e:
            logger.debug("Memory load failed: %s", e)
            return ""

    def _save_to_memory(self, query: str, answer: str) -> None:
        """Save Q&A pair and extract entities to Neo4j.

        Uses hierarchical structurization for long answers (>900 chars).
        """
        try:
            from memory.memory_graph import (
                extract_entities,
                store_entities,
                store_message,
            )

            store_message(self.session_id, "user", query)
            store_message(self.session_id, "assistant", answer)

            # Use hierarchical extraction for long answers
            combined = query + " " + answer
            if len(combined) > 900:
                entities = extract_entities(combined)
            else:
                entities = extract_entities(combined)

            if entities:
                store_entities(self.session_id, entities)

            if any(w in query.lower() for w in ["喜欢", "like", "favorite", "最爱"]):
                from memory.memory_graph import store_fact

                store_fact(self.session_id, "preference:" + query[:50], answer[:200])

        except Exception as e:
            logger.debug("Memory save failed (non-critical): %s", e)

    # ─── Legacy Chitchat (fallback) ──────────────────────────────

    def _legacy_handle_chitchat(self, query: str) -> str:
        """Keyword-based chitchat handler (used when Director LLM unavailable)."""
        q = query.lower().strip()
        if any(w in q for w in ["good morning", "早上好"]):
            return "早上好！有什么关于电影的问题想问吗？"
        if any(w in q for w in ["good night", "晚安"]):
            return "晚安！随时可以回来。"
        if any(w in q for w in ["你好", "hello", "hi", "hey"]):
            return "你好！我是 GraphVoice，可以帮你查电影信息。有什么想问的吗？"
        if any(w in q for w in ["谢谢", "感谢"]):
            return "不客气！还有什么可以帮你的吗？"
        if any(w in q for w in ["再见", "bye"]):
            return "再见！随时可以回来。"
        if any(w in q for w in ["who are you", "你是谁"]):
            return "我是 GraphVoice，一个能聊电影、查演员、记对话的语音助手。"
        return "有什么关于电影的问题想问吗？"

    # ─── History Management ──────────────────────────────────────

    def _add_to_history(self, query: str, answer: str) -> None:
        """Add Q&A to conversation history, respecting MAX_HISTORY."""
        self.state.conversation_history.append(f"Q: {query}")
        self.state.conversation_history.append(f"A: {answer}")
        limit = MAX_CONVERSATION_HISTORY * 2
        if len(self.state.conversation_history) > limit:
            self.state.conversation_history = self.state.conversation_history[-limit:]


# ─── Session Registry ─────────────────────────────────────────────


_sessions: dict[str, GraphVoiceAgent] = {}


def get_or_create_agent(session_id: str | None = None) -> GraphVoiceAgent:
    """Get existing agent for session, or create a new one."""
    if session_id and session_id in _sessions:
        return _sessions[session_id]

    agent = GraphVoiceAgent(session_id=session_id)
    if agent.session_id:
        _sessions[agent.session_id] = agent
    return agent
