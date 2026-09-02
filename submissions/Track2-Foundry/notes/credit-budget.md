# Credit budget: 5 credits remaining after week-1 gate — July 17, 2026

UPDATE July 18: **Session 1 (~50 min: 21-min full build + full bench
ladder + 19GB downloads) left the balance UNCHANGED at 5.** Either
sub-credit sessions round to zero or the meter is coarser than feared.
Implication: Session 2 video capture is comfortably affordable with
generous retakes, and a Radeon UI rehearsal before capture is
affordable too. Keep the destroy-when-done discipline anyway — the
meter's granularity is still unverified, and one forgotten overnight
instance could eat everything. Bonus-endpoint pricing remains unknown
(separate billing class from instances) — still worth the Discord
question before attempting.

Original assessment (July 17), kept for context:
One-liner: the entire week-1 gate (probes + 2 pilots + full 1K run +
model downloads, roughly 1.5-2h of instance time) left the balance at
**5 credits**; burn rate per hour unknown; treat remaining Radeon time
as ~two short scripted sessions unless a top-up is possible.

Consequences, binding until the rate/top-up question is answered:
- ALL development happens on the 4060 with the 4B stand-in teacher.
  The Radeon is only touched with a pre-written, rehearsed script.
- Remaining Radeon needs, batched into two sessions:
  1. **Benchmark session (~30-40 min):** teacher tok/s via llama-bench,
     student tok/s across quant ladder (Q4/Q5/Q6/Q8), rocm-smi
     captures. Quant *accuracy* evals run locally — only speed numbers
     need Radeon silicon.
  2. **Demo capture session (~60 min):** one full agent run on the
     30B teacher, screen-recorded, plus retake buffer. Do this LAST,
     after feature freeze, so it's one take of a finished product.
- The 20-pt bonus (dedicated vLLM endpoint) may be unaffordable —
  endpoint deployment burns credits at its own rate. Decide only after
  the top-up answer; do not spend toward it speculatively.
- URGENT Discord question (add to runbook list): "What is the credit
  burn rate per instance-hour, and can hackathon participants get a
  top-up if they run out before the deadline?"
