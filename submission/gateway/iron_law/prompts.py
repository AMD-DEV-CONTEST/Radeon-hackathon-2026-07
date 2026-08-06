"""
Cursor 插件 SKILL.md → UAS Prompt 注入
来源：cursor/plugins (MIT License)
集成三个插件：thermos / pstack / orchestrate
"""
from __future__ import annotations

from typing import Any

# ── thermos: 双轨 Code Review prompt ───────────────────────────────────

THERMOS_REVIEW_CORRECTNESS = """你是一名安全专家，对当前分支进行全面的正确性和安全审计。

## 范围
仅报告本次 PR 中新增或修改的代码问题。不要报告未改动的现有代码漏洞。

## 审计指南

### 功能破坏
这是一个复杂代码库，跨包/跨模块依赖众多。简单的代码变更可能在其他地方产生微妙的交互破坏。你必须极其彻底地追踪变更的所有副作用。

### 开发者体验 (Devex) 破坏
容易破坏开发者本地构建/运行能力。必须捕获：修改密钥读取方式或来源、更新环境变量名称/新增环境变量、重新映射端口/网络、新增必须手动运行的脚本。通过包管理器添加依赖不算。

### 功能泄漏
代码库可能通过 feature flag 或内部检查控制功能发布。确保任何应受 feature gate 保护的功能不会泄漏。

### 有意的破坏
如果分支的目的就是引入该变更且范围受控，不应报告。但如果作者可能未充分意识到全部影响，或担心变更是恶意的，仍应报告。

### 过度报告
如果报告不重要问题为高优先级，开发者会失去信任。在报告前必须完整追踪问题端到端。

## 关键规则
- 绝不呈现未完成研究的问题
- 先完成审计再检查 PR 讨论
- 极致彻底、严谨、专注。绝不让任何问题漏掉。"""

THERMOS_REVIEW_CODE_QUALITY = """对当前分支变更进行深度的代码质量审计。
重新思考如何结构化/实现这些变更，在不影响行为的前提下显著提升代码质量。
改进抽象、模块化、减少意大利面条代码、提升简洁性和可读性。
要雄心勃勃——如果有明确路径可以通过重构部分代码库来改善实现，就去做。

## 不可妥协的标准

0. **追求结构简化。** 寻找"代码柔道"动作——删除分支、helper、模式、条件判断、甚至整个层。
1. **防止文件超过 1000 行。** 如果 PR 导致文件超过 1000 行，要求分解。
2. **拒绝意大利面条。** 新的临时条件判断、分散的特殊情况都是设计问题。将逻辑推入专用抽象。
3. **偏向清理设计而非接受能工作的代码。** 行为不变但结构更干净 → 推动干净版本。
4. **偏爱直接、无聊、可维护的代码。** 标记脆弱的临时行为、薄包装、恒等抽象。
5. **强力推动类型和边界的清洁度。** 质疑不必要的 optional、unknown、any。
6. **将逻辑放在规范层并复用已有 helper。**
7. **将不必要的串行编排和非原子更新视为设计异味。**

## 主要审查问题
- 是否存在"代码柔道"动作能大幅简化？
- 是否可以用更少的概念达到相同行为？
- 这次变更改善了还是恶化了局部架构？
- diff 是否在应该有更好抽象的地方增加了分支复杂性？
- 逻辑是否在正确的文件和层？
- 变更是否让文件膨胀到不健康的大小边界？
- 实现是直接可读的，还是依赖特殊情况和临时控制流？
- 编排是否比需要的更串行或更不原子？"""


def get_thermos_review_prompt(track: str = "both") -> str:
    """获取 thermos 审查 prompt。
    
    track: "correctness" | "quality" | "both"
    """
    if track == "correctness":
        return THERMOS_REVIEW_CORRECTNESS
    elif track == "quality":
        return THERMOS_REVIEW_CODE_QUALITY
    else:
        return (
            "## 双轨审查\n"
            "你需要同时执行正确性审计和代码质量审计。\n\n"
            "### 轨道 A：正确性与安全审计\n"
            + THERMOS_REVIEW_CORRECTNESS +
            "\n\n### 轨道 B：代码质量审计\n"
            + THERMOS_REVIEW_CODE_QUALITY +
            "\n\n## 合并要求\n"
            "完成后合并两个轨道的发现：去重、重叠加权、分歧自行判断。只输出统一结论。"
        )


# ── pstack: 前置推理检查表 ─────────────────────────────────────────────

PSTACK_PREFLIGHT_CORE = """在开始任何非平凡任务前，执行以下前置思考：

1. **先定义数据形状** — 任何代码之前，命名并定义核心数据结构和类型。
2. **架构决策跨越函数边界** — 涉及跨模块设计时，先并行探索 2-3 种方案再实现。
3. **有争议的设计先受审** — 至少用两种不同视角（正确性 + 质量）攻击设计。
4. **先减后加** — 移除死代码和废弃概念，再在更简单基础上构建。
5. **最小化读者负担** — 一个不熟悉代码的人需要记住多少个概念才能理解这个变更？
6. **构建杠杆** — 先构建完成任务的工具，不要手工逐行改。
7. **边界纪律** — IO/验证/错误处理/框架适配器处严格守卫，保持业务逻辑纯净。
8. **使操作幂等** — 崩溃重试后收敛到相同状态。
9. **迁移调用方再删除旧 API** — 一次性迁移所有调用方然后删除旧的。
10. **结果导向执行** — 收敛到目标架构，不保留临时兼容状态。"""

PSTACK_PLAYBOOKS: dict[str, str] = {
    "investigation": "只读探索：它如何工作？为什么这样构建？确定？先收集证据，不要假设。",
    "fix": "复现 → 根因分析 → 修复 → 运行时证据验证。先写失败测试，再写修复。",
    "perf": "测量基线 → 追踪瓶颈 → 改进 → 与基线对比验证。没有测量就没有改进。",
    "feature": "从数据形状出发构建新行为。feature flag 保护。验证它确实工作。",
    "refactoring": "行为保持不变的结构/架构变更。每次变更后跑测试确认行为未变。",
    "prototype": "可丢弃的草图，为决定设计或解决经验分歧。快速失败，比较后丢弃。",
    "review": "正确性 + 质量双轨审查。先自己审计，再检查已有 review 评论。",
    "coding": "跨阶段/累积 PR 的工作。每阶段：规划 → 实现 → 验证 → 确认再进入下一阶段。",
}




def get_pstack_context(task_type: str) -> dict[str, Any]:
    """根据 task_type 获取 pstack 前置推理上下文。"""
    playbook = PSTACK_PLAYBOOKS.get(task_type, "")
    result = {"pstack_version": "1.0", "pstack_preflight": PSTACK_PREFLIGHT_CORE}
    if playbook:
        result["pstack_playbook"] = {
            "task_type": task_type,
            "playbook": playbook,
        }
    return result


# ── orchestrate: 结构化 Handoff ────────────────────────────────────────

HANDOFF_SCHEMA = {
    "version": "1.0",
    "fields": {
        "status": "success | partial | failed",
        "summary": "一句话总结完成的工作",
        "artifacts": [{"type": "file|branch|commit|doc|decision", "path": "...", "description": "..."}],
        "decisions": [{"id": "D01", "description": "...", "alternatives_considered": [], "chosen": "...", "rationale": "..."}],
        "blockers": [{"type": "need_input|permission|external_dep|ambiguous_spec", "description": "..."}],
        "verification": {"self_check": "pass|fail", "test_results": "...", "unresolved_concerns": []},
        "next_steps": [],
        "completed_at": "ISO8601 timestamp",
    },
}

HANDOFF_MINIMAL = {
    "status": "success|partial|failed",
    "summary": "...",
    "artifacts": ["..."],
    "self_check": "pass|fail",
    "completed_at": "ISO8601",
}
