# Provider setup

Run `./scripts/configure.sh`. The resulting `config/alphanoah.env` is local, gitignored, mode 600, and never included in a release archive.

## Ollama

The default endpoint is `http://127.0.0.1:11434`; the validated model recommendation is `qwen3.5:9b`, but any installed compatible model may be selected. The installer never changes Ollama binding or downloads a model. Use `ollama list` and, only when you choose, `ollama pull MODEL`.

## vLLM / local compatible endpoint

The suggested endpoint is `http://127.0.0.1:8000/v1`. This profile deliberately maps to the existing `openai_compatible` adapter and checks `/v1/models`; it is not a separate client. Loopback, private LAN, and external scopes are labeled separately.

## Remote API

Enter the base URL, model, and key interactively. Explicit consent is required. Keys are not printed by start/status/health endpoints or written to application logs.

## Fake and offline-only

Fake is deterministic and has no egress. Set `ALPHANOAH_OFFLINE_ONLY=true` before configuration to block clearly public endpoints while allowing loopback and RFC1918/private LAN endpoints.

Ollama was host-validated on AMD. OpenAI-compatible behavior is test-harness validated; a real vLLM server is not claimed as host-validated by this package build.
