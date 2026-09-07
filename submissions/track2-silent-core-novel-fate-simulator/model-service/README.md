# Silent Core Model API

This directory contains the English-first, OpenAI-compatible model-serving
layer used by Novel Fate Simulator. The application consumes it through stable
model IDs, while this directory remains independently testable.

## Public API

- `POST /v1/chat/completions` with model `silent-core/llm`
- `POST /v1/responses` with model `silent-core/llm`
- `POST /v1/images/generations` with model `silent-core/image`
- `POST /v1/audio/speech` with model `silent-core/tts`
- `GET /v1/models`
- `GET /health`

All `/v1/*` requests require `Authorization: Bearer $SILENT_CORE_API_KEY`.

## Models

- LLM: Qwen3-8B Q4_K_M served by llama.cpp HIP
- Image: Z-Image-Turbo
- TTS: Kokoro-82M on 16 CPU threads

The quantized LLM uses about one third of the BF16 model memory and reaches
about 91.6 tokens/s in the fixed single-stream benchmark. The image pipeline
stays resident with model CPU offload, avoiding the previous 48 GB VRAM cliff.
TTS runs on CPU so narration does not contend with image generation.

The stable `silent-core/*` model identifiers keep client integration unchanged
if an implementation model is replaced later.

## Client setup

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://PUBLIC_HOST/v1",
    api_key="sc_...",
    timeout=600,
)
```

See `examples/python_client.py` for chat, image, and speech requests. Image
generation is serialized on the single GPU, so clients should use a request
timeout of at least 300 seconds.

The current `trycloudflare.com` URL is a temporary demo tunnel. It changes when
the tunnel or instance restarts and Cloudflare does not guarantee SSE for Quick
Tunnels. Use a named tunnel or direct HTTPS for the competition demo.

See [performance results](../PERFORMANCE_RESULTS.md) for reproducible before/after
measurements and [the model API](../MODEL_API.md) for the application integration
contract.
