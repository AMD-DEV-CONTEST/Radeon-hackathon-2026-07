"""
Layer 3: 语音工头（v2.0）

管理 2 个引擎（主引擎 + 备用引擎），负责：
- TTS：将文本转为语音，支持语速、音色参数调节
- STT：将语音转文字
- 故障转移：主引擎超时/报错时自动切换到备用引擎
- 上下文：维护当前用户语音偏好设置
- 依赖等待：若标记了 depends_on，由第2层在依赖满足后下发

对应第4层：2 个 TTS/STT Worker
"""
from __future__ import annotations

import asyncio
from typing import Any
from loguru import logger

from .base_foreman import BaseForeman, Workspace
from ..layer4.mcp_contract import ErrorCode


class SpeechForeman(BaseForeman):
    """
    语音工头 —— 管理 TTS 和 STT 引擎。

    故障转移策略：
    - 主引擎超时或报错 → 自动切换到备用引擎
    - 备用引擎也失败 → 返回错误

    用户偏好维护：
    - voice: 默认音色
    - speed: 默认语速
    - language: 默认语言
    """

    foreman_type = "audio"

    def __init__(self):
        super().__init__()
        self.max_retries = 1
        self.base_timeout = 20.0

        # 语音偏好（可持久化）
        # 注意：voice 默认留空，让 speech.py 落到模型默认音色（如 alloy）。
        # 切勿用 "auto"——它是 truthy，会覆盖默认并导致 OpenAI/edge-tts 拒绝。
        self._voice_preferences: dict[str, dict] = {
            "default": {
                "voice": "",             # 默认音色（空 = 后端默认）
                "speed": 1.0,            # 默认语速
                "language": "auto",      # 自动检测
            }
        }

    # ── 执行入口 ──

    async def _execute_impl(self, task: dict, ws: Workspace) -> str:
        """语音工头执行逻辑。TTS 和 STT 走不同路径。"""
        user_input = self._sanitize_input(task.get("user_input", ""))
        task_id = task.get("task_id", "")
        task_type = task.get("task_type", "audio")

        # 判断是 TTS 还是 STT（重构修复 Bug 1）
        # sub_type 来自 DAG 节点类型（NodeType.STT/TTS），是权威信号；
        # audio_path 仅作为 sub_type 缺失时的兜底（旧契约/直连调用）。
        # 修复前 `sub_type=="stt" or audio_path` 会误路由：
        # - 上传录音但 Planner 产出 TTS 节点 → audio_path 为真 → 误走 STT
        # - 未上传音频但 Planner 产出 STT 节点 → 落入 TTS 分支
        sub_type = task.get("sub_type")
        if sub_type == "stt":
            return await self._do_stt(task, ws)
        if sub_type == "tts":
            return await self._do_tts(task, ws)
        if task.get("audio_path"):
            return await self._do_stt(task, ws)
        return await self._do_tts(task, ws)

    # ── TTS ──

    async def _do_tts(self, task: dict, ws: Workspace) -> str:
        """文字转语音。"""
        # v3 修复 H2：TTS 依赖的文本节点已产出内容时，朗读上游文本，
        # 而不是朗读规划器给的操作指令（如"朗读上面生成的文本"）。
        upstream = task.get("upstream_results") or {}
        upstream_texts = [
            str(v).strip() for v in upstream.values()
            if isinstance(v, str) and v.strip()
        ]
        # 重构修复（Bug 10）：删除无设置方的死键 text_to_speak，
        # 直接以 上游文本 → user_input 兜底。
        text = "\n\n".join(upstream_texts)[:2000] if upstream_texts else ""
        if not text.strip():
            text = task.get("user_input", "")
        task_id = task.get("task_id", "")

        if not text.strip():
            raise ValueError("TTS 任务缺少文本内容")

        # 获取语音偏好
        prefs = self._voice_preferences.get("default", {})

        # 检测语言
        lang = self._detect_language(text)

        logger.info(f"[FM:audio] TTS [{task_id}] text={text[:60]}... lang={lang}")

        try:
            # 尝试主引擎
            result = await self._call_tts_primary(text, lang, prefs, task_id)
        except Exception as e:
            logger.warning(f"[FM:audio] TTS 主引擎失败，尝试备用: {e}")
            try:
                result = await self._call_tts_fallback(text, lang, prefs, task_id)
            except Exception as e2:
                raise RuntimeError(f"TTS 所有引擎均失败: 主={e}, 备={e2}") from e2

        # 更新工作区
        ws.last_summary = f"TTS: {text[:50]}..."

        return result

    async def _call_tts_primary(self, text: str, lang: str,
                                  prefs: dict, task_id: str) -> str:
        """调用主 TTS 引擎。"""
        from ..api.speech import text_to_speech
        from ..config import get_config
        from pathlib import Path

        output_dir = Path(get_config().settings.output_dir) / "audio"
        output_dir.mkdir(parents=True, exist_ok=True)

        import time
        filename = f"tts_{task_id}_{int(time.time())}.mp3"
        output_path = str(output_dir / filename)

        # voice 为空或 "auto" 时传 None，让 speech.py 用后端默认音色
        voice = prefs.get("voice") or None
        if voice == "auto":
            voice = None
        return await asyncio.to_thread(
            text_to_speech,
            text=text,
            output_path=output_path,
            voice=voice,
            language=lang if lang != "auto" else None,
        )

    async def _call_tts_fallback(self, text: str, lang: str,
                                   prefs: dict, task_id: str) -> str:
        """调用备用 TTS 引擎（edge-tts 或本地端点）。"""
        from ..api.speech import text_to_speech
        from ..config import get_config
        from pathlib import Path

        output_dir = Path(get_config().settings.output_dir) / "audio"
        output_dir.mkdir(parents=True, exist_ok=True)

        import time
        filename = f"tts_fallback_{task_id}_{int(time.time())}.mp3"
        output_path = str(output_dir / filename)

        # 备用引擎走 edge-tts（在 speech.py 中已实现三层降级）
        return await asyncio.to_thread(
            text_to_speech,
            text=text,
            output_path=output_path,
            voice="zh-CN-XiaoxiaoNeural",
            language="zh" if any('\u4e00' <= c <= '\u9fff' for c in text) else "en",
        )

    # ── STT ──

    async def _do_stt(self, task: dict, ws: Workspace) -> str:
        """语音转文字。"""
        audio_path = task.get("audio_path") or task.get("user_input", "")
        task_id = task.get("task_id", "")

        if not audio_path:
            raise ValueError("STT 任务缺少音频文件路径")

        # v3 P4: 从 prompt 中推断语言（自 v1 迁移）
        lang = self._extract_language_from_prompt(task.get("user_input", ""))
        logger.info(f"[FM:audio] STT [{task_id}] audio={audio_path} lang={lang}")

        try:
            result = await self._call_stt_primary(audio_path, lang, task_id)
        except Exception as e:
            logger.warning(f"[FM:audio] STT 主引擎失败，尝试备用: {e}")
            try:
                result = await self._call_stt_fallback(audio_path, lang, task_id)
            except Exception as e2:
                raise RuntimeError(f"STT 所有引擎均失败: 主={e}, 备={e2}") from e2

        ws.last_summary = f"STT: {result[:100]}..."
        return result

    async def _call_stt_primary(self, audio_path: str, lang: str,
                                  task_id: str) -> str:
        """调用主 STT 引擎。"""
        from ..api.speech import speech_to_text
        return await asyncio.to_thread(
            speech_to_text,
            audio_path=audio_path,
            language=lang if lang != "auto" else None,
        )

    async def _call_stt_fallback(self, audio_path: str, lang: str,
                                   task_id: str) -> str:
        """调用备用 STT 引擎。"""
        from ..api.speech import speech_to_text
        return await asyncio.to_thread(
            speech_to_text,
            audio_path=audio_path,
            language="zh",  # 默认中文
        )

    # ── 语言检测 ──

    def _extract_language_from_prompt(self, prompt: str) -> str:
        """从 prompt 中提取语言代码（v3 P4：自 v1 `agents/speech.py` 迁移）。

        支持关键词：中文/english/日语/韩语/自动检测等；无法推断时返回 auto。
        """
        p = (prompt or "").strip()

        # 直接是语言代码
        if p.lower() in ("zh", "en", "ja", "ko", "fr", "de", "es", "pt", "ar", "ru", "auto"):
            return p.lower()

        # 中文提示
        for hint in ["中文", "汉语", "普通话", "国语", "用中文", "转写为中文"]:
            if hint in p:
                return "zh"
        # 英文提示
        for hint in ["english", "英文", "英语", "转写为英文", "transcribe"]:
            if hint.lower() in p.lower():
                return "en"
        # 日文提示
        for hint in ["日语", "日文", "日本語", "转写为日文"]:
            if hint in p:
                return "ja"
        # 韩文提示
        for hint in ["韩语", "韩文", "한국어", "转写为韩文"]:
            if hint in p:
                return "ko"
        # 自动检测提示
        for hint in ["自动", "auto", "detect", "自动检测", "自动识别"]:
            if hint.lower() in p.lower():
                return "auto"

        return "auto"

    def _detect_language(self, text: str) -> str:
        """检测文本语言。"""
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        if chinese_chars > len(text) * 0.3:
            return "zh"
        return "en"

    # ── 偏好管理 ──

    def set_voice_preference(self, user_id: str, key: str, value: Any):
        """设置用户语音偏好。"""
        if user_id not in self._voice_preferences:
            self._voice_preferences[user_id] = dict(self._voice_preferences["default"])
        self._voice_preferences[user_id][key] = value
        logger.info(f"[FM:audio] [{user_id}] 偏好更新: {key}={value}")

    def get_voice_preference(self, user_id: str, key: str, default=None) -> Any:
        """获取用户语音偏好。"""
        return self._voice_preferences.get(user_id, {}).get(
            key,
            self._voice_preferences["default"].get(key, default)
        )
