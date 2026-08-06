# Observability

## When to Use

Developers and support operators use this runbook to inspect local logs, enable or verify OTLP export, or keep a failing telemetry backend from affecting the desktop application. Observability failure must not make interactive startup depend on backend availability.

## Local Evidence

Xenix writes JSON Lines to `logs/xenix.log` under the active runtime home. The file rotates at approximately 1 MB and retains three backups. Logs may contain local paths and diagnostic context; handle them as sensitive support evidence.

LLM token usage has a separate `logs/llm-usage.jsonl` journal with the same
bounded rotation. It contains only normalized token counts plus hashed
correlation keys, so the UI can reproject a retained usage overview after a
Thread is reopened. It contains no prompt, raw provider payload, raw Thread or
Message id, Tool Result, or replay state. Missing or rotated journal data hides
that overview only; it must never repair conversation state, Tool execution, or
provider history.

When OTLP metrics are enabled, the same normalized usage counts may also leave
the device as metrics, tagged with operation and a hashed model key. They still
contain no prompt, raw provider payload, Thread/Message id, or Tool Result, but
their retention and access control are owned by the configured telemetry backend.

`config/telemetry.json` stores a randomly generated persistent install id. It is not derived from machine identity, but it correlates activity across runs and therefore remains sensitive.

## OTLP Enablement

Standard OpenTelemetry endpoint, protocol, and header variables configure transport. Signal-specific values take precedence over global values. Source runs read them from the developer process. Formal packaging reads them once and embeds them in the frozen release configuration; an installed client ignores ambient `XENIX_OTEL_*`, `OTEL_SDK_DISABLED`, and `OTEL_EXPORTER_*` values.

- Traces and metrics enable when their signal endpoint is set, or when the global OTLP endpoint is set, unless their `XENIX_OTEL_EXPORT_*` override disables them.
- Remote log export is off by default. It requires both `XENIX_OTEL_EXPORT_LOGS=true` and a log or global endpoint.
- `OTEL_SDK_DISABLED=true` disables the SDK path.

Prefer signal-specific endpoints and headers when backends or credentials differ. Remote log export deserves separate review because it can transmit application diagnostic detail. Every embedded header/token is extractable from the client and must not be treated as a server-side secret.

## Verify and Degrade

After enabling a signal, perform one identifiable application action and confirm its arrival in the configured backend. If nothing arrives, inspect the local log and process output for exporter, protocol, authentication, DNS, or connection failures. Xenix has no built-in telemetry health screen, so backend receipt plus local failure evidence is the health check.

Interactive startup uses batch processing and does not synchronously flush after showing the main window. A slow or unreachable backend should not block Qt input; process-exit smoke and diagnostics may flush for deterministic evidence.

For source diagnosis, disable a signal with its Xenix override or remove its endpoint and restart. For an installed release, change the protected release build configuration and publish a new version; changing the user's process environment is intentionally not a supported remote reconfiguration path. Disable remote logs independently before traces or metrics, confirm normal interaction, confirm exporter failures stop, and verify intended remaining signals still arrive.
