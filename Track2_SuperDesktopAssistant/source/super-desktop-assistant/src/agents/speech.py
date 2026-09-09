"""
🎤 语音执行 Agent —— STT & TTS。
"""
import asyncio
from pathlib import Path
from ..orchestration.executor import register_agent
from ..orchestration.dag import NodeType
from ..api.speech import speech_to_text, text_to_speech
from loguru import logger


# ─── 转写结果 → 语言代码推断 ───

def _extract_language_from_prompt(prompt: str) -> str:
    """
    从 Planner 的 prompt 中提取语言代码。

    Planner 可能在 prompt 中加入语言提示，如：
    - "语言: en" / "language: ja" / "用中文转写"
    - 也接受纯语言代码: "zh", "en", "ja", "ko", "auto"

    如果无法推断，默认返回 "auto"（自动检测）。
    """
    p = prompt.strip()

    # 直接是语言代码
    if p.lower() in ("zh", "en", "ja", "ko", "fr", "de", "es", "pt", "ar", "ru", "auto"):
        return p.lower()

    # 常见的中文关键词
    cn_hints = ["中文", "汉语", "普通话", "国语", "用中文", "转写为中文"]
    for hint in cn_hints:
        if hint in p:
            return "zh"

    # 常见英文关键词
    en_hints = ["english", "英文", "英语", "转写为英文", "transcribe"]
    for hint in en_hints:
        if hint.lower() in p.lower():
            return "en"

    # 常见日文关键词
    ja_hints = ["日语", "日文", "日本語", "转写为日文"]
    for hint in ja_hints:
        if hint in p:
            return "ja"

    # 常见韩文关键词
    ko_hints = ["韩语", "韩文", "한국어", "转写为韩文"]
    for hint in ko_hints:
        if hint in p:
            return "ko"

    # 自动检测关键词
    auto_hints = ["自动", "auto", "detect", "自动检测", "自动识别"]
    for hint in auto_hints:
        if hint.lower() in p.lower():
            return "auto"

    # 默认：自动检测
    return "auto"


# ═══════════════════════════════════════════════════
# 注册 Agent
# ═══════════════════════════════════════════════════

@register_agent(NodeType.STT)
async def execute_stt(node, prompt: str, context: dict) -> str:
    logger.info(f"[STT] [{node.id}] 语音转文字")

    audio_path = context.get("_user_audio")
    if not audio_path:
        return "[WARN] 没有可用的音频文件。请先上传音频。"

    # 从 prompt 中提取语言（不再把整个 prompt 当语言代码）
    language = _extract_language_from_prompt(prompt)
    logger.info(f"[STT] [{node.id}] 语言: {language} (从 prompt 推断)")

    result = await asyncio.to_thread(
        speech_to_text, audio_path, language=language
    )
    logger.debug(f"[STT] [{node.id}] → {result[:100]}...")
    return result


@register_agent(NodeType.TTS)
async def execute_tts(node, prompt: str, context: dict) -> str:
    logger.info(f"[TTS] [{node.id}] 文字转语音 ({len(prompt)} chars)")

    from ..config import get_config
    output_dir = Path(get_config().settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / f"tts_{node.id}.mp3")

    # 检测语言（用于选择 TTS 音色）
    has_chinese = any('一' <= c <= '鿿' for c in prompt)
    language = "zh" if has_chinese else "en"

    try:
        result_path = await asyncio.to_thread(
            text_to_speech, prompt, output_path=output_path, language=language
        )
        logger.debug(f"[TTS] [{node.id}] → {result_path}")
        return result_path
    except Exception as e:
        logger.error(f"[TTS] [{node.id}] 失败: {e}")
        return f"[WARN] TTS 失败: {e}"
