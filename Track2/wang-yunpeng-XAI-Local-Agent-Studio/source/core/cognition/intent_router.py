"""痛点2：内置意图自动识别与自动分发路由。

解决"用户说一句话，系统要自动判断该交给哪个子引擎"的问题：
- 办公自动化（OpenClaw 网关）
- 长期业务值守（Orchestrator）
- 代码开发（Grok Build 引擎）
- 调研检索（知识库 KB）
- 通用兜底（Reason）

实现：关键词启发式打分（中英双语），归一化得到置信度，映射到引擎 key。
可选 `ModelBackend` 仅在低置信度时辅助消歧；StubBackend 下保持确定性、绝不联网。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class IntentType(Enum):
    OFFICE_AUTOMATION = "office_automation"
    LONG_TERM_BUSINESS = "long_term_business"
    CODE_DEV = "code_dev"
    RESEARCH = "research"
    GENERAL = "general"


@dataclass
class IntentResult:
    intent: IntentType
    confidence: float          # 归一化置信度 [0,1]
    routing: str               # 引擎 key 字符串
    rationale: str             # 简短中文说明


# 各意图关键词表（中英双语启发式）。命中即 +1 分。
KEYWORDS: dict[IntentType, list[str]] = {
    IntentType.CODE_DEV: [
        "代码", "重构", "git", "仓库", "refactor", "repository", "bug",
        "单测", "单元测试", "编译", "terminal", "函数", "class", "脚本", "debug",
    ],
    IntentType.OFFICE_AUTOMATION: [
        "文档", "表格", "浏览器", "桌面", "定时", "企业微信", "钉钉", "飞书",
        "批量处理", "docx", "excel", "ppt", "browser", "desktop", "schedule", "截图",
    ],
    IntentType.LONG_TERM_BUSINESS: [
        "长期", "值守", "监控", "周期", "复盘", "数字员工", "自动化业务",
        "recurring", "monitor", "日报", "巡检", "托管",
    ],
    IntentType.RESEARCH: [
        "调研", "研究", "检索", "知识库", "搜索", "总结", "RAG", "research",
        "search", "资料", "查一下", "汇总", "架构", "执行器", "能力", "是什么",
    ],
}

# 意图 -> 引擎 key 路由表
ROUTING: dict[IntentType, str] = {
    IntentType.OFFICE_AUTOMATION: "openclaw_gateway",
    IntentType.CODE_DEV: "grok_build_engine",
    IntentType.LONG_TERM_BUSINESS: "orchestrator",
    IntentType.RESEARCH: "kb",
    IntentType.GENERAL: "reason",
}


def _score_intents(task: str) -> dict[IntentType, int]:
    """对任务文本逐意图打分（关键词命中计数）。"""
    low = task.lower()
    scores: dict[IntentType, int] = {it: 0 for it in KEYWORDS}
    for intent, kws in KEYWORDS.items():
        for kw in kws:
            if kw.lower() in low:
                scores[intent] += 1
    return scores


class IntentRouter:
    """意图分类 + 自动分发路由器。"""

    def classify(self, task: str, backend=None) -> IntentResult:
        """分类任务意图并返回路由结果。

        - 关键词启发式打分，归一化出置信度。
        - 若提供 backend 且最高置信度 < 0.5，尝试用 backend 辅助消歧；
          但 StubBackend 下必须保持确定性、绝不联网、绝不抛错。
        """
        task = task or ""
        scores = _score_intents(task)

        best_intent = IntentType.GENERAL
        best_score = 0
        for intent, s in scores.items():
            if s > best_score:
                best_score = s
                best_intent = intent

        total = sum(scores.values())
        if total > 0:
            confidence = best_score / max(total, 1)
        else:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        # 低置信度：可选 backend 辅助消歧（StubBackend 下确定性、不抛错）
        if backend is not None and confidence < 0.5:
            try:
                hint = backend.complete(
                    f"仅输出一个词，判断任务类型(office_automation/long_term_business/"
                    f"code_dev/research/general): {task}"
                )
                for intent in KEYWORDS:
                    if intent.value.lower() in (hint or "").lower():
                        best_intent = intent
                        confidence = max(confidence, 0.5)
                        break
            except Exception:
                # 任何后端异常都不影响确定性兜底结果
                pass

        if best_score == 0:
            # 无关键词命中：兜底 GENERAL，置信度保持低但有效
            best_intent = IntentType.GENERAL
            confidence = max(confidence, 0.05)

        rationale = self._rationale(best_intent, scores.get(best_intent, 0))
        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            routing=ROUTING[best_intent],
            rationale=rationale,
        )

    @staticmethod
    def _rationale(intent: IntentType, hits: int) -> str:
        names = {
            IntentType.CODE_DEV: "代码开发",
            IntentType.OFFICE_AUTOMATION: "办公自动化",
            IntentType.LONG_TERM_BUSINESS: "长期业务值守",
            IntentType.RESEARCH: "调研检索",
            IntentType.GENERAL: "通用",
        }
        if hits > 0:
            return f"命中{names[intent]}相关关键词 {hits} 处，分发至 {ROUTING[intent]}"
        return f"未命中强特征，按通用兜底分发至 {ROUTING[intent]}"


def route_task(task: str, backend=None) -> IntentResult:
    """模块级便捷入口：直接对任务做意图路由。"""
    return IntentRouter().classify(task, backend)
