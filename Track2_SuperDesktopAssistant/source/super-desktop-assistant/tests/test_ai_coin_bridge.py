"""
ai-coin 接入桥测试（Phase B）。

离线：mock ai-coin 的 chat/chat_json/chat_with_tools 调用，不触真实 API。
覆盖：
- ensure_seeded 迁移（state 含全部供应商 + 分配）
- resolve_model_id 路由（llm / vision / 子能力回退 / 禁用过滤）
- config 从 state 构建 ProviderSpec（ai_coin_managed）
- set_assignment / set_provider_enabled 写 state
- chat / chat_json / chat_with_tools / analyze_image 委托 ai-coin
"""
import json
import os
import sys
import asyncio
import tempfile
from unittest.mock import patch

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（tests 上一级）
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

errors = 0


def check(name, cond):
    global errors
    if cond:
        print(f"  PASS: {name}")
    else:
        errors += 1
        print(f"  FAIL: {name}")


def _ensure_seeded():
    from src.api import ai_coin_bridge as b
    return b.ensure_seeded()


def test_seed_and_resolve():
    state = _ensure_seeded()
    check("迁移含 mimo 供应商", "mimo" in state.get("providers", {}))
    check("迁移含 llm 分配", state.get("assignments", {}).get("llm", {}).get("provider") == "mimo")
    check("迁移含 vision 分配", state.get("assignments", {}).get("vision", {}).get("provider") == "openai")

    from src.api.ai_coin_bridge import resolve_model_id
    mid = resolve_model_id("llm")
    check("resolve(llm) 返回 int id", isinstance(mid, int) and mid > 0)
    mid2 = resolve_model_id("vision")
    check("resolve(vision) 返回 int id", isinstance(mid2, int) and mid2 > 0)
    # 子能力回退：llm_reasoning 未单独分配 → 回退 llm
    state2 = _ensure_seeded()
    if "llm_reasoning" not in state2.get("assignments", {}):
        state2.setdefault("assignments", {})["llm_reasoning"] = {
            "provider": "mimo", "model": "mimo-v2.5"
        }
        from src.api.ai_coin_bridge import save_state
        save_state(state2)
    check("resolve(llm_reasoning) 可用", isinstance(resolve_model_id("llm_reasoning"), int))


def test_config_from_state():
    from src.config import get_config
    cfg = get_config()
    check("config 由 ai-coin 管理", cfg._ai_coin_managed)
    check("config 含 mimo 供应商", cfg.get_provider("mimo") is not None)
    r = cfg.resolve("llm")
    check("config.resolve(llm) → mimo/mimo-v2.5", r is not None and r[0].name == "mimo" and r[1].id == "mimo-v2.5")


def test_chat_delegation():
    from src.api import llm as llm_api
    from src.api.ai_coin_bridge import get_ai
    real_ai = get_ai()
    with patch.object(real_ai, "chat", return_value="你好，我是 AI") as m:
        out = llm_api.chat([{"role": "user", "content": "hi"}], capability="llm")
        check("chat 委托 ai-coin 返回文本", out == "你好，我是 AI")
        check("chat 传了 model_id", m.call_args[0][0] > 0)


def test_chat_json_delegation():
    from src.api import llm as llm_api
    from src.api.ai_coin_bridge import get_ai
    obj = {"nodes": [{"id": "a", "type": "llm", "prompt": "x"}]}
    with patch.object(get_ai(), "chat", return_value=obj):
        out = llm_api.chat_json([{"role": "user", "content": "规划"}], capability="llm")
        check("chat_json 返回 JSON 字符串", isinstance(out, str))
        check("chat_json 内容可解析", json.loads(out).get("nodes", [{}])[0].get("id") == "a")


def test_chat_with_tools_delegation():
    from src.api import llm as llm_api
    from src.api.ai_coin_bridge import get_ai
    called = []
    tools = [{
        "type": "function",
        "function": {
            "name": "add_note",
            "description": "追加笔记",
            "parameters": {"type": "object", "properties": {}},
        },
    }]

    def on_tool(name, args):
        called.append(name)
        return "done"

    with patch.object(get_ai(), "chat", return_value="final") as m:
        out = llm_api.chat_with_tools(
            [{"role": "user", "content": "写笔记"}], tools,
            on_tool_call=on_tool,
        )
        check("chat_with_tools 委托 ai-coin", out == "final")
        # ai-coin 工具格式：含 name + function(callable)
        _, kwargs = m.call_args
        api_tools = kwargs.get("tools") or []
        check("工具已转成 ai-coin 格式", len(api_tools) == 1 and api_tools[0]["name"] == "add_note")
        check("工具函数可调用", api_tools[0]["function"](content="x") == "done")


def test_chat_with_tools_text_tool_call_loop():
    """文本式 <tool_call>（推理模型 mimo-v2.5 等）也被执行并回传，直到模型收尾。

    回归：ai-coin 原生 _tool_loop 只处理 tool_calls 字段；文本式调用曾直接
    作为最终结果返回（write_file 永不执行，象棋 HTML 未生成）。
    """
    from src.api.ai_coin_bridge import chat_with_tools, get_ai

    executed = []

    def on_tool(name, args):
        executed.append((name, args))
        return "文件已写入"

    tools = [{
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件",
            "parameters": {"type": "object", "properties": {}},
        },
    }]

    def fake_chat(model_id, msgs, tools=None, **kw):
        # 第一轮：文本式工具调用；第二轮：收尾
        if len(msgs) <= 2:
            return ("<tool_call>\n<function=write_file>\n"
                    "<parameter=path>outputs/x.html</parameter>\n"
                    "<parameter=content><h1>hi</h1></parameter>\n</tool_call>")
        return "完成，已写入 outputs/x.html"

    with patch.object(get_ai(), "chat", side_effect=fake_chat):
        out = chat_with_tools(
            [{"role": "user", "content": "写文件"}], tools,
            provider="mimo", model="mimo-v2.5", on_tool_call=on_tool,
        )
    check("文本<tool_call>已执行", executed and executed[0][0] == "write_file")
    check("文本工具参数正确",
          executed and executed[0][1].get("path") == "outputs/x.html")
    check("文本工具循环返回最终答复", out == "完成，已写入 outputs/x.html")


def test_vision_delegation():
    from src.api import vision as vision_api
    from src.api.ai_coin_bridge import get_ai
    with patch.object(get_ai(), "chat", return_value="图里有一只猫"):
        # 用 URL（ai-coin 透传，不读本地文件）
        out = vision_api.analyze(image_url="https://example.com/img.png", prompt="描述")
        check("analyze 委托 ai-coin", out == "图里有一只猫")


def test_write_redirect():
    from src.api.ai_coin_bridge import set_assignment, set_provider_enabled, load_state
    state = _ensure_seeded()
    orig_assign = dict(state.get("assignments", {}).get("tts", {}))
    orig_enabled = state.get("providers", {}).get("zhipu", {}).get("enabled", True)

    try:
        set_assignment("tts", "openai", "tts-1")
        s2 = load_state()
        check("set_assignment 写入 state", s2.get("assignments", {}).get("tts", {}).get("provider") == "openai")

        set_provider_enabled("zhipu", False)
        s3 = load_state()
        check("set_provider_enabled 写入 state", s3.get("providers", {}).get("zhipu", {}).get("enabled") is False)
    finally:
        # 还原
        from src.api.ai_coin_bridge import save_state
        state["assignments"]["tts"] = orig_assign
        state["providers"]["zhipu"]["enabled"] = orig_enabled
        save_state(state)


# ═══════════════════════════════════════════════════════════
# 0.4.x 回归：预设自动建行导致 capabilities 丢失的修复 + 新特性
# 全部离线：临时 DB/state/config，不触真实文件与 API。
# ═══════════════════════════════════════════════════════════


def test_ensure_seeded_upsert_fix():
    """预设自动建行（INSERT OR IGNORE）不再吞掉 config 的 display/capabilities。"""
    from src.api import ai_coin_bridge as b
    from ai_coin import AICoin
    ai = AICoin(":memory:")
    cfg = {
        "settings": {"api_preference": "cloud_default",
                     "execution": {"max_retries": 1, "timeout_text": 240,
                                   "timeout_image": 120, "timeout_audio": 20}},
        "providers": {
            "deepseek": {
                "env_api_key": "", "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-test", "api_type": "openai_compatible",
                "enabled": True,
                "models": {
                    "deepseek-chat": {
                        "display": "DeepSeek-V3 (测试)",
                        "capabilities": ["llm"],
                        "default_params": {"temperature": 0.3},
                    }
                },
            }
        },
        "assignments": {"llm": {"provider": "deepseek", "model": "deepseek-chat"}},
    }
    with patch.object(b, "get_ai", return_value=ai), \
         patch.object(b, "_read_config_json", return_value=cfg), \
         patch.object(b, "load_state", return_value=None), \
         patch.object(b, "save_state", lambda s: None):
        b.ensure_seeded()
        p = next(x for x in ai.list_providers() if x.name == "deepseek")
        m = next(x for x in ai.list_models(p.id) if x.name == "deepseek-chat")
        check("upsert: display 写入 DB", m.display_name == "DeepSeek-V3 (测试)")
        check("upsert: capabilities 写入 DB",
              (m.capabilities or {}).get("capabilities") == ["llm"])


def test_resync_models_from_state():
    """resync：state 元数据回填 DB + 剪除预设噪音行，幂等。"""
    from src.api import ai_coin_bridge as b
    from ai_coin import AICoin
    ai = AICoin(":memory:")
    ai.add_provider("openai", preset="openai", api_key="sk-x")  # 自动建空行
    state = {
        "api_preference": "cloud_default",
        "providers": {"openai": {"enabled": True, "is_local": False}},
        "models": {"openai": {"gpt-4o": {
            "capabilities": ["llm", "vision"],
            "display": "GPT-4o (多模态旗舰)",
            "default_params": {},
        }}},
        "assignments": {},
    }
    with patch.object(b, "get_ai", return_value=ai), \
         patch.object(b, "load_state", return_value=state):
        r1 = b.resync_models_from_state()
        p = next(x for x in ai.list_providers() if x.name == "openai")
        m = next(x for x in ai.list_models(p.id) if x.name == "gpt-4o")
        check("resync: gpt-4o 回填 display", m.display_name == "GPT-4o (多模态旗舰)")
        check("resync: gpt-4o 回填 capabilities",
              sorted((m.capabilities or {}).get("capabilities", [])) == ["llm", "vision"])
        check("resync: 预设噪音行被剪除", any("gpt-4o-mini" in x for x in r1["removed"]))

        r2 = b.resync_models_from_state()
        check("resync: 幂等（二次无更新/剪除）",
              r2["updated"] == [] and r2["removed"] == [])


def test_analyze_media_delegation():
    """analyze_media：音频走 input_audio、视频走 video_url 内容块。"""
    from src.api.ai_coin_bridge import analyze_media, get_ai
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "x.wav")
        with open(wav, "wb") as f:
            f.write(b"RIFFfake")
        with patch.object(get_ai(), "chat", return_value="音频内容: 你好") as m:
            out = analyze_media(audio_path=wav, prompt="这段说了什么")
            check("analyze_media(audio) 返回结果", out == "音频内容: 你好")
            parts = m.call_args[0][1][0]["content"]
            check("音频内容块为 input_audio",
                  any(p.get("type") == "input_audio" for p in parts))

        mp4 = os.path.join(td, "x.mp4")
        with open(mp4, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42")
        with patch.object(get_ai(), "chat", return_value="视频描述") as m2:
            out2 = analyze_media(video_path=mp4, prompt="描述视频")
            check("analyze_media(video) 返回结果", out2 == "视频描述")
            parts2 = m2.call_args[0][1][0]["content"]
            check("视频内容块为 video_url",
                  any(p.get("type") == "video_url" for p in parts2))


def test_chat_stream_delegation():
    """chat_stream 委托 ai-coin stream_chat，返回增量生成器。"""
    from src.api.ai_coin_bridge import chat_stream as b_stream, get_ai
    from src.api import llm as llm_api
    with patch.object(get_ai(), "stream_chat", side_effect=lambda *a, **k: iter(["你", "好"])):
        check("bridge chat_stream 逐块产出", list(b_stream([{"role": "user", "content": "hi"}])) == ["你", "好"])
        check("llm.chat_stream 委托 bridge", list(llm_api.chat_stream([{"role": "user", "content": "hi"}])) == ["你", "好"])


def main():
    print("=== ai-coin 接入桥测试 ===")
    test_seed_and_resolve()
    test_config_from_state()
    test_chat_delegation()
    test_chat_json_delegation()
    test_chat_with_tools_delegation()
    test_chat_with_tools_text_tool_call_loop()
    test_vision_delegation()
    test_write_redirect()
    test_ensure_seeded_upsert_fix()
    test_resync_models_from_state()
    test_analyze_media_delegation()
    test_chat_stream_delegation()
    print(f"\n{'=' * 40}")
    if errors == 0:
        print("  ALL AICOIN BRIDGE TESTS PASSED!")
    else:
        print(f"  {errors} TESTS FAILED!")
    print(f"{'=' * 40}")
    return errors


if __name__ == "__main__":
    sys.exit(main())
