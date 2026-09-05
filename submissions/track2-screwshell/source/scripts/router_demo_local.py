"""本地可跑的 SkillRouter 演示 —— 不需要显卡、不需要真模型。

这是给"非工程背景"的你自己看的：文档里说的"场景路由 + 间接控制"，
到底在你问一句话时发生了什么。运行：

    python scripts/router_demo_local.py

它只调用 screwshell.core.router.SkillRouter（纯 Python 启发式路由），
把文档里那 4 类场景（聊天 / RAG长文档 / 代码 / Agent / 安全审计）
变成你能亲眼看到的"问题 -> 命中专家"映射。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from screwshell.core.router import SkillRouter, DEFAULT_SKILL_MAP

# 模拟真实用户会问的 8 句话（覆盖文档里所有场景）
DEMO_QUERIES = [
    ("帮我看看 bench_harness.py 为什么这么慢", None, "代码场景"),
    ("总结一下 ROCm 迁移计划文档里的主要风险", None, "RAG/长文档场景"),
    ("调查一下为什么 GPU 显存超预算了，分几步验证", None, "Agent 多步规划"),
    ("对这个登录接口做一次安全审计，有没有注入风险", None, "安全审计场景"),
    ("run 一个 grep 找一下 'float64' 在哪些文件", None, "工具调用场景"),
    ("你好，今天天气怎么样", None, "纯聊天（默认走 agent）"),
    ("审计这段代码的 CVE 和 XSS 漏洞", None, "安全（抢占代码）"),
    ("plan a multi-step investigation of the VRAM budget", "agent", "显式任务标签"),
]

EXPERT_DESC = {
    "btl3": "BTL-3 · 工具/代码执行专家",
    "teichai_plan": "TeichAI Fable-5 · 多步规划专家",
    "cybersec": "CyberSec · 安全审计专家",
    "rag_n7": "RAG-n7 · 文档/证据报告专家",
    None: "（无 LoRA = 纯基座 Qwen3.6-27B 原生思考）",
}


def main():
    r = SkillRouter()
    print("=" * 64)
    print("  ScrewShell · SkillRouter 场景路由演示（纯本地，无显卡）")
    print("=" * 64)
    print(f"  当前专家映射: {DEFAULT_SKILL_MAP}")
    print("-" * 64)
    for q, tag, label in DEMO_QUERIES:
        d = r.route(q, task_tag=tag)
        expert = d.adapter
        desc = EXPERT_DESC.get(expert, expert)
        taginfo = f" [显式标签={tag}]" if tag else ""
        print(f"\n[{label}]{taginfo}")
        print(f"  你问: {q}")
        print(f"  路由: skill={d.skill}  ->  激活专家 = {expert}")
        print(f"  说明: {desc}")
        print(f"  原因: {d.reason}")
    print("\n" + "=" * 64)
    print("  这就是文档里说的「场景路由 + 间接控制」：")
    print("  你只暴露'问题/技能'，系统内部把问题映射到具体 LoRA 专家。")
    print("=" * 64)


if __name__ == "__main__":
    main()
