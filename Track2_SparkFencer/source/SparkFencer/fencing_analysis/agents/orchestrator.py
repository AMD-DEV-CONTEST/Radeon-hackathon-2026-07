"""Coach agent orchestration (LangChain tool-calling, fully local).

A conversational fencing-coach agent that plans and executes multi-step tasks
by calling tools over previously analyzed sessions (outputs/<name>/), backed
by a local LLM served through an OpenAI-compatible endpoint (ollama / vLLM /
llama.cpp — the same abstraction used by the vision reviewers, so the whole
stack stays on-device).

Capabilities demonstrated:
  - 工具调用: every answer is grounded in tool results, not model guesses
  - 多步骤任务规划: the agent chains list -> query -> compare -> evidence
  - 本地多轮记忆: chat history threads through the executor
"""

import json
import os
import re
import uuid

from ..security import (audit_tool, require_child_path, require_local_endpoint,
                        require_model_endpoint)

SESSIONS_ROOT = "outputs"
MEMORY_ROOT = os.path.join(SESSIONS_ROOT, ".agent_memory")

SYSTEM_PROMPT = """You are SparkFencer's fencing coach assistant, running in a private deployment.

Rules:
1. Ground every answer in real tool results. State clearly when data is insufficient; never invent figures.
2. For complex questions, plan and call tools in sequence (for example list_sessions, then query or compare).
3. When citing an event, give its start/end time and direct the user to the main replay; never cite a standalone evidence-clip path.
4. Reply exclusively in the same language as the latest user question. English questions require an English-only answer; Chinese questions require a Chinese-only answer. Do not mix languages except for unavoidable proper nouns, model names, or measured units.
5. Style dimensions: aggression, territory, tempo, distance (close-range preference), and technique.
6. For technical points, tactical advice, or training methods, call search_knowledge first and cite sources in the answer. If retrieval has no answer, say that the recommendation is coaching judgment.
7. Use each session's weapon field. When it is general, call the weapon unspecified; do not infer a weapon.
/no_think"""


def _response_language_instruction(question):
    """Return a per-turn instruction without relying on the UI locale."""
    if re.search(r"[\u4e00-\u9fff]", question or ""):
        return "Respond only in Chinese for this turn."
    if re.search(r"[A-Za-z]", question or ""):
        return "Respond only in English for this turn."
    return "Respond in the user's language for this turn."


def _session_dir(session):
    path = require_child_path(SESSIONS_ROOT, session)
    if not os.path.isdir(path):
        raise ValueError(f"场次不存在: {session}")
    audit_tool("read_session", details={"session": session})
    return path


def _load_events(session):
    path = os.path.join(_session_dir(session), "events.json")
    if not os.path.exists(path):
        raise ValueError(f"该场次尚未完成分析(缺 events.json): {session}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def build_tools(enable_rag=True, rag_config=None):
    from langchain_core.tools import tool

    rag_config = rag_config or {}
    rag_provider = rag_config.get("provider", "ollama")
    rag_base_url = rag_config.get("base_url")
    rag_embed_model = rag_config.get("model", "bge-m3")
    if rag_base_url:
        require_local_endpoint(rag_base_url)

    @tool
    def list_sessions() -> str:
        """列出所有已分析的比赛/训练场次及其基本信息(时长、回合数、事件数)。回答任何针对场次的问题前先调用它确认场次名。"""
        sessions = []
        if os.path.isdir(SESSIONS_ROOT):
            for name in sorted(os.listdir(SESSIONS_ROOT)):
                epath = os.path.join(SESSIONS_ROOT, name, "events.json")
                if not os.path.exists(epath):
                    continue
                with open(epath, encoding="utf-8") as f:
                    e = json.load(f)
                sessions.append({
                    "session": name,
                    "duration_sec": e["video"]["duration_sec"],
                    "weapon": e.get("weapon"),
                    "phrases": len(e.get("phrases", [])),
                    "lunges": len(e["footwork"]["lunges"]),
                    "actions": len(e.get("actions", [])),
                })
        audit_tool("list_sessions", details={"count": len(sessions)})
        return _dumps(sessions or {"error": "还没有已分析的场次"})

    @tool
    def get_session_overview(session: str) -> str:
        """获取一个场次的总体统计:双方检出率、前进/后退、弓步数、峰值速度、攻防次数、反应时间、距离统计。"""
        e = _load_events(session)
        return _dumps({"stats": e["stats"], "distance": {
            k: v for k, v in e.get("distance", {}).items() if k != "series"}})

    @tool
    def get_style_profiles(session: str) -> str:
        """获取一个场次双方剑手的打法画像(五维评分、风格标签、先动率、站位、弓步节奏)与对位解读。"""
        e = _load_events(session)
        style = e.get("style")
        return _dumps(style or {"error": "该场次无打法数据,需重跑 analysis"})

    @tool
    def query_events(session: str, event_type: str = "", fencer: str = "", limit: int = 10) -> str:
        """查询场次中的候选事件。event_type 可为 lunge/attack/parry/counter/空(全部);fencer 可为 left/right/空。返回时间点与特征。"""
        e = _load_events(session)
        out = []
        if event_type in ("", "lunge"):
            for l in e["footwork"]["lunges"]:
                if fencer and l["fencer"] != fencer:
                    continue
                out.append({"type": "lunge", **{k: l[k] for k in
                            ("fencer", "time_sec", "spread_m", "recovery_sec", "confidence")}})
        if event_type != "lunge":
            for a in e.get("actions", []):
                if event_type and a["type"] != event_type:
                    continue
                if fencer and a["fencer"] != fencer:
                    continue
                out.append({k: a[k] for k in ("id", "type", "fencer", "start_sec", "confidence")})
        out.sort(key=lambda x: -x.get("confidence", 0))
        return _dumps({"count": len(out), "events": out[:limit]})

    @tool
    def get_evidence(session: str, event_id: str) -> str:
        """获取某事件的开始/结束回放时间及 VLM 关键帧信息。回看应在主视频画布按时间段播放。"""
        path = os.path.join(_session_dir(session), "evidence_manifest.json")
        if not os.path.exists(path):
            return _dumps({"error": "该场次无证据清单"})
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)["events"]
        for ev in manifest:
            if ev["id"] == event_id or ev["id"].startswith(event_id):
                return _dumps({k: ev.get(k) for k in
                               ("id", "kind", "fencer", "start_sec", "end_sec", "playback_start_sec",
                                "playback_end_sec", "keyframes")})
        return _dumps({"error": f"未找到事件 {event_id}",
                       "available": [ev["id"] for ev in manifest][:20]})

    @tool
    def compare_sessions(session_a: str, session_b: str) -> str:
        """对比两个场次:双方统计与打法五维的差值。用于纵向进步分析或不同对手风格对比。"""
        ea, eb = _load_events(session_a), _load_events(session_b)
        cmp = {}
        for side in ("left", "right"):
            sa, sb = ea["stats"][side], eb["stats"][side]
            entry = {
                "lunges": [sa["footwork"]["lunge_count"], sb["footwork"]["lunge_count"]],
                "peak_speed_ms": [sa["footwork"]["peak_speed_ms"], sb["footwork"]["peak_speed_ms"]],
                "attacks": [sa["attack_count"], sb["attack_count"]],
                "defenses": [sa["defense_count"], sb["defense_count"]],
            }
            if ea.get("style") and eb.get("style"):
                pa, pb = ea["style"]["profiles"][side], eb["style"]["profiles"][side]
                entry["style_delta"] = {k: round(pb[k] - pa[k], 3) for k in
                                        ("aggression", "territory", "tempo", "distance", "technique")}
                entry["style_labels"] = [pa.get("style_label"), pb.get("style_label")]
            cmp[side] = entry
        return _dumps({"a": session_a, "b": session_b, "per_side [a,b]": cmp})

    @tool
    def search_bout_archive(query: str, weapon: str = "", event_kind: str = "", limit: int = 8) -> str:
        """跨多个已分析视频做语义检索。返回场次、事件时间段和匹配理由；随后可用 get_evidence 回放。"""
        try:
            import functools
            from ..rag.store import _embed
            from ..rag.session_store import SessionStore
            embedder = functools.partial(_embed, model=rag_embed_model, base_url=rag_base_url,
                                         provider=rag_provider)
            results = SessionStore(embedder=embedder).search(query, k=max(1, min(limit, 20)),
                                            weapon=weapon or None, kind=event_kind or None)
            return _dumps({"results": results} if results else {"results": [], "note": "场次索引为空，请先完成分析或检查本地嵌入服务。"})
        except Exception as exc:
            return _dumps({"error": f"跨场次检索失败: {exc}"})

    _store_cache = {}

    @tool
    def search_knowledge(query: str) -> str:
        """检索本地击剑知识库(规则/步法/进攻防守技术/距离管理/打法应对/训练处方/复盘方法)。回答技术、战术、训练建议类问题时必须先调用它,并在回答中标注出处。"""
        try:
            audit_tool("search_knowledge", details={"query_length": len(query)})
            if "store" not in _store_cache:
                from ..rag.store import KnowledgeStore
                _store_cache["store"] = KnowledgeStore("knowledge/.index", base_url=rag_base_url,
                                                       provider=rag_provider)
            results = _store_cache["store"].search(query, k=4)
        except FileNotFoundError:
            return _dumps({"error": "知识库索引未构建,先运行 scripts/build_knowledge.py"})
        except Exception as exc:
            return _dumps({"error": f"知识检索失败: {exc}"})
        return _dumps({"results": results} if results else {"results": [], "note": "未检索到相关内容"})

    tools = [list_sessions, get_session_overview, get_style_profiles,
             query_events, get_evidence, compare_sessions, search_bout_archive]
    if enable_rag:
        tools.append(search_knowledge)
    return tools


def create_coach_agent(base_url=None, model=None, api_key="none", enable_rag=True, rag_config=None):
    """LangChain 1.x create_agent (langgraph-based tool-calling loop).

    *base_url*/*model* configure the chat LLM; *rag_config* (provider/base_url/model)
    configures the embedding service used for RAG. The two are independent —
    e.g. the chat LLM can run on ollama while embeddings come from a separate
    llama.cpp instance, or vice versa.
    """
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI

    base_url = base_url or os.environ.get("VLM_BASE_URL", "http://127.0.0.1:11434/v1")
    require_model_endpoint(base_url)
    model = model or os.environ.get("AGENT_MODEL", "qwen3:32b")
    api_key = (api_key if api_key not in (None, "", "none")
               else os.environ.get("VLM_API_KEY", "none"))

    llm = ChatOpenAI(base_url=base_url, api_key=api_key, model=model, temperature=0.2)
    prompt = SYSTEM_PROMPT
    if not enable_rag:
        prompt += "\nKnowledge retrieval is disabled for this conversation; state when advice is coaching judgment."
    tools = build_tools(enable_rag=enable_rag, rag_config=rag_config)
    return create_agent(model=llm, tools=tools, system_prompt=prompt)


class CoachChat:
    """Multi-turn wrapper keeping local conversation memory."""

    def __init__(self, thread_id=None, verbose=True, **kwargs):
        self.thread_id = thread_id or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", self.thread_id):
            raise ValueError("非法会话标识")
        os.makedirs(MEMORY_ROOT, exist_ok=True)
        self.memory_path = os.path.join(MEMORY_ROOT, f"{self.thread_id}.json")
        self.agent = create_coach_agent(**kwargs)
        self.messages = self._load_memory()
        self.verbose = verbose

    def _load_memory(self):
        if not os.path.exists(self.memory_path):
            return []
        try:
            with open(self.memory_path, encoding="utf-8") as f:
                messages = json.load(f).get("messages", [])
            if not isinstance(messages, list):
                return []
            # Newer LangChain agents return BaseMessage objects.  Persist them
            # with the official type/data representation so tool-call context
            # survives a WebUI or CLI restart.
            if messages and all(isinstance(m, dict) and "type" in m and "data" in m
                                for m in messages):
                from langchain_core.messages import messages_from_dict
                return messages_from_dict(messages[-40:])
            return messages[-40:]
        except (OSError, ValueError, TypeError):
            return []

    def _save_memory(self):
        from langchain_core.messages import convert_to_messages, messages_to_dict

        temp = self.memory_path + ".tmp"
        serializable = messages_to_dict(convert_to_messages(self.messages[-40:]))
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({"thread_id": self.thread_id, "messages": serializable},
                      f, ensure_ascii=False)
        os.replace(temp, self.memory_path)
        audit_tool("persist_memory", details={"thread_id": self.thread_id,
                                               "message_count": len(self.messages)})

    def clear_memory(self):
        self.messages = []
        if os.path.exists(self.memory_path):
            os.remove(self.memory_path)
        audit_tool("clear_memory", details={"thread_id": self.thread_id})

    def ask(self, question):
        self.messages.append({"role": "user", "content": question})
        turn_messages = self.messages + [{"role": "system", "content": _response_language_instruction(question)}]
        result = self.agent.invoke({"messages": turn_messages})
        new_messages = result["messages"]
        if self.verbose:
            for m in new_messages[len(self.messages):]:
                calls = getattr(m, "tool_calls", None)
                if calls:
                    for c in calls:
                        print(f"  🔧 调用工具 {c['name']}({json.dumps(c['args'], ensure_ascii=False)})")
        self.messages = new_messages
        # Bound the local memory (keep system-side context small).
        if len(self.messages) > 40:
            self.messages = self.messages[-40:]
        self._save_memory()
        answer = self.messages[-1].content if self.messages else ""
        return answer

    def ask_stream(self, question):
        """Generator yielding ("tool", desc) events as the agent calls tools,
        then ("final", answer). Used by the WebUI chat page."""
        self.messages.append({"role": "user", "content": question})
        turn_messages = self.messages + [{"role": "system", "content": _response_language_instruction(question)}]
        final = None
        try:
            for chunk in self.agent.stream({"messages": turn_messages},
                                           stream_mode="updates"):
                for _node, payload in (chunk or {}).items():
                    for m in (payload or {}).get("messages", []) or []:
                        calls = getattr(m, "tool_calls", None)
                        if calls:
                            for c in calls:
                                args = json.dumps(c.get("args", {}), ensure_ascii=False)
                                yield ("tool", f"{c['name']}({args})")
                        elif getattr(m, "type", "") == "ai" and getattr(m, "content", None):
                            final = m.content
        except Exception as exc:
            yield ("final", f"Agent 执行出错: {exc}")
            self.messages.pop()
            return
        self.messages.append({"role": "assistant", "content": final or ""})
        if len(self.messages) > 40:
            self.messages = self.messages[-40:]
        self._save_memory()
        yield ("final", final or "(模型未给出回答)")
