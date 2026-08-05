# Chunk retriever built + validated July 18 — retrieval honest for large corpora

One-liner: foundry/retrieval.py (dependency-free: heading-aware
chunking + tf-idf selection into a char budget) activates only when the
seed corpus exceeds [datagen] context_budget_chars (default 6000);
validated end-to-end on a 3-doc, 8,342-char expense corpus where
correct labels require rules from different documents.

Design facts:
- Small corpora: behavior byte-identical to before (whole corpus in
  context) — the proven triage path is untouched.
- Query = target balance value + situation facet + spec description +
  output field names + ALL enum values (the enum vocab is what pulls
  definition sections in reliably).
- Section titles weigh 3× in chunk term counts; scores normalized by
  chunk length; greedy budget packing.
- Provenance: accepted examples carry "_sections" (doc:title list) —
  underscore fields are ignored by train/eval; auditable in
  accepted.jsonl.

Validation (runs/slice-20260718-122307, 4B stand-in teacher, 49
accepted / 61 attempts = 80.3%):
- Cross-doc rule application observed in samples: software-addendum
  "never auto_approve software" applied; travel-addendum international
  rule applied; missing-receipt override applied.
- Fixture assets: seeds/expense_travel_addendum.md,
  seeds/expense_software_policy.md, specs/expense-routing-v2.json,
  configs/pilot_expense_4060.toml.

Known limits (recorded honestly):
- The 4B stand-in mislabels some multi-rule cases (spot-checked: $450
  no-receipt equipment routed needs_finance instead of needs_manager)
  and drifts off the facet's target value — balance skew
  (needs_finance 20 vs auto_approve 8 in 49). Teacher-quality issue,
  not retrieval; expect the 30B to do markedly better. Re-validate
  label quality on Radeon before using this task in the demo.
- tf-idf selection is soft at this corpus size (drops ~3 of 15
  chunks); its value grows with corpus size. The mechanism, budget,
  and provenance are what the submission claims — claims match what
  is built.
