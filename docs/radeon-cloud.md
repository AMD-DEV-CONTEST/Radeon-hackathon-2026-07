# Radeon Cloud Configuration

Recorded on 2026-07-27 from the Radeon Cloud Token Factory.

- Provider: Radeon Cloud shared Model API
- Model: `Qwen3.6-35B-A3B`
- Base URL: `https://developer.amd.com.cn/radeon/api/v1`
- Chat endpoint: `https://developer.amd.com.cn/radeon/api/v1/chat/completions`
- Protocol: OpenAI-compatible chat completions
- Instance credits: not required for the shared Model API
- API key: stored in the git-ignored local `.env` at the user's explicit request
- Live connectivity check: successful on 2026-07-27
- Observed model: `radeon-qwen/Qwen3.6-35B-A3B`
- Observed latency: `3046.8 ms`
- Observed request cost: `$0.0001525`

The Token Factory UI labels the model as free while also displaying LLMGateway reference prices. Treat the official shared-API statement, "no credits spent," as applying to Radeon GPU instance credits; verify any gateway billing before high-volume use.

Security: never commit `.env`.
