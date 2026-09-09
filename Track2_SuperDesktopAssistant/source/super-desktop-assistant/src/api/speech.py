"""
语音 API —— STT（语音转文字）& TTS（文字转语音）。

多后端架构，按优先级自动降级：

STT 后端（按顺序尝试）：
  1. OpenAI 兼容 /v1/audio/transcriptions（OpenAI / vLLM / 兼容服务）
  2. 本地 faster-whisper（需 pip install faster-whisper）
  3. Chat API 回退：base64 音频 → 多模态 LLM 转写

TTS 后端（按顺序尝试）：
  1. OpenAI 兼容 /v1/audio/speech（OpenAI / 兼容服务）
  2. edge-tts（免费，无需 GPU，pip install edge-tts）
  3. 本地 HTTP TTS 端点（可配置）
"""
import base64
import io
import os
import subprocess
import tempfile
from pathlib import Path
from loguru import logger

from ._client import get_client_for
from ..config import get_config


# ─── 安全限制 ───
_MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB — base64 编码后约 33 MB，接近 API 限制


# ═══════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════

def _encode_audio_to_base64(audio_path: str) -> str:
    """将音频文件编码为 base64 字符串。"""
    with open(audio_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_audio_mime_type(audio_path: str) -> str:
    """根据扩展名返回音频 MIME 类型。"""
    ext = Path(audio_path).suffix.lower()
    mime_map = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
        ".opus": "audio/opus",
    }
    return mime_map.get(ext, "audio/mpeg")


# ═══════════════════════════════════════════════════
# STT
# ═══════════════════════════════════════════════════

def _resolve_stt(provider: str | None = None, model: str | None = None):
    cfg = get_config()
    if provider and model:
        p = cfg.get_provider(provider)
        if not p:
            raise ValueError(f"供应商不存在: {provider}")
        m = p.get_model(model)
        if not m:
            raise ValueError(f"模型 {model} 不存在")
        return p, m, model

    resolved = cfg.resolve("stt")
    if not resolved:
        raise ValueError("stt 功能未分配供应商/模型")
    p, m = resolved
    return p, m, m.id


def speech_to_text(
    audio_path: str,
    language: str = "zh",
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """
    语音转文字（多后端自动降级）。

    Args:
        audio_path: 音频文件路径（mp3, wav, m4a, ogg, flac 等）
        language: 语言代码（zh, en, ja, ko, auto 等）
        provider/model: 覆盖配置

    Returns:
        识别文本
    """
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    # ── 后端 1: OpenAI 兼容音频 API ──
    try:
        p, m, model_id = _resolve_stt(provider, model)
    except ValueError:
        pass  # 未配置 provider，跳过
    else:
        try:
            result = _stt_via_openai_api(audio_path, language, p, m, model_id)
            if result:
                logger.info(f"🎤 STT [OpenAI/{model_id}] → {len(result)} chars")
                return result
        except Exception as e:
            logger.warning(f"🎤 STT [OpenAI] 失败: {e}")

    # ── 后端 2: 本地 faster-whisper ──
    try:
        result = _stt_via_faster_whisper(audio_path, language)
        if result:
            logger.info(f"🎤 STT [faster-whisper] → {len(result)} chars")
            return result
    except Exception as e:
        logger.warning(f"🎤 STT [faster-whisper] 失败: {e}")

    # ── 后端 3: Chat API 回退（base64 音频 → 多模态 LLM） ──
    try:
        result = _stt_via_chat_api(audio_path, language)
        if result:
            logger.info(f"🎤 STT [Chat-API] → {len(result)} chars")
            return result
    except Exception as e:
        logger.warning(f"🎤 STT [Chat-API] 失败: {e}")

    raise RuntimeError(
        f"所有 STT 后端均失败。音频: {audio_path}\n"
        f"请检查: (1) .env 中的 API Key  (2) pip install faster-whisper  "
        f"(3) 或配置支持音频的多模态 LLM"
    )


def _stt_via_openai_api(
    audio_path: str, language: str, p, m, model_id: str
) -> str:
    """通过 OpenAI 兼容 /v1/audio/transcriptions 端点转写。"""
    client = get_client_for(p.name)

    # language="auto" 对 OpenAI 意味着自动检测
    api_language = language if language != "auto" else None
    kwargs = dict(model=model_id)
    if api_language:
        kwargs["language"] = api_language

    logger.debug(f"🎤 STT [OpenAI/{model_id}] lang={language}")
    with open(audio_path, "rb") as audio_file:
        kwargs["file"] = audio_file
        transcript = client.audio.transcriptions.create(**kwargs)
    return transcript.text.strip()


def _stt_via_faster_whisper(audio_path: str, language: str) -> str:
    """通过本地 faster-whisper 转写。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper 未安装。请运行: pip install faster-whisper")

    # 使用 small 模型（速度快，适合桌面应用）
    # 可选: tiny, base, small, medium, large-v3
    model_size = os.environ.get("WHISPER_MODEL_SIZE", "small")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")  # int8 适合 CPU

    logger.debug(f"🎤 STT [faster-whisper] model={model_size}, compute={compute_type}")

    model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    lang = None if language == "auto" else language
    segments, info = model.transcribe(audio_path, language=lang, beam_size=5)

    text_parts = []
    for segment in segments:
        text_parts.append(segment.text)

    result = " ".join(text_parts).strip()
    if info.language and language == "auto":
        logger.debug(f"🎤 STT 检测到语言: {info.language} (概率: {info.language_probability:.2f})")

    return result


def _stt_via_chat_api(audio_path: str, language: str) -> str:
    """
    通过 Chat Completions API 转写（回退方案）。

    将音频 base64 编码后发送给支持音频输入的多模态 LLM
    （如 GPT-4o-audio、Qwen-Audio 等），要求其转写音频内容。
    使用 OpenAI 标准的 input_audio 格式，回退到 audio_url 格式。
    """
    from .llm import chat

    # 文件大小限制（base64 编码膨胀 ~33%）
    try:
        audio_size = os.path.getsize(audio_path)
        if audio_size > _MAX_AUDIO_SIZE:
            raise RuntimeError(
                f"音频文件过大: {audio_size} bytes > {_MAX_AUDIO_SIZE} limit "
                f"（base64 编码后接近 API 限制）"
            )
    except OSError as e:
        raise RuntimeError(f"无法读取音频文件: {e}")

    mime_type = _get_audio_mime_type(audio_path)
    audio_b64 = _encode_audio_to_base64(audio_path)

    # OpenAI input_audio 的 format 要求扩展名本身，而不是 mime sub（mp3≠"mpeg"）
    _ext = Path(audio_path).suffix.lower().lstrip(".")
    audio_format = {
        "mp3": "mp3", "wav": "wav", "m4a": "mp4", "ogg": "ogg", "flac": "flac",
    }.get(_ext, "wav")

    lang_hint = {
        "zh": "中文", "en": "English", "ja": "日本語",
        "ko": "한국어", "auto": "自动检测语言",
    }.get(language, language)

    # 多模态消息：包含 base64 音频数据
    # 优先使用 OpenAI 兼容的 input_audio 格式
    messages = [
        {
            "role": "system",
            "content": (
                f"你是一个高精度语音识别系统。请将用户提供的音频内容逐字转写为文本。\n"
                f"语言提示: {lang_hint}\n"
                f"要求: 只输出转写文本，不要添加任何解释、说明或标记。"
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请转写这段音频的全部内容，不要遗漏任何词句。"},
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_b64,
                        "format": audio_format,
                    },
                },
            ],
        },
    ]

    logger.debug(f"🎤 STT [Chat-API] 通过多模态 LLM 转写，音频 {len(audio_b64)} chars base64")

    # 尝试用 vision/llm capability 解析
    last_error = RuntimeError("Chat API STT 回退：未尝试任何 capability")
    for cap in ("vision", "llm"):
        try:
            result = chat(messages, capability=cap, temperature=0.0, max_tokens=4096)
            return result.strip()
        except Exception as e:
            last_error = e
            logger.debug(f"🎤 STT [Chat-API] capability={cap} 失败: {e}")

    raise RuntimeError(f"Chat API STT 回退失败: {last_error}")


# ═══════════════════════════════════════════════════
# TTS
# ═══════════════════════════════════════════════════

def _resolve_tts(provider: str | None = None, model: str | None = None):
    cfg = get_config()
    if provider and model:
        p = cfg.get_provider(provider)
        if not p:
            raise ValueError(f"供应商不存在: {provider}")
        m = p.get_model(model)
        if not m:
            raise ValueError(f"模型 {model} 不存在")
        return p, m, model

    resolved = cfg.resolve("tts")
    if not resolved:
        raise ValueError("tts 功能未分配供应商/模型")
    p, m = resolved
    return p, m, m.id


def text_to_speech(
    text: str,
    output_path: str = "output_tts.mp3",
    voice: str | None = None,
    language: str = "zh",
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """
    文字转语音（多后端自动降级）。

    Args:
        text: 要合成的文字
        output_path: 输出文件路径
        voice: 音色名称（取决于后端）
        language: 语言代码
        provider/model: 覆盖配置

    Returns:
        输出文件路径
    """
    if not text or not text.strip():
        raise ValueError("TTS 文字不能为空")

    # ── 后端 1: OpenAI 兼容音频 API ──
    try:
        p, m, model_id = _resolve_tts(provider, model)
    except ValueError:
        pass
    else:
        try:
            result = _tts_via_openai_api(text, output_path, voice, p, m, model_id)
            if result and os.path.isfile(result):
                logger.info(f"🔊 TTS [OpenAI/{model_id}] → {output_path}")
                return result
        except Exception as e:
            logger.warning(f"🔊 TTS [OpenAI] 失败: {e}")

    # ── 后端 2: edge-tts ──
    try:
        result = _tts_via_edge_tts(text, output_path, voice, language)
        if result and os.path.isfile(result):
            logger.info(f"🔊 TTS [edge-tts] → {output_path}")
            return result
    except Exception as e:
        logger.warning(f"🔊 TTS [edge-tts] 失败: {e}")

    # ── 后端 3: 本地 HTTP TTS 端点 ──
    local_tts_url = os.environ.get("LOCAL_TTS_URL", "")
    if local_tts_url:
        try:
            result = _tts_via_http_endpoint(text, output_path, voice, local_tts_url)
            if result and os.path.isfile(result):
                logger.info(f"🔊 TTS [HTTP/{local_tts_url}] → {output_path}")
                return result
        except Exception as e:
            logger.warning(f"🔊 TTS [HTTP] 失败: {e}")

    raise RuntimeError(
        f"所有 TTS 后端均失败。\n"
        f"请检查: (1) .env 中的 API Key  (2) pip install edge-tts  "
        f"(3) 或设置 LOCAL_TTS_URL 环境变量指向本地 TTS 服务"
    )


def _tts_via_openai_api(
    text: str, output_path: str, voice: str | None, p, m, model_id: str
) -> str:
    """通过 OpenAI 兼容 /v1/audio/speech 端点合成语音。"""
    from pathlib import Path
    client = get_client_for(p.name)
    actual_voice = voice or m.default_params.get("voice", "alloy")

    # BUG5 修复：确保输出目录存在（对齐 HTTP 分支），嵌套路径不再 FileNotFoundError
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    logger.debug(f"🔊 TTS [OpenAI/{model_id}] voice={actual_voice}, {len(text)} chars")

    response = client.audio.speech.create(
        model=model_id,
        voice=actual_voice,
        input=text,
    )
    response.stream_to_file(output_path)
    return output_path


def _tts_via_edge_tts(
    text: str, output_path: str, voice: str | None, language: str
) -> str:
    """
    通过 edge-tts 合成语音（免费，无需 API Key）。

    音色示例:
      zh-CN: zh-CN-XiaoxiaoNeural, zh-CN-YunxiNeural, zh-CN-YunjianNeural
      en-US: en-US-JennyNeural, en-US-GuyNeural
      ja-JP: ja-JP-NanamiNeural, ja-JP-KeitaNeural
      ko-KR: ko-KR-SunHiNeural
    """
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge-tts 未安装。请运行: pip install edge-tts")

    # 音色映射
    voice_map = {
        "zh": "zh-CN-XiaoxiaoNeural",
        "en": "en-US-JennyNeural",
        "ja": "ja-JP-NanamiNeural",
        "ko": "ko-KR-SunHiNeural",
    }
    default_voice = voice_map.get(language, "zh-CN-XiaoxiaoNeural")
    selected_voice = voice or os.environ.get("EDGE_TTS_VOICE", default_voice)

    logger.debug(f"🔊 TTS [edge-tts] voice={selected_voice}, {len(text)} chars")

    async def _synth():
        communicate = edge_tts.Communicate(text, selected_voice)
        await communicate.save(output_path)

    import asyncio as _asyncio
    import concurrent.futures
    try:
        _asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的事件循环，直接创建新的
        _asyncio.run(_synth())
    else:
        # 已有事件循环：在新线程中运行 edge-tts，避免嵌套事件循环冲突
        # 注意：超时后不能 shutdown(wait=True)（会阻塞等待挂起的线程），用 wait=False
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(_asyncio.run, _synth())
            future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            pool.shutdown(wait=False, cancel_futures=True)
            raise RuntimeError("edge-tts 合成超时 (120s)")
        finally:
            pool.shutdown(wait=False)

    return output_path


def _tts_via_http_endpoint(
    text: str, output_path: str, voice: str | None, endpoint_url: str
) -> str:
    """
    通过 HTTP TTS 端点合成语音（如 GPT-SoVITS、CosyVoice 等本地服务）。

    端点应接受 POST 请求，body: {"text": "...", "voice": "..."}
    返回音频二进制数据。
    """
    import httpx

    payload = {"text": text}
    if voice:
        payload["voice"] = voice

    logger.debug(f"🔊 TTS [HTTP] {endpoint_url}, {len(text)} chars")

    resp = httpx.post(endpoint_url, json=payload, timeout=120)
    resp.raise_for_status()

    # 确保输出目录存在
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(resp.content)

    return output_path
