# Policy-true accuracy measured July 18 — mimicry critique answered

One-liner: blind re-annotation of the 100-ticket Radeon holdout against
the policy text gives ground truth independent of the teacher: teacher
0.95, tuned student 0.95, base 0.14 exact — and on the 92 unambiguous
tickets both teacher and student score **1.00**. All 5 teacher-policy
disagreements are on tickets pre-flagged as genuinely ambiguous
(dual-issue), where the teacher chose the recorded defensible
alternative.

Protocol (repeat for any future task):
- Extract holdout inputs with labels STRIPPED (no anchoring).
- Re-read the policy, label each input with a one-line rationale;
  flag ambiguous cases and record the alternative reading.
- Annotator = project author, blind to teacher labels and
  model outputs; rationales published for audit in
  runs/slice-20260718-052618/policy_labels.jsonl.
- Scorer: score_policy_true.py → policy_true_report.json (both in
  repo; joins holdout teacher labels + predictions.jsonl).

Numbers (runs/slice-20260718-052618/policy_true_report.json):
- vs policy, n=100 exact: teacher 0.95 · student 0.95 (priority 0.96,
  one-ticket noise) · base 0.14. Ambiguous count: 8.
- vs policy, unambiguous n=92: teacher 1.00 · student 1.00.

Framing for report/video (verified): "Both the 30B teacher and the
424 MB student apply the written policy essentially perfectly; on every
unambiguous ticket both are flawless, and all residual disagreement
lies in tickets where two readings are defensible."

Honest caveats to carry: annotator is the project author (mitigated by
blind protocol + published rationales + spot-checkable); the seed
policy was also authored in-project (it IS the task definition, so
that's inherent, not a bias); n=100.
