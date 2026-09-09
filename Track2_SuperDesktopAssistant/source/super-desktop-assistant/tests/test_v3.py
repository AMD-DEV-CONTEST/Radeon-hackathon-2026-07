"""v3 统一架构特性测试 —— 覆盖 P0/P0b/P1/P2/P3/P5/P6b 阶段新特性。

不依赖真实网络，使用 mock。
"""
import os
import sys
import asyncio
from unittest.mock import patch

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（tests 上一级）
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

# Phase B：快照 ai-coin state，测试结束后还原（P6b 配置测试会经 set_assignment 写 state）
from pathlib import Path as _P
_AICOIN_STATE_PATH = _P(_ROOT_DIR) / "data" / "ai_coin_state.json"
_AICOIN_STATE_SNAP = (_AICOIN_STATE_PATH.read_text(encoding="utf-8")
                      if _AICOIN_STATE_PATH.exists() else None)

errors = 0


def check(name, cond):
    global errors
    if cond:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}")
        errors += 1


# ═══════════════════════════════════════
# 1. P0: 工作目录配置 + 沙箱读写区分
# ═══════════════════════════════════════
print("=== 1. P0 沙箱 ===")
from src.config import get_config
from src.agents import tools as T

cfg = get_config()
check("workspace_dir 默认 outputs", cfg.settings.workspace_dir == "outputs")
check("api_preference 默认 cloud_default", cfg.settings.api_preference == "cloud_default")

T._refresh_allowed_paths()
ws = T._ALLOWED_PATHS[0]
root = T._READONLY_PATHS[0]

tmp_ok = os.path.join(ws, "_v3_p0_test.txt")
r = T._tool_write_file({"path": tmp_ok, "content": "hi"})
check("写工作目录内成功", "已写入" in r)
if os.path.exists(tmp_ok):
    os.remove(tmp_ok)

r2 = T._tool_write_file({"path": os.path.join(root, "_v3_should_fail.txt"), "content": "x"})
check("写项目根被拒", ("拒绝访问" in r2) or ("安全限制" in r2))

r3 = T._tool_read_file({"path": os.path.join(root, "requirements.txt"), "start_line": 1, "line_count": 1})
check("读项目根允许", "文件" in r3)

# ═══════════════════════════════════════
# 2. P0b: 子能力路由 + enabled + local_first
# ═══════════════════════════════════════
print("\n=== 2. P0b 多 API 路由 ===")
r_reason = cfg.resolve("llm_reasoning")
check("resolve(llm_reasoning) 有值", r_reason is not None)
r_creat = cfg.resolve("llm_creative")
check("resolve(llm_creative) 有值", r_creat is not None)
r_summ = cfg.resolve("llm_summary")
check("resolve(llm_summary)=mimo", r_summ is not None and r_summ[0].name == "mimo")
check("zhipu 被禁用", cfg.get_provider("zhipu").enabled is False)

cands = cfg.resolve_candidates("llm")
check("候选不含 zhipu", all(p.name != "zhipu" for p, _ in cands))

# local_first 排序
cfg._settings.api_preference = "local_first"
cands_local = cfg.resolve_candidates("llm")
check("local_first 本地优先", cands_local[0][0].is_local)
cfg._settings.api_preference = "cloud_default"

# ═══════════════════════════════════════
# 3. P1: LLMForeman 工具链
# ═══════════════════════════════════════
print("\n=== 3. P1 工头工具链 ===")
from src.layer3.llm_foreman import LLMForeman
from src.layer3.base_foreman import Workspace

fm = LLMForeman()
check("路由 reasoning→llm_reasoning", fm._route_model("reasoning") == "llm_reasoning")
check("路由 creative→llm_creative", fm._route_model("creative") == "llm_creative")
check("路由 summary→llm_summary", fm._route_model("summary") == "llm_summary")
check("pick(llm_reasoning)=mimo", asyncio.run(fm._pick_provider("llm_reasoning"))[0] == "mimo")

LONG = "x" * 60


async def _t_tool():
    fm2 = LLMForeman()
    task = {"task_id": "t1", "task_type": "text", "user_input": "写一个 hello.py"}
    ws = Workspace(task_id="t1", task_type="text")
    captured = {}

    def fake_ct(**kw):
        captured["kw"] = kw
        return LONG

    with patch("src.layer3.llm_foreman.chat_with_tools", side_effect=fake_ct):
        await fm2._execute_impl(task, ws)
    k = captured["kw"]
    return ("tools" in k and len(k["tools"]) == 8
            and k.get("provider") == ws.api_provider
            and "write_file" in k["messages"][0]["content"])


check("chat_with_tools 带8工具+锁定API", asyncio.run(_t_tool()))

# ═══════════════════════════════════════
# 4. P2/P3: v3 process 统一入口（mock 规划+工头）
# ═══════════════════════════════════════
print("\n=== 4. P2/P3 v3 process ===")
DAG_JSON = ('{"task_id":"t","description":"生成游戏",'
            '"nodes":[{"id":"llm_1","type":"llm","prompt":"写HTML","depends_on":[]}],'
            '"user_inputs":{"images":"never","audio":"never"}}')


async def _t_process():
    from src.main import AssistantEngine
    eng = AssistantEngine()

    async def fake_plan(user_message, **kw):
        return DAG_JSON

    async def fake_route(task, user_message):
        return {"status": "success", "data": "E:/out/game.html"}

    with patch("src.agents.planner.plan", side_effect=fake_plan), \
         patch("src.layer2.supervisor.Supervisor._route_to_foreman", side_effect=fake_route):
        r = await eng.process("帮我做一个html小游戏，实现人机对战五子棋")
    return (r.get("version") == "3.0"
            and r["dag"]["description"] == "生成游戏"
            and "llm_1" in r["results"]
            and "outputs" in r
            and r.get("status") == "ok")


check("process v3 完整链路", asyncio.run(_t_process()))

# 规则拆分兜底
async def _t_fallback():
    from src.main import AssistantEngine
    eng = AssistantEngine()

    async def fake_plan(user_message, **kw):
        raise RuntimeError("LLM 不可用")

    async def fake_route(task, user_message):
        return {"status": "success", "data": "OK"}

    with patch("src.agents.planner.plan", side_effect=fake_plan), \
         patch("src.layer2.supervisor.Supervisor._route_to_foreman", side_effect=fake_route):
        r = await eng.process("画一只猫")
    return r["dag"]["description"] == "规则拆分" and len(r["results"]) >= 1


check("LLM 规划失败回退规则拆分", asyncio.run(_t_fallback()))

# ═══════════════════════════════════════
# 5. P6b: 配置指令
# ═══════════════════════════════════════
print("\n=== 5. P6b 配置指令 ===")
from src.layer1.user_agent import ConfigIntentHandler, UserAgent

h = ConfigIntentHandler()
check("普通消息不拦截", h.handle("写一首诗") is None)

with patch("src.config.ConfigManager.save_to_file"), patch("src.config.reload_config"):
    r = h.handle("把 LLM 换成 deepseek")
check("切换LLM→deepseek", r is not None and r["handled"] and "deepseek" in r["reply"])

with patch("src.config.ConfigManager.save_to_file"), patch("src.config.reload_config"):
    r = h.handle("temperature 调到 0.7")
check("调 temperature", r is not None and r["handled"])

with patch("src.config.ConfigManager.save_to_file"), patch("src.config.reload_config"):
    r = h.handle("禁用 zhipu 这个 API")
check("禁用 zhipu", r is not None and r["handled"] and "禁用" in r["reply"])

with patch("src.config.ConfigManager.save_to_file"), patch("src.config.reload_config"):
    ua = UserAgent()
    l1 = ua.process("把 LLM 换成 openai")
check("UserAgent 配置拦截", l1.get("config_handled") is True and "reply" in l1)

# ═══════════════════════════════════════
# 6. P5: 记忆统一
# ═══════════════════════════════════════
print("\n=== 6. P5 记忆统一 ===")
from src.memory import get_shared_memory as g_mem, reset_shared_memory as r_mem
from src.memory import SharedMemory as SMem
from src.agents.shared_memory import get_shared_memory as g_mem_old, SharedMemory as SMemOld

check("新旧接口同一对象", g_mem is g_mem_old)
check("SharedMemory 别名", SMem is SMemOld)

m = r_mem()
m.init_task("t1", "任务", "输入")
m.register_agent("node1", "llm")
view = g_mem().get_agent_view("node1")
check("任务记忆读写", view["task_description"] == "任务")

# 还原 ai-coin state（P6b 配置测试污染还原）
if _AICOIN_STATE_SNAP is not None:
    try:
        _AICOIN_STATE_PATH.write_text(_AICOIN_STATE_SNAP, encoding="utf-8")
    except Exception as e:
        print(f"  WARN: 还原 ai-coin state 失败: {e}")

# 汇总
print(f"\n{'=' * 40}")
if errors == 0:
    print("  ALL V3 TESTS PASSED!")
else:
    print(f"  {errors} TESTS FAILED!")
print(f"{'=' * 40}")
# BUG11 修复：加 __main__ 保护，避免 import 时 sys.exit 终止解释器
if __name__ == "__main__":
    sys.exit(errors)
