# -*- coding: utf-8 -*-
"""
test_agent.py — M4 端到端验证

1) pipeline：确定性流水线端到端（OCR→查验→RAG→决策），验证金额链路跑通
2) agent：LangChain tool-calling Agent 真实调用工具（RAG 查询药品）
3) memory：同一 session 多轮追问，验证记忆生效

运行：python test_agent.py
说明：pipeline 默认 do_verify=False（跳过外部查验接口，专注演示 RAG+决策链路）。
"""

import os

from agent.pipeline import process_invoice, format_result_text
from agent.agent import chat

IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fapiao2.jpg")


def test_pipeline():
    print("\n===== 1) 确定性流水线 =====")
    if not os.path.exists(IMG):
        print("[WARN] fapiao2.jpg 不存在，跳过")
        return
    result = process_invoice(IMG, do_verify=False, session_id="demo")
    if not result.get("ok"):
        print(f"[WARN] 流水线未跑通：{result.get('message')}")
        return
    print(format_result_text(result))
    d = result["decision"]
    print(f"\n[CHECK] conclusion={d.get('conclusion')} "
          f"total={d.get('total_amount')} reimbursable={d.get('total_reimbursable')} "
          f"items={len(d.get('items', []))}")


def test_agent_toolcall():
    print("\n===== 2) Agent 工具调用（药品目录查询）=====")
    ans = chat("阿莫西林胶囊属于医保哪一类？能报销吗？", session_id="s1")
    print("助手>", ans)


def test_agent_memory():
    print("\n===== 3) Agent 多轮记忆追问 =====")
    ans = chat("那它的统筹报销比例大概是多少？", session_id="s1")
    print("助手>", ans)


def main():
    test_pipeline()
    test_agent_toolcall()
    test_agent_memory()
    print("\n==== M4 端到端验证结束 ====")


if __name__ == "__main__":
    main()
