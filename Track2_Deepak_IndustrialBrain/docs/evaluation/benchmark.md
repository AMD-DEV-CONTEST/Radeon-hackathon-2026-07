# Prototype Evaluation Benchmark

The included corpus is synthetic and designed for repeatable functional evaluation.

| # | Question | Expected evidence |
|---|---|---|
| 1 | Why did Pump P-101 fail repeatedly in 2025? | Bearing wear, contaminated lubrication, misalignment, vibration, temperature |
| 2 | How many major bearing events occurred for P-101? | Three significant bearing-related events |
| 3 | Which readings exceeded OEM limits? | Vibration above 6.0 mm/s; bearing temperature above 90 C |
| 4 | What maintenance was performed on 22-Nov-2025? | Bearing and seal replacement; housing flush; test |
| 5 | What did the lubricant sample show? | Water and metallic particles |
| 6 | What safety steps apply before pump maintenance? | Permit, shutdown, LOTO, valve isolation, zero energy, PPE |
| 7 | What alert thresholds were recommended? | 6.0 mm/s and 90 C |
| 8 | What was P-101 pressure after verification? | 15 bar |
| 9 | Did C-201 cause the P-101 failure? | No evidence of a relation |
| 10 | What was the P-101 motor current? | Insufficient evidence; system should not invent |

## Acceptance targets

- Equipment-tag extraction: at least 90% on the included corpus.
- Correct source document among top five results: at least 85%.
- Every supported answer includes at least one citation.
- Unsupported questions explicitly report insufficient evidence.
- Local response target: under 15 seconds for the small demonstration corpus.

