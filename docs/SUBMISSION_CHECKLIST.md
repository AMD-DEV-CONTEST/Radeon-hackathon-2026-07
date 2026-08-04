# AMD AI DevMaster Track 2 Submission Checklist

Use this file as the release gate for the final pull request. A checked item must point to evidence a
reviewer can open or reproduce. Do not mark an item complete based only on intended behavior.

## 1. Required Deliverables

| Requirement | Evidence | Status |
|---|---|---|
| Application scenario | `docs/SUBMISSION_BRIEF.md` | Ready |
| Agent architecture diagram | Mermaid diagram in `docs/SUBMISSION_BRIEF.md` | Ready |
| Core capabilities | Track 2 capability matrix in `docs/SUBMISSION_BRIEF.md` | Ready |
| Model and local deployment | `docs/PRODUCTION_DEPLOYMENT.md`, `docs/REPRODUCE.md` | Ready after final host reproduction |
| Radeon inference optimization | Brief optimization table and `benchmarks/README.md` | Protocol ready; final metrics pending |
| Complete source repository | `src/`, `apps/web/`, `scripts/`, `tests/`, `data/` | Ready |
| README with environment and dependencies | `README.md`, `.env.example`, `pyproject.toml`, `uv.lock`, web lockfile | Ready |
| README startup guide | `README.md`, `docs/LOCAL_DEVELOPMENT.md` | Ready |
| 3–5 minute demonstration video | `docs/DEMO_VIDEO_SCRIPT.md` | Script ready; recording pending |
| Command/GUI to final Radeon result | Video sections 1–6 | Recording pending |
| PPT or poster | `submission/XiangLens_Track2_Deck.pptx` | Ready; includes an actual UI capture, rendered and overflow-tested |
| Pull request to competition repository | Final fork/PR URL | Pending |

## 2. Scoring Evidence Matrix

### AI Agent completeness — 60 points

| Criterion | Points | Evidence to show first |
|---|---:|---|
| Clear positioning and creative scenario | 20 | Two-candidate GitHub avatar decision with goal, privacy, and cultural context |
| Task decomposition, tools, RAG, memory | 20 | Eight-step plan, nine node events, QR/EXIF tool, four cited cards, consent proposal |
| Smooth multi-turn experience | 20 | Streaming progress, thread state, approved preference recall, memory deletion |

### AMD Radeon / ROCm — 40 points

| Criterion | Points | Evidence to show first |
|---|---:|---|
| Core inference on Radeon | 20 | `rocm-smi`, llama-server log, localhost model endpoint, production status response |
| Directed inference optimization | 20 | Exact launch command, Q6_K, GPU offload, flash attention, Q8 cache, Top-K RAG, benchmark summary |

## 3. Functional Release Gate

- [ ] One clean fixture completes all nine successful-path nodes.
- [ ] Two fixtures produce a valid comparison and recommendation.
- [ ] Four fixtures complete without exceeding the upload or schema limits.
- [ ] EXIF GPS fixture produces a visible privacy finding.
- [ ] QR fixture produces a visible privacy finding when the optional QR dependency is installed.
- [ ] Every report evidence item has a source title, URL, card ID, and pack.
- [ ] A sensitive-inference prompt takes the blocked branch.
- [ ] A normal observation never identifies the depicted person.
- [ ] A memory proposal remains pending until approval.
- [ ] A rejected memory is absent from later recall.
- [ ] An approved preference is recalled in a new thread for the same access session.
- [ ] Deleting one memory removes it from active recall.
- [ ] Forget Me removes the session's threads, images, messages, and active memories.
- [ ] Safe copy contains no EXIF metadata.
- [ ] A visitor token cannot access another visitor's thread or memory.
- [ ] GitHub Pages contains no permanent application key.

## 4. Radeon Evidence Gate

- [ ] Record `rocm-smi` or `amd-smi` showing AMD Radeon PRO W7900 activity.
- [ ] Record the ROCm version.
- [ ] Record the exact llama.cpp commit.
- [ ] Record the complete `llama-server` launch command.
- [ ] Show the model ID and Q6_K representation.
- [ ] Show the multimodal projection loaded.
- [ ] Show FastAPI using `http://127.0.0.1:8000/v1`.
- [ ] Confirm only FastAPI, not `llama-server`, is publicly tunneled.
- [ ] Run one cold benchmark separately from warm measurements.
- [ ] Run at least one warmup plus three measured multimodal requests.
- [ ] Commit reviewed JSON and Markdown results under `benchmarks/results/`.
- [ ] Report TTFT, final-content TTFT, total latency, decode rate, and JSON success rate.
- [ ] Capture peak VRAM and GPU utilization separately with ROCm tooling.
- [ ] Avoid an unsupported causal claim about W7900 FP8.

## 5. Documentation and Rights Gate

- [ ] All reviewer-facing source comments, UI copy, docs, deck, and captions are English.
- [ ] No private course text, screenshot, prompt, or derivative card is present.
- [ ] No real API key, Bearer token, `.env`, model file, SQLite file, or upload is tracked.
- [ ] Every knowledge source has a URL and rights label.
- [ ] Every image fixture has source, license, and hash provenance.
- [ ] No AI-generated fixture is described as a downloaded open-license image.
- [ ] The project name and paper distinction are explained consistently if asked.
- [ ] The Apache-2.0 code intent and dataset/image licenses are visible.
- [ ] `git status --short` is clean on the final submission branch.

Suggested repository scans:

```bash
git status --short
git ls-files | rg '(^|/)(\.env|runtime|uploads|.*\.gguf)$'
rg -n 'sk-|Bearer [A-Za-z0-9_-]{20,}|XIANG_APP_API_KEY=.+' \
  --glob '!docs/SUBMISSION_CHECKLIST.md' \
  --glob '!*.lock'
```

Review every match manually; placeholders and test fixtures are acceptable only when clearly fake.

## 6. Video Gate

- [ ] Final duration is between 3:00 and 5:00.
- [ ] Video is 1080p or higher with readable terminal and UI text.
- [ ] Spoken narration and captions are English.
- [ ] First 20 seconds state the problem, product, Track 2, and Radeon runtime.
- [ ] The recording shows an actual command-line Radeon environment.
- [ ] The recording shows the real GUI, upload, streaming execution, and final report.
- [ ] Tool trace, retrieved evidence, memory consent, and deletion are visible.
- [ ] Performance metrics and GPU telemetry are legible.
- [ ] No token, permanent key, tunnel control state, private hostname, or personal upload is visible.
- [ ] No edit implies that a cached or fake result was generated live.
- [ ] Final frame contains project name, repository, and one-sentence value proposition.

## 7. Supplementary Deck Gate

- [x] Title identifies XiangLens, Track 2, AMD Radeon, and ROCm.
- [x] Scenario is understandable without narration.
- [x] An actual XiangLens interface capture shows intent, result, and Agent-trace surfaces.
- [x] Architecture labels the public/private boundary.
- [x] All five Agent capabilities are represented.
- [x] Model and local deployment are explicit.
- [x] Optimization slide contains only defensible claims.
- [x] Performance slide uses final measured values or omits numeric claims.
- [x] Safety and consent boundary is visible.
- [x] Final slide links to repository and reproduction steps.
- [x] Every slide renders without clipping, overlap, or placeholder text.

## 8. Final Pull Request

1. Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` if the project is not already in the required
   fork relationship.
2. Rebase or merge the final organizer branch only after a clean backup.
3. Put the XiangLens changes on one reviewable submission branch.
4. Use the pull-request description from `submission/README.md`.
5. Link the demonstration video and deck.
6. Include the exact tested commit SHA and Radeon environment summary.
7. Open every link from a signed-out browser before submitting.
8. Submit before the stated deadline and preserve a local copy of all artifacts.

## 9. Remaining Critical Path

As of the document's creation, the remaining non-code work is deliberately short:

1. Run and review the final W7900 benchmark when the production tunnel is available.
2. Record the 3–5 minute video using `docs/DEMO_VIDEO_SCRIPT.md`.
3. Insert the reviewed metrics into the deck if numeric values are used.
4. Perform the rights/secrets scan and a clean-machine reproduction.
5. Open the final competition pull request.
