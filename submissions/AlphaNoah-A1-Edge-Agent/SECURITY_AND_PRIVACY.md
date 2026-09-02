# Security and privacy

Provider selection determines the data boundary.

- Ollama on localhost: event data stays on the machine. Data egress: none.
- LAN vLLM/compatible: event data may be transmitted to the configured enterprise LAN endpoint. Data egress: LAN only.
- Remote compatible API: event, knowledge, and analysis context may leave the enterprise environment. Data egress: external.
- Fake: deterministic simulation. Data egress: none.

The service binds only to `127.0.0.1`. AlphaNoah does not expose or reconfigure Ollama/vLLM. The API key is stored only in local `config/alphanoah.env` with mode 600, passed through a process environment variable, and excluded from public health/runtime payloads. Protect the host account and filesystem; localhost binding is not a substitute for host security.

The release contains no model weights, development database, logs, tunnel credentials, or real `.env` file. `reset_demo.sh` only moves the fixed demo database path to a recoverable timestamped backup and never touches the production-like database.
