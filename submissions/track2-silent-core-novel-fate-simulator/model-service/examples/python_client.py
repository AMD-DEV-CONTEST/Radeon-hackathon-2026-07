"""Minimal integration example using the official OpenAI Python SDK."""

import base64
import os
from pathlib import Path

from openai import OpenAI


client = OpenAI(
    base_url=os.environ["SILENT_CORE_BASE_URL"].rstrip("/") + "/v1",
    api_key=os.environ["SILENT_CORE_API_KEY"],
    timeout=600,
)

chat = client.chat.completions.create(
    model="silent-core/llm",
    messages=[
        {"role": "system", "content": "You write concise cinematic fantasy in English."},
        {"role": "user", "content": "Write an opening scene in a city built above a sleeping dragon."},
    ],
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
print(chat.choices[0].message.content)

image = client.images.generate(
    model="silent-core/image",
    prompt="Cinematic fantasy city above a sleeping dragon, moonlight, detailed concept art",
    size="1024x1024",
    response_format="b64_json",
)
Path("scene.png").write_bytes(base64.b64decode(image.data[0].b64_json))

with client.audio.speech.with_streaming_response.create(
    model="silent-core/tts",
    voice="heart",
    input="Far below the city, the dragon opened one ancient eye.",
    response_format="mp3",
) as response:
    response.stream_to_file("narration.mp3")
