"""Explicit offline fake provider for deterministic operational checks."""

from __future__ import annotations

from ..knowledge.models import KnowledgeContext
from ..models import AnalysisResult, Event
from ..skill import SkillContext


class ReadinessFakeAnalysisProvider:
    """Return a synthetic result; never claim real model inference."""

    provider_id = "fake:readiness"
    prompt_version = "fake-readiness-v1"

    def analyze(self, event: Event) -> AnalysisResult:
        return self._result(event)

    def analyze_with_context(
        self,
        event: Event,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        if not isinstance(knowledge_context, KnowledgeContext):
            raise TypeError("knowledge_context must be KnowledgeContext")
        return self._result(event)

    def analyze_with_contexts(
        self,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        if not isinstance(skill_context, SkillContext):
            raise TypeError("skill_context must be SkillContext")
        if not isinstance(knowledge_context, KnowledgeContext):
            raise TypeError("knowledge_context must be KnowledgeContext")
        return self._result(event)

    def _result(self, event: Event) -> AnalysisResult:
        return AnalysisResult(
            detected_issue=(
                f"检测到事件 {event.event_type} 的合成就绪性结果"
            ),
            decision_type="synthetic_readiness_check",
            reasoning_summary=(
                "该合成输出仅用于验证 Provider 组合与分析防护；"
                "未进行设备诊断，也未执行任何 Runtime 操作。"
            ),
            evidence=["synthetic_provider=true"],
            model_or_rule=self.provider_id,
            confidence=0.8,
            requires_human_review=True,
            severity="LOW",
        )
