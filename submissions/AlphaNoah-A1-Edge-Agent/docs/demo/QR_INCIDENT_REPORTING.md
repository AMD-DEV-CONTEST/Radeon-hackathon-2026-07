# QR Incident Reporting Demo

Status: Implemented as a local-only v0.2 prototype.

## Current function

This demo adds one bounded input path to the existing AlphaNoah Runtime:

```text
QR entry URL
→ local HTML form
→ QRIncidentInputAdapter validation
→ AlphaNoahRuntime.create_event()
→ SQLite
→ Event / NEW
→ existing read-only CLI
```

The page states:

```text
AlphaNoah Industrial Incident Report
AlphaNoah 工业现场问题申报

This prototype creates an incident record.
It does not automatically diagnose equipment faults.
```

Every created Event is marked:

```text
Synthetic demo data
Not a real production incident
```

## Start

Python 3.11+ is required. No third-party Web or QR dependency is used.

PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m alphanoah_a1.web --db tmp/alphanoah_qr_demo.sqlite3
```

Linux/macOS:

```bash
PYTHONPATH=src python -m alphanoah_a1.web \
  --db tmp/alphanoah_qr_demo.sqlite3
```

The service always binds to `127.0.0.1`. The default page is:

```text
http://127.0.0.1:8080/report
```

Demo URL with untrusted prefill values:

```text
http://127.0.0.1:8080/report?asset_id=PACK-003&location=Packaging-Line-A
```

`asset_id` and `location` are only prefilled. The server validates them again
when the form is submitted. They are not authentication or authoritative asset
registry data.

### Physical-phone limitation

`127.0.0.1` always refers to the device opening the URL. Therefore a separate
phone cannot reach a server running on a laptop through this URL. The current
acceptance demo uses a browser on the same machine. LAN binding, firewall
configuration, HTTPS and authentication require an explicit later security
task and are not implemented here.

## Form fields

| Field | Required | Limit | Handling |
|---|---:|---:|---|
| `asset_id` | No | 128 characters | Trimmed, persisted as an Event field |
| `location` | No | 200 characters | Trimmed, persisted as an Event field |
| `event_type` | Yes | 64 characters | Defaults to `equipment_issue_report`; snake_case validation |
| `reporter` | No | 128 characters | Demo identity or blank |
| `description` | Yes | 2000 characters | Trimmed and validated |
| `attachments` | No | 512 characters | Up to five newline-separated string references |

The form does not expose `metadata`, `source`, `actor`, IDs, status or arbitrary
JSON. Metadata is assigned by the adapter. Attachment references are stored as
strings; the server never opens a path, uploads a file or fetches a URL.

## Input adapter boundary

`QRIncidentInputAdapter`:

- allows only the documented fields;
- rejects duplicates, unknown fields and arbitrary metadata;
- trims surrounding whitespace;
- checks required values, lengths and event-type syntax;
- converts attachment references to `list[str]`;
- assigns fixed synthetic-data metadata;
- calls the existing `AlphaNoahRuntime.create_event()`.

Runtime validation remains active after adapter validation. HTTP and QR logic
do not enter Runtime, the state machine or SQLiteStore.

## Successful response

The success page returns:

- `event_id`;
- `trace_id`;
- `asset_id`;
- `location`;
- `description`;
- `NEW` status;
- creation timestamp;
- read-only CLI command templates.

It does not return a diagnosis, risk score, repair action or AI recommendation.

## Inspect persisted Events

Stop the service with `Ctrl+C`, then use the same database:

```bash
PYTHONPATH=src python -m alphanoah_a1.demo \
  --db tmp/alphanoah_qr_demo.sqlite3 list events

PYTHONPATH=src python -m alphanoah_a1.demo \
  --db tmp/alphanoah_qr_demo.sqlite3 show event <event_id>

PYTHONPATH=src python -m alphanoah_a1.demo \
  --db tmp/alphanoah_qr_demo.sqlite3 show trace <trace_id>
```

## Local-demo security boundary

Implemented:

- hard-coded `127.0.0.1` binding;
- GET `/report` and form POST `/report` only;
- 16 KiB request-body limit;
- bounded field count and field lengths;
- strict form content type and UTF-8 handling;
- rejection of duplicate/invalid length headers, Transfer-Encoding and
  incomplete request bodies;
- bounded socket read timeout and graceful request-thread shutdown;
- HTML escaping for prefill, errors and success output;
- Content Security Policy, no-store, nosniff and anti-framing headers;
- no database absolute path in HTML;
- no request headers or form bodies logged;
- one-time, expiring in-memory submission tokens;
- generic error pages without Python traceback;
- Runtime validation cannot be bypassed by the HTTP adapter.

The one-time token provides duplicate-submit protection and limited CSRF
mitigation for this local demo. It is generated in the HTML form, is not
encoded in the QR URL and is not authentication or a claim of complete CSRF
protection.

Not implemented:

- HTTPS;
- production authentication or authorization;
- complete CSRF/session protection;
- rate limiting across processes;
- LAN or public binding;
- reverse proxy hardening;
- durable idempotency across service restarts;
- file upload or attachment retrieval.

## QR generation boundary

The repository does not include a QR generator. For a controlled presentation,
an approved QR tool may encode the demo URL. The QR contains only the entry URL
and optional simulated `asset_id`/`location`. It must not contain credentials,
tokens, personal identity, secrets, sensitive equipment data or history.

## Not implemented by this demo

- equipment diagnosis or Equipment Skill;
- LLM/Ollama/model calls;
- responsible-person notification;
- approval or evidence workflow pages;
- Feishu, DingTalk or WeCom integration;
- account, tenant or asset-management systems;
- production Web deployment.
