# AlphaNoah A1 Edge Agent

Local Edge Release

1. Extract the archive.
2. Run `./scripts/install.sh`.
3. Run `./scripts/configure.sh`.
4. Run `./scripts/start.sh`.
5. Open `http://127.0.0.1:8090`.

The native Linux bundle is the recommended deployment. It uses a private `.venv`, local SQLite, one loopback HTTP entry point, and does not require a Vite development server.

Provider choices:

- Ollama — best for local edge inference.
- vLLM / OpenAI-compatible — best for enterprise local GPU servers.
- Remote API — best where local inference is unavailable; review the data-egress warning.
- Fake — deterministic, network-free evaluation and demo.

Operations: `status.sh`, `healthcheck.sh`, `restart.sh`, and `stop.sh`. Stop before rerunning `configure.sh`; provider hot switching is intentionally unsupported.
