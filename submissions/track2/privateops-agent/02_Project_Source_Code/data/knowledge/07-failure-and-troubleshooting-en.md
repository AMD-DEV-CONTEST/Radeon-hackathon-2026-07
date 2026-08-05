# Failure and Troubleshooting

PrivateOps fails visibly. An unconfigured development server asks for a provider instead of inventing an AI answer. A missing or unhealthy local model returns a stable provider error. `rocm-local` rejects non-loopback URLs and never falls back to a shared API. Unsupported Windows collectors return `unsupported`; failed collectors return `failed`.

Malformed JSON, oversized payloads, path escape, shell metacharacters, expired or reused confirmation tokens, unknown tools, unverifiable GPU claims, and audit deletion without an exact identifier are rejected. API keys never appear in public status, repository files, or audit exports.
