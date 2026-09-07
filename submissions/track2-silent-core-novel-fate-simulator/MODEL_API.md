# Silent Core Model API

This is the application integration contract for the English-first model
services used by Novel Fate Simulator. Public hostnames and credentials are not
committed to the competition repository.

## Connection

```text
Base URL: https://<model-host>/v1
Authentication: Authorization: Bearer <API_KEY>
Content-Type: application/json
```

Keep the API key in a backend environment variable. Do not embed it in a public
frontend bundle.

| Operation | Recommended timeout |
|---|---:|
| Chat | 120 seconds |
| Text-to-speech | 180 seconds |
| Image generation | 600 seconds |

## Stable model IDs

| Capability | Model ID | Current implementation |
|---|---|---|
| Chat and text generation | `silent-core/llm` | Qwen3-8B Q4_K_M on llama.cpp HIP |
| Image generation | `silent-core/image` | Z-Image-Turbo |
| Text-to-speech | `silent-core/tts` | Kokoro-82M on 16 CPU threads |

## Authentication

All `/v1/*` endpoints require:

```http
Authorization: Bearer <API_KEY>
```

`GET /health` is unauthenticated. Missing or invalid credentials for model
endpoints return HTTP 401.

## Chat Completions

### `POST /v1/chat/completions`

```json
{
  "model": "silent-core/llm",
  "messages": [
    {"role": "system", "content": "You write cinematic fantasy fiction in English."},
    {"role": "user", "content": "Write an opening scene above a sleeping dragon."}
  ],
  "temperature": 0.8,
  "top_p": 0.95,
  "max_tokens": 800,
  "stream": false,
  "chat_template_kwargs": {"enable_thinking": false}
}
```

Standard parameters include `temperature`, `top_p`, `max_tokens`, `stop`,
`presence_penalty`, `frequency_penalty`, `seed`, and `stream`.

The gateway also exposes `POST /v1/responses` and `POST /v1/completions` for
compatible clients.

## Image Generation

### `POST /v1/images/generations`

```json
{
  "model": "silent-core/image",
  "prompt": "A moonlit fantasy library, cinematic concept art",
  "size": "1024x1536",
  "n": 1,
  "response_format": "url",
  "seed": 2026
}
```

Each dimension must be a multiple of 64 from 512 to 1536. Image requests are
serialized on the single GPU. The returned URL is directly downloadable without
an authorization header.

## Text-to-Speech

### `POST /v1/audio/speech`

```json
{
  "model": "silent-core/tts",
  "input": "Far below the city, the dragon opened one ancient eye.",
  "voice": "heart",
  "response_format": "mp3",
  "speed": 1.0
}
```

The OpenAI-compatible response body contains binary MP3 or WAV audio. The same
endpoint also accepts the existing application's MiniMax-compatible payload and
can return newline-delimited JSON with hexadecimal audio chunks.

## Discovery and health

- `GET /v1/models` returns the three stable `silent-core/*` identifiers.
- `GET /health` returns `ok`, `degraded`, or `starting` plus per-service health.

## Backend environment

```dotenv
LLM_PROVIDER=openai
LLM_BASE_URL=https://<model-host>/v1
LLM_MODEL=silent-core/llm
LLM_ACTION_MODEL=silent-core/llm

IMAGE_BASE_URL=https://<model-host>/v1
IMAGE_MODEL=silent-core/image
SCENE_IMAGE_SIZE=1024x1536

TTS_PROVIDER=minimax
TTS_BASE_URL=https://<model-host>/v1
TTS_MODEL=silent-core/tts
TTS_DEFAULT_VOICE=male-qn-qingse
TTS_ENABLED=true

LLM_API_KEY=<API_KEY>
IMAGE_API_KEY=<API_KEY>
TTS_API_KEY=<API_KEY>
```

## Python SDK example

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["SILENT_CORE_BASE_URL"],
    api_key=os.environ["SILENT_CORE_API_KEY"],
    timeout=600,
)

response = client.chat.completions.create(
    model="silent-core/llm",
    messages=[{"role": "user", "content": "Write one line of narration."}],
    max_tokens=100,
)
print(response.choices[0].message.content)
```

## Error handling

| HTTP status | Meaning | Client behavior |
|---:|---|---|
| 400 | Unsupported parameter or format | Correct the request |
| 401 | Invalid API key | Refresh the backend credential |
| 422 | Validation failure | Check required fields and types |
| 429 | Concurrency or transport limit | Retry with backoff and jitter |
| 500 | Inference failure | Log and retry once |
| 503 | Upstream model unavailable | Wait for health recovery |

Clients should retry only 429, 500, and 503 responses, at most twice, using
exponential backoff.

