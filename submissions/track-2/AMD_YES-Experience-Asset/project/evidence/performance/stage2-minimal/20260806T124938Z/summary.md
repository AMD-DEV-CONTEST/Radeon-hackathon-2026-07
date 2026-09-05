# Stage 2 deadline-minimal paired result

- `A0/S0`: PASS on the accepted W7900 A0 journey, approximately 2.0 minutes.
- `A1/P1-prefix-cache`: PASS on the same exact-commit journey, 109.21 seconds
  (Playwright 1.8 minutes).
- No functional, evidence, correction, privacy, permission or terminal-state
  regression was observed.
- P1 is selected for final launch because it won the frozen Stage 1 service
  screen and passed this integrated safety check; S0 remains the immediate
  rollback.
- The approximate 9% one-run difference is not a generalized performance claim.
  The P1 log reported a 0.0% cache-hit rate for this journey, so this delta is
  not attributed to prefix caching.
- Peak Stage 2 VRAM is explicitly `NOT_MEASURED`; the post-run device reading
  was 40,741 MiB. No missing measurement was invented.
- Raw logs and checksums are indexed in `manifest.json` and retained on the
  persistent W7900 workspace. No service was exposed publicly.
