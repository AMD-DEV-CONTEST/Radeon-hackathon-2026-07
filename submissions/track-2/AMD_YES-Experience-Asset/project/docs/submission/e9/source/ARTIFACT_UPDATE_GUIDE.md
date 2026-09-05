# Material Update Notes

These notes preserve factual boundaries while leaving editing, generation and
review methods to the team.

Product-direction proposals first go through
[`PRODUCT_DIRECTION_AND_ROADMAP.md`](PRODUCT_DIRECTION_AND_ROADMAP.md). A
future idea does not enter judge-facing artifacts until implemented behavior
and traceable evidence exist.

## Suggested content order

1. Put current, traceable claims in [`SUBMISSION_FACTS.md`](SUBMISSION_FACTS.md).
2. Update the English specification, presentation, Judge Entry, official PR
   draft and demo narration as needed.
3. Update the Chinese specification or presentation only when the team finds
   those copies useful.
4. If displayed hashes or snapshot IDs are retained, update them when their
   referenced files change.

The R8 English PDF/PPT are valid submission artifacts. Replacing the PPT's
authentic M1 screenshot with a later English WebUI capture is optional polish,
not a completion gate. The final Demo URL can be added to the publication
surfaces without reopening product claims. [`EVIDENCE_CARD.md`](EVIDENCE_CARD.md)
remains an optional fact reference, not an approval step.

## Stable sections

Do not rewrite positioning, M1–M5 names, phase-gated RAG, Runtime/model
authority, exact-bound approval or local architecture unless the repository
product contract changes.

## Final evidence slots

The application, model/runtime/device manifest, complete W7900 result, Stage 2
decision and test ledger are frozen. Remaining edits are limited to the Demo
URL/timestamps, the registered team/submitter name, official publication links
and contribution wording whose PR merge state changes. A slide 5 screenshot
replacement is optional.

## Claim hygiene

- Do not combine counts or metrics from different commits.
- Do not present service-layer metrics as application performance.
- Do not convert `NOT_RUN`, `CONDITIONAL` or a failed profile into success.
- Do not call a component/API path a complete user flow.
- Describe hallucination controls and limitations; never claim elimination.
- Keep resolved debugging history in engineering evidence, not the judge story.

## File boundary

The repository stores editable text sources, two R8 English final-content
artifacts and older reference binaries.
Build caches, slide renders, raw recordings and private evidence stay outside
the package. The team decides how to edit and review the visual files; factual
claims should remain traceable to current code or evidence.
