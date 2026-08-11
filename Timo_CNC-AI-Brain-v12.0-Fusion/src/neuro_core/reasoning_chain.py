"""
Industrial Explainable AI Reasoning Chain - XAI
================================================
For high-responsibility scenarios: failure analysis, QC, industrial decisions.
AI must show complete judgment basis, feature matching, reasoning chain.

Chain structure:
  1. Input parse - what params AI received
  2. Feature extraction - key features identified
  3. Rule matching - which rules/knowledge matched
  4. Reasoning process - each logical step
  5. Confidence assessment - evidence sufficiency score
  6. Final conclusion - judgment based on reasoning chain

Author: timo.cao | Union CNC AI Brain v11.1.0
"""
import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class StepType(str, Enum):
    INPUT_PARSE = "input_parse"
    FEATURE_EXTRACT = "feature_extract"
    RULE_MATCH = "rule_match"
    KNOWLEDGE_LOOKUP = "knowledge_lookup"
    CALCULATION = "calculation"
    INFERENCE = "inference"
    EXCLUSION = "exclusion"
    CONFIDENCE = "confidence"
    CONCLUSION = "conclusion"
    TOOL_CALL = "tool_call"
    WARNING = "warning"
    VETO = "veto"


@dataclass
class ReasoningStep:
    step_id: int
    step_type: StepType
    title: str
    description: str
    evidence: Optional[Dict] = None
    confidence: float = 0.0
    formula: Optional[str] = None
    source: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict = field(default_factory=dict)


@dataclass
class ReasoningChain:
    """
    Reasoning Chain - records AI's complete reasoning from input to conclusion.
    """
    task_type: str
    task_title: str
    steps: List[ReasoningStep] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    overall_confidence: float = 0.0
    overall_conclusion: str = ""
    warnings: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        self._step_counter = 0
        # 步骤耗时测量 (time.perf_counter，高精度单调时钟)
        # _step_anchor: 上一步骤结束(或链创建)时刻；_step_start: start_step() 显式开始的时刻
        self._step_anchor = time.perf_counter()
        self._step_start: Optional[float] = None

    def _next_id(self) -> int:
        self._step_counter += 1
        return self._step_counter

    def start_step(self) -> 'ReasoningChain':
        """显式开始一个步骤的计时（time.perf_counter）。"""
        self._step_start = time.perf_counter()
        return self

    def end_step(self) -> float:
        """结束当前步骤计时，返回真实耗时毫秒（非零）。

        若未调用 start_step()，则以上一步骤结束时刻为起点，
        即测量两步之间实际发生的计算耗时。
        """
        now = time.perf_counter()
        t0 = self._step_start if self._step_start is not None else self._step_anchor
        dur_ms = (now - t0) * 1000.0
        self._step_start = None
        self._step_anchor = now
        return round(max(dur_ms, 0.001), 3)

    def _append(self, step: ReasoningStep) -> 'ReasoningChain':
        """统一步骤追加入口：为每个步骤记录真实耗时 duration_ms。"""
        step.duration_ms = self.end_step()
        self.steps.append(step)
        return self

    def add_step(self, step_type: StepType, title: str, description: str,
                 evidence: Dict = None, confidence: float = 0.9,
                 source: str = None, formula: str = None) -> 'ReasoningChain':
        """通用步骤追加入口 — 供CAD参数提取等混合类型推理链使用。"""
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=step_type,
            title=title, description=description,
            evidence=evidence, confidence=confidence, source=source, formula=formula))
        return self

    def add_input(self, key: str, value: Any, source: str = "user") -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.INPUT_PARSE,
            title=f"Input: {key}",
            description=f"Parsed parameter {key}={value}",
            evidence={"key": key, "value": str(value)}, confidence=1.0, source=source))
        return self

    def add_feature(self, feature: str, value: Any, description: str = "") -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.FEATURE_EXTRACT,
            title=f"Feature: {feature}",
            description=description or f"Extracted feature {feature}={value}",
            evidence={"feature": feature, "value": str(value)}, confidence=0.9))
        return self

    def add_rule_match(self, rule_id: str, rule_desc: str, matched: bool,
                       severity: str = "info", conflict_msg: str = "",
                       all_rules_checked: int = 0) -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.RULE_MATCH,
            title=f"Rule {rule_id}: {'MATCHED' if matched else 'no match'}",
            description=conflict_msg if matched and conflict_msg else f"Rule {rule_id}: {rule_desc}",
            evidence={"rule_id": rule_id, "matched": matched, "severity": severity,
                      "conflict_msg": conflict_msg, "rules_checked": all_rules_checked},
            confidence=1.0 if matched else 0.0,
            source="hard_rule_db",
            formula=f"Rule #{rule_id}"))
        return self

    def add_knowledge(self, query: str, result_count: int, top_score: float,
                      description: str = "") -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.KNOWLEDGE_LOOKUP,
            title=f"Knowledge search: {query}",
            description=description or f"Found {result_count} matches, top score {top_score:.2f}",
            evidence={"query": query, "result_count": result_count, "top_score": top_score},
            confidence=min(top_score, 1.0), source="knowledge_base"))
        return self

    def add_calculation(self, name: str, formula: str, result: float,
                        unit: str = "", inputs: Dict = None) -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.CALCULATION,
            title=f"Calc: {name}",
            description=f"{formula} = {result}{unit}",
            evidence={"name": name, "formula": formula, "result": result,
                      "unit": unit, "inputs": inputs or {}},
            confidence=1.0, formula=formula))
        return self

    def add_inference(self, conclusion: str, reasoning: str,
                      confidence: float = 0.7, evidence: Dict = None) -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.INFERENCE,
            title=f"Inference: {conclusion}",
            description=reasoning, evidence=evidence, confidence=confidence))
        return self

    def add_exclusion(self, excluded: str, reason: str,
                      confidence: float = 0.8) -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.EXCLUSION,
            title=f"Excluded: {excluded}",
            description=reason,
            evidence={"excluded": excluded, "reason": reason}, confidence=confidence))
        return self

    def add_tool_call(self, tool_name: str, input_params: Dict,
                      output: Any, success: bool = True) -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.TOOL_CALL,
            title=f"Tool: {tool_name} ({'OK' if success else 'FAIL'})",
            description=f"Called {tool_name} with {json.dumps(input_params, ensure_ascii=False)[:200]}",
            evidence={"tool": tool_name, "input": input_params, "output": output, "success": success},
            confidence=1.0 if success else 0.0, source=f"tool:{tool_name}"))
        return self

    def add_conclusion(self, conclusion: str, confidence: float,
                       rationale: str = "", recommendations: List[str] = None) -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.CONCLUSION,
            title=f"Conclusion: {conclusion}",
            description=rationale,
            evidence={"conclusion": conclusion, "recommendations": recommendations or []},
            confidence=confidence))
        self.overall_confidence = confidence
        self.overall_conclusion = conclusion
        return self

    def add_warning(self, warning: str, severity: str = "warning") -> 'ReasoningChain':
        self.warnings.append(warning)
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.WARNING,
            title=f"Warning [{severity}]",
            description=warning,
            evidence={"severity": severity}, confidence=0.5))
        return self

    def add_veto(self, expert: str, reason: str, confidence: float) -> 'ReasoningChain':
        self._append(ReasoningStep(
            step_id=self._next_id(), step_type=StepType.VETO,
            title=f"VETO by {expert}",
            description=reason,
            evidence={"expert": expert, "reason": reason}, confidence=confidence))
        return self

    def finish(self) -> 'ReasoningChain':
        self.end_time = time.time()
        return self

    def to_dict(self) -> Dict[str, Any]:
        # 总耗时 = 各步骤 duration_ms 之和（perf_counter 高精度测量）；
        # 若无步骤则回退到 wall-clock 差值，保底 0.1ms，确保恒大于 0
        step_ms = sum(s.duration_ms for s in self.steps)
        if step_ms <= 0:
            step_ms = ((self.end_time or time.time()) - self.start_time) * 1000
        elapsed = round(max(step_ms, 0.1), 1)
        return {
            "task_type": self.task_type,
            "task_title": self.task_title,
            "total_steps": len(self.steps),
            "elapsed_ms": round(elapsed, 1),
            "overall_confidence": round(self.overall_confidence, 3),
            "overall_conclusion": self.overall_conclusion,
            "warnings": self.warnings,
            "steps": [asdict(s) for s in self.steps],
            "summary": self._build_summary(),
            "metadata": self.metadata,
        }

    def _build_summary(self) -> str:
        parts = []
        for s in self.steps:
            icon = {
                StepType.INPUT_PARSE: "[INPUT]",
                StepType.FEATURE_EXTRACT: "[FEATURE]",
                StepType.RULE_MATCH: "[RULE]",
                StepType.KNOWLEDGE_LOOKUP: "[KNOWLEDGE]",
                StepType.CALCULATION: "[CALC]",
                StepType.INFERENCE: "[INFER]",
                StepType.EXCLUSION: "[EXCLUDE]",
                StepType.CONCLUSION: "[CONCLUDE]",
                StepType.TOOL_CALL: "[TOOL]",
                StepType.WARNING: "[WARN]",
                StepType.VETO: "[VETO]",
            }.get(s.step_type, "[STEP]")
            parts.append(f"{s.step_id}. {icon} {s.title}: {s.description[:120]}")
        return "\n".join(parts)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def confidence_level(self) -> str:
        c = self.overall_confidence
        if c > 0.9: return "very_high"
        if c > 0.7: return "high"
        if c > 0.5: return "medium"
        if c > 0.3: return "low"
        return "very_low"


# Global registry for completed chains (in-memory, last 100)
_chain_registry: List[Dict] = []
_MAX_CHAINS = 100


def register_chain(chain: ReasoningChain) -> str:
    """Register a completed reasoning chain. Returns chain_id."""
    import hashlib
    chain_id = hashlib.md5(f"{chain.task_type}:{chain.start_time}".encode()).hexdigest()[:12]
    d = chain.finish().to_dict()
    d["chain_id"] = chain_id
    _chain_registry.append(d)
    if len(_chain_registry) > _MAX_CHAINS:
        _chain_registry.pop(0)
    return chain_id


def get_chain(chain_id: str) -> Optional[Dict]:
    """Retrieve a reasoning chain by ID."""
    for c in _chain_registry:
        if c.get("chain_id") == chain_id:
            return c
    return None


def get_recent_chains(limit: int = 10) -> List[Dict]:
    """Get recent reasoning chains."""
    return _chain_registry[-limit:]
