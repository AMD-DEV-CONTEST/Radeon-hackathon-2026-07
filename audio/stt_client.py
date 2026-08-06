"""Speech-to-text using Qwen Omni multimodal API."""

import base64
import logging
from pathlib import Path

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL
from utils.timing import timing

logger = logging.getLogger(__name__)

OMNI_MODEL = "qwen3.5-omni-flash"


@timing(name="stt_transcribe")
def transcribe(filepath: str) -> str:
    """Transcribe audio to text using Qwen Omni model.

    Uses qwen3.5-omni-flash with input_audio content type.
    Audio data is passed as a data URI (data:audio/wav;base64,...).
    """
    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        return "[未配置 API key]"

    path = Path(filepath)
    if not path.exists():
        logger.error("Audio not found: %s", filepath)
        return "[音频文件不存在]"

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    try:
        with open(path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")

        data_uri = f"data:audio/wav;base64,{audio_b64}"

        completion = client.chat.completions.create(
            model=OMNI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请将这段音频转换为文字，只返回转写文本。"},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": data_uri,
                                "format": "wav",
                            },
                        },
                    ],
                }
            ],
            modalities=["text"],
            stream=True,
        )

        text_parts = []
        for chunk in completion:
            if chunk.choices and chunk.choices[0].delta.content:
                text_parts.append(chunk.choices[0].delta.content)

        text = "".join(text_parts).strip()
        logger.info("STT: %s", text)
        return text

    except Exception as e:
        logger.error("STT failed: %s", e)
        return f"[语音识别失败: {e}]"
