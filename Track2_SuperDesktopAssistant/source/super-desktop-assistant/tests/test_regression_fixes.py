"""
本次全面修复的回归测试（离线，不依赖真实 API）。

覆盖修复点：
- B1  _repair_json 多缺陷叠加
- K1  _parse_text_tool_calls 多调用 + 值内含 <parameter=
- H3  沙箱懒初始化
- J   SpeechForeman 默认音色不再 auto
- E1  vision 依赖图片
- M4  DAGNode.to_dict 字段完整
- H6  process() 返回 error 键
- H5  会话侧边栏 last_message 预览
- H6  write_file 允许空内容
- BUG1 本地供应商空 key 可用
- H2  TTS 优先朗读上游文本
"""
import json
import os
import sys
import tempfile
import asyncio
from types import SimpleNamespace
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


def test_repair_json_multi_fault():
    from src.agents.planner import _repair_json
    # 双重缺陷：```json 代码块 + 尾逗号（旧实现各策略独立作用于原文，永远修不好）
    bad = '```json\n{"nodes":[{"id":"a","type":"llm","prompt":"x"}],}\n```'
    repaired = _repair_json(bad)
    try:
        data = json.loads(repaired)
        check("B1 修复：fence+尾逗号叠加", data["nodes"][0]["id"] == "a")
    except json.JSONDecodeError:
        check("B1 修复：fence+尾逗号叠加", False)


def test_text_tool_calls_multi_and_embedded_param():
    from src.api.llm import _parse_text_tool_calls
    content = (
        '<tool_call>\n<function=write_file>\n'
        '<parameter=path>outputs/a.html</parameter>\n'
        '<parameter=content><div data-x="<parameter=1>">hi</div></parameter>\n'
        '</tool_call>\n'
        '<tool_call>\n<function=add_note>\n<parameter=content>note1</parameter>\n</tool_call>'
    )
    calls = _parse_text_tool_calls(content)
    check("K1 修复：同回复解析出 2 个调用", len(calls) == 2)
    check("K1 修复：值内 <parameter= 不被截断",
          "<parameter=1>" in calls[0][1].get("content", ""))
    check("K1 修复：第二个调用被保留", len(calls) >= 2 and calls[1][0] == "add_note")


def test_sandbox_populated():
    from src.agents.tools import _get_allowed_paths, _get_readonly_paths
    check("H3 修复：可写白名单非空", len(_get_allowed_paths()) > 0)
    check("H3 修复：只读白名单非空", len(_get_readonly_paths()) > 0)


def test_speech_foreman_default_voice():
    from src.layer3.speech_foreman import SpeechForeman
    fm = SpeechForeman()
    check("J 修复：默认音色不是 auto", fm._voice_preferences["default"]["voice"] != "auto")


def test_vision_dependency_image():
    from src.agents.vision import _find_source_image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"\x89PNG\r\n\x1a\n")
        tmp_img = tf.name
    try:
        node = SimpleNamespace(depends_on=["img1"])
        context = {"img1": tmp_img}
        img, url = _find_source_image(node, context)
        check("E1 修复：vision 使用依赖节点图片", img == tmp_img)
    finally:
        os.unlink(tmp_img)


def test_dagnode_to_dict_complete():
    from src.orchestration.dag import DAGNode, NodeType
    nd = DAGNode(id="n1", type=NodeType.LLM, prompt="x",
                 reset_context=True, timeout_override=99.0)
    d = nd.to_dict()
    check("M4 修复：to_dict 含 reset_context", d.get("reset_context") is True)
    check("M4 修复：to_dict 含 timeout_override", d.get("timeout_override") == 99.0)


def test_process_returns_error_key():
    from src.main import AssistantEngine

    async def _t():
        eng = AssistantEngine()
        with patch.object(AssistantEngine, "_build_dag",
                          side_effect=ValueError("功能 'llm' 未分配供应商/模型")):
            r = await eng.process("你好")
        return r

    r = asyncio.run(_t())
    check("H6 修复：process 返回 error 键", "error" in r and r["status"] == "error")


def test_conv_label_uses_preview():
    from app import _conv_label
    from src.conversations import Conversation
    c = Conversation(id="x", title="测试", last_message={"role": "user", "preview": "你好世界"})
    label = _conv_label(c)
    check("H5 修复：侧边栏用 last_message 预览", "你好世界" in label)


def test_write_file_empty_content():
    from src.agents.tools import _tool_write_file
    out = os.path.join(_ROOT_DIR, "outputs", "test_empty.txt")
    r = _tool_write_file({"path": out, "content": ""})
    ok = r.startswith("文件已写入")
    try:
        os.remove(out)
    except OSError:
        pass
    check("H6 修复：write_file 允许空内容", ok)


def test_local_provider_empty_key():
    from src.config import get_config, ProviderSpec
    from src.api import _client
    cfg = get_config()
    orig = dict(cfg._providers)
    cfg._providers["vllm_test"] = ProviderSpec(
        name="vllm_test", api_key="",
        base_url="http://127.0.0.1:8000/v1",
    )
    _client.clear_client_cache()
    try:
        _client.get_client_for("vllm_test")
        ok = True
    except ValueError:
        ok = False
    finally:
        cfg._providers.clear()
        cfg._providers.update(orig)
        _client.clear_client_cache()
    check("BUG1 修复：本地供应商空 key 可用", ok)


def test_tts_prefers_upstream_text():
    from src.layer3.speech_foreman import SpeechForeman
    from src.layer3.base_foreman import Workspace
    import src.api.speech as speech_mod

    async def _t():
        fm = SpeechForeman()
        ws = Workspace(task_id="t1", task_type="audio")
        captured = {}

        def fake_tts(text, output_path, voice=None, language=None):
            captured["text"] = text
            return output_path

        task = {
            "task_id": "t1", "task_type": "audio",
            "user_input": "朗读上面生成的诗",
            "upstream_results": {"llm_1": "床前明月光"},
        }
        with patch.object(speech_mod, "text_to_speech", side_effect=fake_tts):
            await fm._do_tts(task, ws)
        return "床前明月光" in captured.get("text", "")

    check("H2 修复：TTS 优先朗读上游文本", asyncio.run(_t()))


def test_conversation_trim_even():
    from src.conversations import Conversation
    c = Conversation(id="trim1")
    for i in range(510):
        c.add_message("user" if i % 2 == 0 else "assistant", f"msg{i}")
    check("L3 修复：裁剪后保持 user/assistant 配对",
          len(c.messages) <= 500 and len(c.messages) % 2 == 0)


def main():
    print("=== 回归修复测试 ===")
    test_repair_json_multi_fault()
    test_text_tool_calls_multi_and_embedded_param()
    test_sandbox_populated()
    test_speech_foreman_default_voice()
    test_vision_dependency_image()
    test_dagnode_to_dict_complete()
    test_process_returns_error_key()
    test_conv_label_uses_preview()
    test_write_file_empty_content()
    test_local_provider_empty_key()
    test_tts_prefers_upstream_text()
    test_conversation_trim_even()
    print(f"\n{'=' * 40}")
    if errors == 0:
        print("  ALL REGRESSION TESTS PASSED!")
    else:
        print(f"  {errors} TESTS FAILED!")
    print(f"{'=' * 40}")
    return errors


if __name__ == "__main__":
    sys.exit(main())
