# Final WebUI + P1 live check

- Date: 2026-08-06
- UI branch base: `main@0b6ec88`
- UI route: loopback Vite -> loopback SSH tunnel -> W7900 FastAPI -> local
  vLLM
- Model reported by both `/api/v1/health` and `/v1/models`: `Qwen3.5-9B`
- Test input: synthetic, de-identified office-chair selection experience
- Screenshot: [`p1-live-m2.png`](p1-live-m2.png)

Observed results:

1. M1 ingested and durably saved the synthetic experience.
2. M1 was explicitly accepted as `COMPLETE_WITH_GAPS`.
3. P1 generated a source-linked M2 Critical Moment Map with six moments; the
   UI rendered provenance roles, unresolved time labels, editable titles, and
   explicit criticality review controls.
4. The separate M1 structured tool-proposal probe failed closed first as
   `TIMED_OUT` on a cold request and then as `INVALID_MODEL_OUTPUT` after warmup.
   No tool executed and the durable asset version was preserved. This packet
   therefore proves a live P1-backed M2 product path, not universal success for
   every Agent node.

The API health response reported `gpu_viability=NOT_VERIFIED`; this UI check
does not overwrite that server-side field. Stage 1 W7900/ROCm profile-selection
evidence remains the authority for the P1 service decision.
