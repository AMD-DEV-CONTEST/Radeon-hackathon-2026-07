# GTM Campaign Workspace V1

The Campaign Workspace closes the internal last-mile gap between a strategy receipt and the drafts a human operator can actually inspect. A prepared run exposes nine content-addressed, same-run artifacts:

1. big idea and message hierarchy;
2. primary and secondary channel copy;
3. landing-page draft;
4. lifecycle-email draft;
5. SEO/GEO FAQ drafts;
6. video production brief;
7. audio production brief;
8. preregistered analytics plan; and
9. content calendar.

The landing page and lifecycle email share the same strategy, campaign, claim citation and proof spine. The API derives the public workspace only after validating every source artifact against the prepared-run manifest. The browser renders bounded text fields with `textContent`; it does not accept draft HTML as executable markup.

## Harness boundary

- Every workspace artifact is a draft.
- Human release remains mandatory.
- Automatic publish, send and spend remain disabled.
- A byte change in any bound artifact invalidates preview and release approval.
- The workspace hash is a deterministic digest over the named nine-artifact subset.
- No draft, mechanical render or passing regression test proves publication, delivery, business lift, causal revenue, human preference, 4A quality or Top-1 standing.

## Evidence

`gtm-lifecycle-closure-matrix-v1.json` evaluates the workspace contract across all 456 industry/business-model/lifecycle/budget cases. Each case requires nine artifacts, a shared evidence spine and disabled external activation. The runtime and HTTP tests separately prove prepared-run hash binding and fail-closed behavior after tampering.

