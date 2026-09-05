# ADR 0011: Admit PAGE over KServe as a bounded OCR provider boundary

- Status: accepted
- Date: 2026-07-28
- Relates to: [ADR 0009](0009-official-paddle-native-local-ocr.md) and
  [ADR 0010](0010-managed-amd-rocm-deployments.md)

## Context

The existing native Paddle bundle remains a supported local OCR implementation.
A managed Radeon profile needs an OCR implementation that can be realized on a
separate Linux target without coupling Knowledge import or spawned workers to
AMD deployment internals.

## Decision

Define an engine-neutral OCR provider boundary. The first managed implementation
uses a KServe V2-compatible inference endpoint with one PNG image request and one
PAGE 2024-07-15 `PcGts/Page` response.

- Xenix owns source splitting, PDF/TIFF page identity, ordering, transforms,
  canonical assembly, publication, and lifecycle. The provider owns only OCR.
- The normalized unit is a text line. Preferred text is `TextEquiv index=1`.
  Reading order and region/line hierarchy are preserved. Xenix applies the
  inverse transform, round-half-up quantization, then image-bound clamping.
- One OCR generation admits one request at a time. Compressed bytes, image
  dimensions, channels/frames, decoded pixels/bytes, tensors, XML bytes/depth/
  nodes/regions/points/references, deadline, and in-flight memory are mandatory
  manifest limits. A cell without measured cold-probe limits is not admitted.
- A legal no-text result is an empty success. Transport, authentication,
  timeout, binding loss, malformed or hostile XML, profile mismatch, and missing
  generation are typed provider failures. They fail the entire import attempt;
  no partial canonical document is published.
- A spawned Knowledge worker receives only a memory-only ordinary OCR spawn
  specification. The parent holds any managed-generation admission through child
  settlement. The worker does not import AMD code or resolve managed runtime
  state.

## Consequences

- PAGE is the v1 normative interchange; ALTO and custom XML are not fallback
  protocols.
- KServe itself offers no portable hard-cancel endpoint. Client cancellation
  stops waiting while the target's manifest-bounded deadline limits remote work.
- ADR 0009 remains the Paddle delivery decision and is not superseded.
