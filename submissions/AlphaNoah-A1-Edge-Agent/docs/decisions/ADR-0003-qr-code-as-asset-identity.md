# ADR-0003: Use a QR Code as the Initial Physical Asset Identity Anchor

> **AlphaNoah A1 Edge Agent** — *An AMD ROCm-powered industrial asset maintenance edge agent.*

## Status

Accepted for hackathon v0.1

Decision date: 2026-07-22<br>
Implementation status: planned; the demo uses a simulated asset and QR identity.

## Context

Maintenance reasoning is unsafe and unhelpful without a clear physical target. A free-form conversation can easily mix device histories, retrieve the wrong guidance or create a work order for the wrong machine. The demo needs a simple, visible way to ground digital context in one simulated physical asset.

A QR code is widely understood, easy to simulate and requires no specialized sensor. However, it must not be treated as a generic webpage shortcut or as authorization by itself.

## Decision

Use a QR code as the first physical identity anchor:

```text
QR Code
→ asset_id
→ Asset Graph
→ Device Context
→ History / simulated SOP / Open Work Orders
```

The QR payload resolves to a stable `asset_id`. All subsequent Task, Incident, WorkOrder, Memory and Evidence records are scoped to that ID.

The stable domain concept is `asset_id`, not the QR technology. The resolver validates payload shape, lookup result and actor access before activating context.

## Identity and Authorization Boundary

- QR scanning identifies a candidate asset; it does not grant permission.
- The payload should contain an opaque identifier or signed/minimized reference, not customer secrets or full asset records.
- Unknown, malformed, expired or conflicting identity input is blocked.
- Switching assets interrupts or closes the active context before another is loaded.
- Every retrieval includes the active `asset_id` as a mandatory filter.
- Work-order creation displays the selected asset for human confirmation.
- Audit records keep the resolver version and identity evidence hash.

## Reasons

- visible physical-to-digital grounding for judges;
- low hardware and integration risk;
- deterministic context isolation before model invocation;
- clear retrieval boundary for local history and simulated SOPs;
- easy replacement without changing domain records.

## Consequences

Positive:

- the demo begins with a concrete asset rather than a generic chatbot;
- memory isolation and work-order traceability become explainable;
- the same workflow can later support other identity mechanisms.

Negative:

- damaged or incorrect labels need a recovery procedure;
- QR alone cannot prove who scanned it;
- asset registration and label lifecycle remain outside the v0.1 demo;
- cloned codes require a future signing or challenge strategy where threat models demand it.

## Future Identity Mechanisms

The resolver port may later accept:

- NFC;
- RFID;
- visual asset recognition;
- spatial localization;
- robot semantic maps;
- another approved industrial identity mechanism.

These mechanisms may replace QR input, but they still resolve to the same `asset_id` domain object. They must not change Task/Memory/WorkOrder ownership semantics.

The staged identity evolution is described in Future Is Robots?. That future mapping does not imply that visual recognition, localization or a semantic map exists in v0.1.

## Alternatives Considered

### Manual asset selection

Useful as an explicit recovery path, but weaker as the main physical-grounding demonstration and more prone to operator selection error.

### Put full context in the QR payload

Rejected. It creates stale data, exposes unnecessary details and weakens the authoritative local asset store.

### Vision-only asset recognition

Deferred. It adds model uncertainty to identity and is unnecessary for the bounded first demo.

## Demo Data Boundary

`PACK-003` and its context are simulated. No real customer, site, machine, identifier, SOP or maintenance history may be embedded in the QR code or repository.
