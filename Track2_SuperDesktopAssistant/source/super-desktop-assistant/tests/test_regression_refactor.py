"""
重构修复回归测试（离线，不依赖真实 API）。

覆盖 v3-refactor-bugfix-plan.md 的 10 个 bug 中可离线断言的部分：
- Bug 1  TTS/STT 双向误路由（sub_type 权威）
- Bug 2  orchestrate 处理当前用户消息（而非上一轮/空消息）
- Bug 3  reset_context 信号端到端透传
- Bug 4  中文"输出目录"指令写对键
- Bug 5  生图全链路失败 [WARN] 抛 RuntimeError
- Bug 7  压缩摘要不再以 system 角色插入对话中部
- Bug 8  疑问句不触发 api_preference 写盘

风格对齐 test_regression_fixes.py：自写 check() + main() + __main__ 保护。
"""
import os
import sys
import asyncio
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


# ── Bug 1: TTS/STT 双向误路由 ──

def test_tts_node_with_user_audio_stays_tts():
    """上传录音 + Planner 产出 TTS 节点 → 必须走 TTS（修复前被 audio_path 误路由到 STT）。"""
    from src.layer3.speech_foreman import SpeechForeman
    from src.layer3.base_foreman import Workspace

    async def _t():
        fm = SpeechForeman()
        ws = Workspace(task_id="t1", task_type="audio")
        calls = []

        async def fake_stt(task, ws):
            calls.append("stt")
            return "stt-out"

        async def fake_tts(task, ws):
            calls.append("tts")
            return "tts-out"

        fm._do_stt = fake_stt
        fm._do_tts = fake_tts
        task = {
            "task_id": "t1", "task_type": "audio",
            "user_input": "朗读上面生成的诗",
            "sub_type": "tts", "audio_path": "/fake/rec.wav",
            "upstream_results": {"llm_1": "床前明月光"},
        }
        await fm._execute_impl(task, ws)
        return calls

    calls = asyncio.run(_t())
    check("Bug1 TTS节点带用户音频仍走 TTS", calls == ["tts"])


def test_stt_node_without_audio_stays_stt():
    """未上传音频 + Planner 产出 STT 节点 → 必须走 STT（修复前落入 TTS 分支）。"""
    from src.layer3.speech_foreman import SpeechForeman
    from src.layer3.base_foreman import Workspace

    async def _t():
        fm = SpeechForeman()
        ws = Workspace(task_id="t2", task_type="audio")
        calls = []

        async def fake_stt(task, ws):
            calls.append("stt")
            return "stt-out"

        async def fake_tts(task, ws):
            calls.append("tts")
            return "tts-out"

        fm._do_stt = fake_stt
        fm._do_tts = fake_tts
        task = {
            "task_id": "t2", "task_type": "audio",
            "user_input": "转写这段录音",
            "sub_type": "stt",  # 无 audio_path
            "upstream_results": {},
        }
        await fm._execute_impl(task, ws)
        return calls

    calls = asyncio.run(_t())
    check("Bug1 STT节点无音频仍走 STT", calls == ["stt"])


def test_audio_no_subtype_fallback():
    """sub_type 缺失（旧契约/直连）→ 有 audio_path 兜底 STT，无则 TTS。"""
    from src.layer3.speech_foreman import SpeechForeman
    from src.layer3.base_foreman import Workspace

    async def _t():
        fm = SpeechForeman()
        ws = Workspace(task_id="t3", task_type="audio")
        calls = []

        async def fake_stt(task, ws):
            calls.append("stt")
            return "stt-out"

        async def fake_tts(task, ws):
            calls.append("tts")
            return "tts-out"

        fm._do_stt = fake_stt
        fm._do_tts = fake_tts
        # 无 sub_type + 有 audio_path → STT 兜底
        await fm._execute_impl(
            {"task_id": "t3", "task_type": "audio", "user_input": "x", "audio_path": "/a.wav"}, ws)
        # 无 sub_type + 无 audio_path → TTS 兜底
        await fm._execute_impl(
            {"task_id": "t3", "task_type": "audio", "user_input": "x"}, ws)
        return calls

    calls = asyncio.run(_t())
    check("Bug1 sub_type缺失按audio_path兜底", calls == ["stt", "tts"])


# ── Bug 2: orchestrate 处理当前用户消息 ──

def test_orchestrate_uses_current_user_message():
    from src.layer2.supervisor import Supervisor, SubTask, TaskResult

    async def _t():
        sv = Supervisor()
        captured = {}

        def fake_classify(msg, **kw):
            captured["classified"] = msg
            return ["text"]

        sv.classifier.classify = fake_classify
        sv.splitter.split = lambda msg, intents, entities: [
            SubTask(task_id="t1", task_type="text", description="d", prompt="p")]

        async def fake_execute(subtasks, user_message):
            captured["exec_msg"] = user_message
            return [TaskResult(task_id="t1", status="success", data="ok")]

        sv._execute_with_dependencies = fake_execute
        l1 = {"recent_dialogs": [{"role": "user", "content": "上一轮消息"}],
              "entities": {}, "original_goal": ""}
        await sv.orchestrate(l1, user_message="现在这条")
        return captured

    c = asyncio.run(_t())
    check("Bug2 分类使用当前消息", c.get("classified") == "现在这条")
    check("Bug2 执行使用当前消息", c.get("exec_msg") == "现在这条")


def test_orchestrate_fallback_to_recent_dialogs():
    """未显式传 user_message → 回退 recent_dialogs 里最后一条用户消息（向后兼容）。"""
    from src.layer2.supervisor import Supervisor, SubTask, TaskResult

    async def _t():
        sv = Supervisor()
        captured = {}

        def fake_classify(msg, **kw):
            captured["classified"] = msg
            return ["text"]

        sv.classifier.classify = fake_classify
        sv.splitter.split = lambda msg, intents, entities: [
            SubTask(task_id="t1", task_type="text", description="d", prompt="p")]

        async def fake_execute(subtasks, user_message):
            return [TaskResult(task_id="t1", status="success", data="ok")]

        sv._execute_with_dependencies = fake_execute
        l1 = {"recent_dialogs": [
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "历史最后一条"},
        ], "entities": {}, "original_goal": ""}
        await sv.orchestrate(l1)
        return captured

    c = asyncio.run(_t())
    check("Bug2 无当前消息回退recent_dialogs", c.get("classified") == "历史最后一条")


# ── Bug 3: reset_context 信号端到端透传 ──

def test_reset_context_propagates():
    from src.layer2.supervisor import Supervisor, SubTask, TaskResult

    async def _t():
        sv = Supervisor()
        sv.classifier.classify = lambda msg, **kw: ["text"]
        sv.splitter.split = lambda msg, intents, entities: [
            SubTask(task_id="t1", task_type="text", description="d", prompt="p")]
        sv.reset_detector.should_reset = lambda tt, msg: True
        captured = {}

        async def fake_execute(subtasks, user_message):
            captured["reset"] = subtasks[0].reset_context
            return [TaskResult(task_id="t1", status="success", data="ok")]

        sv._execute_with_dependencies = fake_execute
        l1 = {"recent_dialogs": [], "entities": {}, "original_goal": ""}
        await sv.orchestrate(l1, user_message="重新来")
        return captured

    c = asyncio.run(_t())
    check("Bug3 should_reset 写入 SubTask", c.get("reset") is True)


def test_reset_context_not_set_when_false():
    from src.layer2.supervisor import Supervisor, SubTask, TaskResult

    async def _t():
        sv = Supervisor()
        sv.classifier.classify = lambda msg, **kw: ["text"]
        sv.splitter.split = lambda msg, intents, entities: [
            SubTask(task_id="t1", task_type="text", description="d", prompt="p")]
        sv.reset_detector.should_reset = lambda tt, msg: False
        captured = {}

        async def fake_execute(subtasks, user_message):
            captured["reset"] = subtasks[0].reset_context
            return [TaskResult(task_id="t1", status="success", data="ok")]

        sv._execute_with_dependencies = fake_execute
        l1 = {"recent_dialogs": [], "entities": {}, "original_goal": ""}
        await sv.orchestrate(l1, user_message="普通话题")
        return captured

    c = asyncio.run(_t())
    check("Bug3 无重置信号保持 False", c.get("reset") is False)


# ── Bug 4: 中文"输出目录"指令写对键 ──

def test_path_setting_chinese_output_dir():
    from src.layer1.user_agent import ConfigIntentHandler
    import src.config as config_mod

    captured = {}

    class FakeCfg:
        def update_setting(self, key, value):
            captured["key"] = key
            captured["value"] = value
            return "已更新"

        def save_to_file(self):
            return True

    fake = FakeCfg()
    with patch.object(config_mod, "get_config", return_value=fake), \
         patch.object(config_mod, "reload_config"):
        handler = ConfigIntentHandler()
        handler._try_path_setting("输出目录改成 E:\\test\\out")
    check("Bug4 中文'输出目录'→output_dir", captured.get("key") == "output_dir")


def test_path_setting_workspace_dir():
    from src.layer1.user_agent import ConfigIntentHandler
    import src.config as config_mod

    captured = {}

    class FakeCfg:
        def update_setting(self, key, value):
            captured["key"] = key
            return "已更新"

        def save_to_file(self):
            return True

    fake = FakeCfg()
    with patch.object(config_mod, "get_config", return_value=fake), \
         patch.object(config_mod, "reload_config"):
        handler = ConfigIntentHandler()
        handler._try_path_setting("工作目录改成 E:\\test\\ws")
    check("Bug4 中文'工作目录'→workspace_dir", captured.get("key") == "workspace_dir")


# ── Bug 5: 生图全链路失败抛 RuntimeError ──

def test_image_worker_warn_raises():
    import src.agents.image_gen as img_mod
    import src.api.image_gen as api_mod
    from src.layer3.image_foreman import ImageForeman

    async def _t():
        fm = ImageForeman()

        def bad_api(*a, **k):
            raise RuntimeError("backend down")

        def bad_sd(*a, **k):
            raise RuntimeError("sd webui down")

        async def warn_local(*a, **k):
            return "[WARN] 本地生图失败: boom"

        with patch.object(img_mod, "_generate_sdwebui", side_effect=bad_sd), \
             patch.object(img_mod, "_generate_local", side_effect=warn_local), \
             patch.object(api_mod, "generate", side_effect=bad_api):
            try:
                await fm._call_image_worker(
                    {"prompt": "cat", "width": 512, "height": 512}, "img_1")
                return "no-raise"
            except RuntimeError:
                return "raised"

    r = asyncio.run(_t())
    check("Bug5 全链路[WARN]抛RuntimeError", r == "raised")


def test_image_worker_success_still_returns():
    import src.agents.image_gen as img_mod
    import src.api.image_gen as api_mod
    from src.layer3.image_foreman import ImageForeman

    async def _t():
        fm = ImageForeman()

        def bad_api(*a, **k):
            raise RuntimeError("backend down")

        def bad_sd(*a, **k):
            raise RuntimeError("sd webui down")

        async def ok_local(*a, **k):
            return "outputs/img_1.png"

        with patch.object(img_mod, "_generate_sdwebui", side_effect=bad_sd), \
             patch.object(img_mod, "_generate_local", side_effect=ok_local), \
             patch.object(api_mod, "generate", side_effect=bad_api):
            return await fm._call_image_worker(
                {"prompt": "cat", "width": 512, "height": 512}, "img_1")

    r = asyncio.run(_t())
    check("Bug5 生图成功仍正常返回", r == "outputs/img_1.png")


# ── Bug 7: 压缩摘要不再以 system 插入对话中部 ──

def test_summary_not_system_mid_context():
    from src.layer3.llm_foreman import LLMForeman
    from src.layer3.base_foreman import Workspace
    import src.layer3.llm_foreman as fm_mod

    async def _t():
        fm = LLMForeman()
        ws = Workspace(task_id="t7", task_type="text")
        # 预填 16 条 context，超过阈值 (max_context_turns=6 → 12) 触发压缩
        for i in range(16):
            ws.context.append({"role": "user" if i % 2 == 0 else "assistant",
                               "content": f"历史消息{i}"})
        # 锁定 API，跳过 _pick_provider（避免触碰真实配置路由）
        ws.api_provider = "mimo"
        ws.api_model = "mimo-v2.5"
        captured = {}

        def fake_chat_with_tools(messages=None, **kw):
            captured["messages"] = messages
            return ("这是一段足够长的测试输出内容，用于通过推理任务的长度校验。"
                    "快速排序算法实现完毕，主逻辑如上。")

        task = {"task_id": "t7", "task_type": "text",
                "user_input": "写一段代码实现快速排序",
                "upstream_results": {}, "conversation_history": []}
        with patch.object(fm_mod, "chat_with_tools", side_effect=fake_chat_with_tools):
            await fm._execute_impl(task, ws)
        return ws, captured

    ws, captured = asyncio.run(_t())
    system_in_context = [m for m in ws.context if m.get("role") == "system"]
    check("Bug7 压缩后 context 无 system 条目", not system_in_context)
    check("Bug7 摘要已生成", bool(ws.last_summary))
    msgs = captured.get("messages") or []
    system_positions = [i for i, m in enumerate(msgs) if m.get("role") == "system"]
    check("Bug7 messages 中 system 只在开头", system_positions == [0])


# ── Bug 8: 疑问句不触发 api_preference 写盘 ──

def test_question_not_trigger_api_preference():
    from src.layer1.user_agent import ConfigIntentHandler
    import src.config as config_mod

    calls = []

    class FakeCfg:
        def update_setting(self, key, value):
            calls.append((key, value))
            return "已更新"

        def save_to_file(self):
            return True

    fake = FakeCfg()
    with patch.object(config_mod, "get_config", return_value=fake), \
         patch.object(config_mod, "reload_config"):
        handler = ConfigIntentHandler()
        r_question = handler._try_api_preference("本地优先吗？")
        r_cmd = handler._try_api_preference("优先用本地 ollama")

    check("Bug8 疑问句返回 None", r_question is None)
    check("Bug8 疑问句不触发写盘", len(calls) == 1)
    check("Bug8 明确指令仍触发写盘", calls == [("api_preference", "local_first")])


def main():
    print("=== 重构修复回归测试 ===")
    test_tts_node_with_user_audio_stays_tts()
    test_stt_node_without_audio_stays_stt()
    test_audio_no_subtype_fallback()
    test_orchestrate_uses_current_user_message()
    test_orchestrate_fallback_to_recent_dialogs()
    test_reset_context_propagates()
    test_reset_context_not_set_when_false()
    test_path_setting_chinese_output_dir()
    test_path_setting_workspace_dir()
    test_image_worker_warn_raises()
    test_image_worker_success_still_returns()
    test_summary_not_system_mid_context()
    test_question_not_trigger_api_preference()
    print(f"\n{'=' * 40}")
    if errors == 0:
        print("  ALL REFACTOR TESTS PASSED!")
    else:
        print(f"  {errors} TESTS FAILED!")
    print(f"{'=' * 40}")
    return errors


if __name__ == "__main__":
    sys.exit(main())
