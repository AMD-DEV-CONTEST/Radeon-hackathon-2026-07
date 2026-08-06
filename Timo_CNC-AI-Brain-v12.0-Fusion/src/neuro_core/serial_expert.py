"""
串行多专家会议引擎 v13 — 专家先调 Skill 拿硬数据，再推理。
单一 LLM 实例，顺序切换角色。
支持一票否决 + CEO 覆写 + Skill 工具调用。
所有通信为标准 JSON。
v13.1: 新增 Schema 校验器，不通过自动重试。
"""
import json
from typing import Dict, List, Optional, Any
from src.ai_engine.ollama_engine import OllamaEngine
from src.runtime.event_bus import EventBus
from src.runtime.skill_caller import SkillCaller
from src.neuro_core.schema_validator import SchemaValidator
from src.neuro_core.reasoning_chain import ReasoningChain, register_chain


class SerialExpertOrchestrator:
    """串行多专家会议引擎。v13: 集成 Skill 工具调用。"""

    # 每个专家可调用的 Skill
    EXPERT_TOOLS = {
        "cfo_analysis": ["quote_calculate"],        # CFO 可算精确报价
        "bi_analyst": ["history_lookup"],            # BI 可查历史数据
        "process_chief": ["conflict_check"],          # 工艺可检查冲突
        "strategist": [],                             # 战略官暂不需工具
        "ceo_decision": [],                           # CEO 只看汇总
    }

    def __init__(self, ai_engine: OllamaEngine, expert_registry: Dict[str, Dict],
                 event_bus: Optional[EventBus] = None,
                 skill_registry: Optional[SkillCaller] = None,
                 schema_validator: Optional[SchemaValidator] = None):
        self.ai = ai_engine
        self.experts = expert_registry
        self.bus = event_bus or EventBus()
        self.skills = skill_registry or SkillCaller()
        self.schema = schema_validator or SchemaValidator(expert_registry)
        self.transcript: List[Dict[str, Any]] = []

    def convene(self, topic: str, context: Dict[str, Any],
                expert_names: List[str],
                progress_cb=None) -> Dict[str, Any]:
        """
        召开专家会议。
        
        Args:
            topic: 议题
            context: 上下文数据（含报价详情、客户信息等）
            expert_names: 需要征询的专家名称列表
            progress_cb: (index, name) 进度回调
        
        Returns:
            标准 JSON dict: {decision, summary, transcript, tool_usage, ...}
        """
        self.transcript.clear()
        self._emit("start", message="专家会议开始...")

        analyses: Dict[str, Dict[str, Any]] = {}
        all_tool_results: Dict[str, Dict] = {}

        for idx, name in enumerate(expert_names):
            if name not in self.experts:
                continue

            if progress_cb:
                progress_cb(idx, name)

            expert_cfg = self.experts[name]
            self._emit("analyzing", expert=name, message=f"{name} 正在调用工具分析...")

            # v13: 先调 Skill 拿硬数据
            analysis = self._query_expert_with_tools(name, expert_cfg, topic, context, analyses)
            analyses[name] = analysis
            all_tool_results[name] = analysis.get("_tool_results", {})

            self.transcript.append({"expert": name, "analysis": analysis})
            self._emit("done", expert=name,
                       message=f"{name} 完成 (工具有效: {len(analysis.get('_tool_results', {}))})")

        # 一票否决检查
        veto = self._check_veto(analyses, expert_names)
        if veto:
            veto["tool_usage"] = all_tool_results
            self._emit("vetoed", message=f"被否决: {veto['veto_by']}")
            return veto

        # CEO 最终裁决
        self._emit("ceo", message="CEO 正在做最终裁决...")
        final = self._ceo_summarize(topic, analyses, context)
        final["tool_usage"] = all_tool_results
        self._emit("complete", message="会议决策完成")
        return final

    def convene_with_reasoning(self, topic: str, context: Dict[str, Any],
                                expert_names: List[str],
                                progress_cb=None) -> Dict[str, Any]:
        """
        Expert meeting WITH full reasoning chain (XAI).
        Records each expert's analysis, tool calls, and decision process.
        """
        chain = ReasoningChain("expert_panel", f"Expert Panel: {topic[:60]}")
        chain.add_input("topic", topic)
        chain.add_input("expert_count", len(expert_names))
        chain.add_input("experts", ", ".join(expert_names))

        self.transcript.clear()
        self._emit("start", message="专家会议开始...")

        analyses: Dict[str, Dict[str, Any]] = {}
        all_tool_results: Dict[str, Dict] = {}

        for idx, name in enumerate(expert_names):
            if name not in self.experts:
                chain.add_warning(f"Expert '{name}' not found in registry")
                continue

            if progress_cb:
                progress_cb(idx, name)

            expert_cfg = self.experts[name]
            chain.add_inference(
                f"Expert {name} analyzing",
                f"Role: {expert_cfg.get('system_prompt', '')[:100]}...",
                confidence=0.8,
                evidence={"expert": name, "has_veto": expert_cfg.get("has_veto", False)}
            )

            self._emit("analyzing", expert=name, message=f"{name} 正在调用工具分析...")
            analysis = self._query_expert_with_tools(name, expert_cfg, topic, context, analyses)
            analyses[name] = analysis
            all_tool_results[name] = analysis.get("_tool_results", {})

            # Record tool calls in reasoning chain
            for tool_name, tool_result in analysis.get("_tool_results", {}).items():
                chain.add_tool_call(tool_name, context, tool_result, 
                                   success=tool_result.get("success", True))

            # Record expert's recommendation
            rec = analysis.get("recommendation", "abstain")
            conf = analysis.get("confidence", 0.5)
            reasoning = analysis.get("analysis", "")[:300]
            chain.add_inference(
                f"{name} recommends: {rec}",
                reasoning,
                confidence=conf,
                evidence={"recommendation": rec, "confidence": conf, "analysis": reasoning}
            )

            self.transcript.append({"expert": name, "analysis": analysis})
            self._emit("done", expert=name,
                       message=f"{name} 完成 (工具有效: {len(analysis.get('_tool_results', {}))})")

        # Veto check with reasoning
        veto = self._check_veto(analyses, expert_names)
        if veto:
            chain.add_veto(veto["veto_by"], veto.get("reason", ""), 0.9)
            veto["tool_usage"] = all_tool_results
            chain.add_conclusion(f"VETOED by {veto['veto_by']}", 0.99,
                               rationale=veto.get("reason", ""))
            self._emit("vetoed", message=f"被否决: {veto['veto_by']}")
            veto["reasoning_chain"] = chain.finish().to_dict()
            veto["reasoning_chain_id"] = register_chain(chain)
            return veto

        # CEO summary with reasoning
        self._emit("ceo", message="CEO 正在做最终裁决...")
        chain.add_inference("CEO synthesizing", "Combining all expert opinions for final decision", 0.9)
        final = self._ceo_summarize(topic, analyses, context)
        final["tool_usage"] = all_tool_results

        decision = final.get("decision", "DEFERRED")
        chain.add_conclusion(
            f"Final decision: {decision}",
            confidence=final.get("confidence", 0.7),
            rationale=final.get("rationale", "")[:500],
            recommendations=[final.get("summary", "")]
        )

        self._emit("complete", message="会议决策完成")
        final["reasoning_chain"] = chain.finish().to_dict()
        final["reasoning_chain_id"] = register_chain(chain)
        return final

    def _query_expert_with_tools(self, name: str, cfg: Dict, topic: str,
                                  context: Dict, prior: Dict) -> Dict[str, Any]:
        """
        v13 核心：专家先调用已注册的 Skill 获取硬数据，再基于硬数据推理。
        """
        tools = self.EXPERT_TOOLS.get(name, [])
        tool_results: Dict[str, Any] = {}

        # Step 1: 调用该专家可用的所有 Skill
        for tool_name in tools:
            if tool_name in self.skills._registry:
                try:
                    self._emit("tool_call", expert=name,
                               message=f"{name} 调用 Skill: {tool_name}")
                    result = self.skills.call(tool_name, context)
                    tool_results[tool_name] = result
                except Exception as e:
                    tool_results[tool_name] = {"success": False, "error": str(e)}

        # Step 2: 构建 prompt，注入硬数据
        tool_text = self._format_tool_results(tool_results)
        prior_text = self._format_prior(prior)
        schema = json.dumps(cfg.get("schema", {}), ensure_ascii=False)
        ctx_json = json.dumps(context, ensure_ascii=False)[:2000]

        prompt = f"""【议题】{topic}

【可用数据】
{ctx_json}

【系统工具返回的硬数据（注意：这是真实数据，优先采信）】
{tool_text}

【前序专家意见】
{prior_text or '（你是第一位发言专家）'}

【任务】
请以 {name} 的身份严格分析以上信息。
重要提示：
1. 如果你的分析能用"系统工具返回的硬数据"来支撑，就不要凭空猜测
2. 如果工具返回了具体数据（如精确报价），直接引用，不要自已估算
3. 严格按照 JSON Schema 输出（只输出 JSON，不要其他文字）

JSON Schema:
{schema}"""

        raw = self.ai.chat(prompt, system_prompt=cfg.get("system_prompt", ""), temperature=0.3)

        # JSON 解析
        try:
            analysis = json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[\s\S]*\}', raw)
            try:
                analysis = json.loads(match.group(0)) if match else {}
            except (json.JSONDecodeError, AttributeError):
                analysis = {"analysis": raw.strip()[:500], "recommendation": "abstain", "confidence": 0.0}

        # Schema 校验 — 不通过则重试一次
        vr = self.schema.validate(name, json.dumps(analysis, ensure_ascii=False) if isinstance(analysis, dict) else raw)
        if not vr["valid"]:
            self._emit("warn", expert=name,
                       message=f"{name} Schema校验失败: {vr.get('error','')}, 重试...")
            # 重试：追加校验错误到 prompt
            retry_prompt = prompt + f"\n\n【纠错指令】上次输出未通过JSON Schema校验，错误: {vr.get('error', '')}。请严格按Schema输出。"
            raw2 = self.ai.chat(retry_prompt, system_prompt=cfg.get("system_prompt", ""), temperature=0.2)
            try:
                analysis = json.loads(raw2)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\{[\s\S]*\}', raw2)
                try:
                    analysis = json.loads(match.group(0)) if match else {}
                except (json.JSONDecodeError, AttributeError):
                    analysis = {"analysis": raw2.strip()[:500], "recommendation": "abstain", "confidence": 0.0}
            vr2 = self.schema.validate(name, json.dumps(analysis, ensure_ascii=False) if isinstance(analysis, dict) else raw2)
            analysis["_schema_valid"] = vr2["valid"]

        analysis.setdefault("analysis", "")
        analysis.setdefault("recommendation", "abstain")
        analysis.setdefault("confidence", 0.5)
        analysis["_tool_results"] = tool_results  # 附带工具结果用于审计
        analysis["_tools_used"] = tools
        return analysis

    def _format_tool_results(self, results: Dict[str, Any]) -> str:
        """格式化工具返回结果为可读文本，注入 prompt。"""
        if not results:
            return "（无工具结果）"

        lines = []
        for skill_name, data in results.items():
            if not data.get("success"):
                lines.append(f"🔧 {skill_name}: 调用失败 — {data.get('error', '未知错误')}")
                continue

            result = data.get("result", {})
            # 根据不同 Skill 类型截取关键信息
            if skill_name == "quote_calculate":
                lines.append(f"🔧 {skill_name}: 精确报价 — ¥{result.get('final_price', 0):.2f}")
                lines.append(f"   单价: ¥{result.get('unit_price', 0):.2f} | "
                           f"数量: {result.get('quantity', 0)} | "
                           f"利润: ¥{result.get('profit', 0):.2f}")
                lines.append(f"   材料: {result.get('material', 'N/A')} | "
                           f"表面: {result.get('surface', 'N/A')} | "
                           f"引擎: {result.get('engine', 'N/A')}")
                if result.get("warnings"):
                    for w in result["warnings"]:
                        lines.append(f"   ⚠️ {w}")

            elif skill_name == "conflict_check":
                if not result.get("valid"):
                    lines.append(f"🔧 {skill_name}: ❌ 发现 {result.get('total_issues', 0)} 个冲突")
                    for c in result.get("conflicts", []):
                        lines.append(f"   ❌ [{c.get('severity')}] {c.get('message')}")
                    for w in result.get("warnings", []):
                        lines.append(f"   ⚠️ [{w.get('severity')}] {w.get('message')}")
                else:
                    lines.append(f"🔧 {skill_name}: ✅ 无工艺冲突")

            elif skill_name == "history_lookup":
                lines.append(f"🔧 {skill_name}: 查询到 {result.get('total', 0)} 条历史记录")
                if result.get("stats"):
                    s = result["stats"]
                    lines.append(f"   均价: ¥{s.get('avg_price', 0):.2f} | "
                               f"区间: ¥{s.get('min_price', 0)} ~ ¥{s.get('max_price', 0)} | "
                               f"订单数: {s.get('total_orders', 0)}")
                if result.get("records"):
                    for r in result["records"][:3]:
                        lines.append(f"   📋 {r.get('order_id')}: {r.get('part_name')} "
                                   f"¥{r.get('final_price', 0)} | {r.get('customer_name')}")

        return "\n".join(lines) if lines else "（无有效工具结果）"

    @staticmethod
    def _format_prior(prior: Dict) -> str:
        if not prior:
            return ""
        items = []
        for e, a in prior.items():
            items.append(
                f"[{e}] 建议: {a.get('recommendation', 'N/A')} | "
                f"置信度: {a.get('confidence', 0)} | "
                f"分析: {a.get('analysis', 'N/A')[:200]}"
            )
        return "\n".join(items)

    def _ceo_summarize(self, topic: str, analyses: Dict,
                       context: Dict) -> Dict[str, Any]:
        """CEO 综合所有专家意见做最终裁决。"""
        ceo_cfg = self.experts.get("ceo_decision", {})
        if not ceo_cfg:
            return {"decision": "DEFERRED", "summary": "CEO 配置缺失"}

        opinions = json.dumps(analyses, ensure_ascii=False)[:3000]
        schema = json.dumps(ceo_cfg.get("schema", {}), ensure_ascii=False)

        prompt = f"""【议题】{topic}

【各专家意见（基于硬数据分析）】
{opinions}

【任务】
你是CEO。请综合以上所有专家的意见，做出最终裁决。
注意：专家意见中包含了系统工具返回的硬数据（如精确报价、工艺冲突等），请优先采信这些硬数据。
严格按照以下 JSON Schema 输出（只输出 JSON）:

{schema}"""

        result = self.ai.chat_json(prompt, system_prompt=ceo_cfg.get("system_prompt", ""),
                                   temperature=0.2)

        if result is None or "_error" in result:
            return {"decision": "DEFERRED", "rationale": "CEO 裁决解析失败", "summary": "决策异常"}

        result.setdefault("decision", "DEFERRED")
        result.setdefault("rationale", "未提供理由")
        result["summary"] = f"最终决策: {result.get('decision')} — {result.get('rationale', '')[:200]}"
        result["transcript"] = [
            {"expert": t["expert"],
             "recommendation": t["analysis"].get("recommendation"),
             "confidence": t["analysis"].get("confidence")}
            for t in self.transcript
        ]
        return result

    def _check_veto(self, analyses: Dict, expert_names: List[str]) -> Optional[Dict]:
        """检查是否有专家行使一票否决权。"""
        for name in expert_names:
            cfg = self.experts.get(name, {})
            if not cfg.get("has_veto"):
                continue
            opinion = analyses.get(name, {})
            if opinion.get("recommendation") == "reject" and opinion.get("confidence", 0) > 0.7:
                return {
                    "decision": "REJECTED",
                    "veto_by": name,
                    "reason": opinion.get("analysis", "未提供理由")[:500],
                    "override_available": True,
                    "summary": f"⚠️ {name} 行使一票否决: {opinion.get('analysis', '')[:200]}",
                    "transcript": [
                        {"expert": t["expert"],
                         "recommendation": t["analysis"].get("recommendation"),
                         "confidence": t["analysis"].get("confidence")}
                        for t in self.transcript
                    ],
                }
        return None

    def _emit(self, phase: str, expert: str = None, message: str = ""):
        self.bus.publish("hmi.meeting_progress", {
            "phase": phase,
            "expert": expert,
            "message": message,
        })

    def get_transcript_json(self) -> str:
        return json.dumps(self.transcript, ensure_ascii=False, indent=2)
