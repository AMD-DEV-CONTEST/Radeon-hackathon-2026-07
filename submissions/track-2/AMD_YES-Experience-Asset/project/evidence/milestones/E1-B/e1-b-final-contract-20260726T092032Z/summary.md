# E1-B evidence — final E1-A contract realignment for PR #8

Packet: `E1-B-final-contract-20260726T092032Z`
Issue: #6 · PR: #8 · branch: `codex/e1-b-react-shell`

## Outcome and scope

The E1-B status shell is locally realigned to the only final E1-A contract
source, `main@431e1a54040efbe4ccf04daf51b96e3642d233da`.

- All 14 E1-A files are vendored byte-for-byte and SHA-256-bound; the separate
  public RAG contract retains its true `main@14a43a4` provenance.
- Progress uses only backend-supplied public milestone percentage/basis. Internal
  units never become user-visible percentage, and ETA appears only with a
  backend-supplied value plus basis.
- The synthetic active run validates and renders the final canonical work plan,
  current-source retrieval, policy decision, actual tool execution, and
  verification result. A model proposal is never treated as permission or an
  execution record.
- Cross-asset candidates come from final `ExperienceAssetV1` summary fields only
  after accepted M4 readiness matches the current asset/version/content hash and
  the public trace. Mismatches fail closed.
- No-match is valid; confirm/decline are explicit; bounded detail is available
  only on the confirmed relation; no historical detail body is preloaded.
- Editing/reopening M1-M4 invalidates readiness, candidates, decisions, related
  links, and detail.

Explicit non-goals: no backend/root-schema change, M1-M5 workflow feature, live
asset/progress/relation endpoint, performance or GPU work, E2+ capability,
publication, merge, or milestone promotion.

## Requirement mapping

- **AC:** AC-03, AC-04, AC-11, AC-15, AC-17, AC-19, AC-22, AC-30.
- **L1:** cross-cutting E1-B status shell and the M4 -> M5 relation-readiness
  gate; no M1-M5 promotion is claimed.
- **L2:** Canonical state; Persistence and resume; Retrieval phase integrity;
  Failure behavior; Observability.
- **Retrieval phases:** current-source; post-M4 summary candidate/no-match;
  confirmed-detail.
- **Track 2/submission relevance:** reproducible observation and evidence for the
  local Experience Asset Agent. This local packet makes no model, W7900, ROCm,
  or performance claim.

## Reproduction and observed results

| Gate | Result |
|---|---|
| E1-A provenance | PASS — 15/15 total vendored hashes; 14/14 E1-A files byte-identical |
| TypeScript / ESLint / build | PASS |
| Vitest | PASS — 8 files, 72 tests |
| Mock Playwright | PASS — 15 executable tests; live test expectedly skipped |
| Real FastAPI Playwright | PASS — 16/16 against detached exact `main@431e1a5` |
| AC-30 public checker | PASS — 5/5 relation traces |
| Exact E1-A backend | PASS — contracts current, Ruff, 46 pytest tests |
| Repository QA | PASS — static checks, 31 unit tests, PR contract gate |
| Credential/privacy boundary | PASS |

The live backend was started on `127.0.0.1` from a detached exact E1-A worktree
with FastAPI 0.128.8. Its health response reported `status=ok`, `database=ok`,
`inference_mode=local_only`, and `gpu_viability=NOT_VERIFIED`. The temporary
worktree and database were removed after the run.

Retained screenshots are sanitized public synthetic states plus the loopback
live-health/not-served state. Visual review found no private user content,
credentials, emails, absolute local paths, raw traces, or historical detail body.

## Failures, recovery, and unverified areas

Retained failures:

1. The fresh clone had no frontend dependencies; pre-install typecheck/test
   failed, then `npm ci` restored the lockfile environment.
2. The first installed unit run correctly caught two legacy trace version/hash
   mismatches. Fixtures were bound to final canonical readiness; the final
   hardened suite passed 72/72.
3. The first mock E2E rerun found one stale exact label assertion; after aligning
   the assertion to the existing LOCKED label, all 15 executable tests passed.
4. One provenance invocation used the repository root rather than `web/`; it was
   excluded and rerun correctly with 15/15 passing.

Still unverified:

- GitHub CI after push;
- owner/quality-owner review, private gates, Ready-for-review, and merge;
- W7900/ROCm/model viability or performance;
- live asset/progress/relation behavior, because final E1-A does not expose
  those endpoints. The UI truthfully renders `not_served` instead.

`npm ci` also reported 10 lockfile audit findings (3 moderate, 6 high,
1 critical). No potentially breaking `npm audit fix --force` was run because it
is outside this PR's approved behavior scope.

## Decision and history

- **Result:** `CONDITIONAL` — local public PR gates pass, but this draft packet
  does not promote E1 and still requires GitHub CI plus owner review. The exact
  clean implementation commit is `dc0cc13c666ba8529c8f80f3246dd81d46a4f103`.
- **Exact rollback:** pre-resolution PR head
  `1ffe0757729ac79b8a0702800952255699619ebf`; post-main-merge/pre-implementation
  baseline `93676bed104cd9ca1d9fe56016f11eab1636600b`. Roll back with a normal
  `git revert dc0cc13c666ba8529c8f80f3246dd81d46a4f103`, never shared-history reset.
- **History:** supersedes the conclusions of
  `E1-B-20260724T105247Z-relation` without altering that historical packet.
- **Promotion authority:** `kinnyuww` / quality owner. No self-merge or
  Ready-for-review claim is made.
