# Privacy, Permissions and Safety Controls

## Threat model

The demo handles hypothetical technical scenarios but is designed as though inputs could contain sensitive site or analyst metadata. The main threats are:

- accidental data exfiltration to a cloud endpoint;
- an LLM requesting an unsafe or unsupported action;
- persistence of personal or exact-location data;
- public exposure of the dashboard or model endpoint;
- path traversal through downloadable artifacts;
- treating generated language as an operational instruction.

## Local-only defaults

- LLM endpoint: `127.0.0.1:8000`.
- Dashboard endpoint: `127.0.0.1:8080`.
- Local retrieval reads bundled files only.
- The offline path requires no network.
- The dashboard rejects every non-loopback bind; remote serving is outside this unauthenticated prototype's threat model.
- The LLM client accepts only credential-free loopback HTTP(S) endpoints.

## Role allowlists

| Role | Allowed examples |
|---|---|
| analyst | validate, assess site, retrieve, simulate, analyze, read/write memory, report |
| reviewer | retrieve, read memory, report |
| observer | retrieve and report |

The following are never allowed:

- `operational_control`;
- `equipment_control`;
- `issue_public_alert`.

`external_network` is denied in local-only mode.

## Redaction

Before memory persistence, mappings and nested collections are recursively inspected. Values under known sensitive keys are replaced with `[REDACTED]`, including:

- operator/contact names and emails;
- exact coordinates;
- API keys, tokens and passwords.

Memory files are created with Unix mode `0600` and are scoped by session ID. A session can be explicitly deleted.

## Planner boundary

The LLM must return only a JSON list. The workflow verifies:

- every item is a string;
- every step is allow-listed;
- every required step appears;
- no unsupported action is present.

Tool input is taken from the validated case, never reconstructed from LLM prose. Tool output is immutable from the planner's perspective.

## HTTP boundary

The dashboard:

- limits request bodies to 1 MB;
- accepts only a JSON case object;
- restricts session IDs to 1–64 letters, numbers, `-` or `_`;
- validates artifact routes and filename basenames;
- adds `nosniff`, no-store and Content Security Policy headers;
- has no CORS opt-in and no external JavaScript dependency.

## Tests

`tests/test_security_memory.py` and `tests/test_web.py` verify denial, redaction, file mode, localhost mode, unsafe session rejection, health, API execution and artifact access.

## Residual risks

- redaction is key-based and cannot detect arbitrary sensitive content embedded in free text;
- local administrators can access process memory and files;
- local users and administrators can still inspect localhost traffic and generated artifacts;
- the prototype is not an accredited cybersecurity product.
