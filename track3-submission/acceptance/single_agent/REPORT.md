# Single-agent fixed-seed comparison

Both controllers were evaluated in the real Genesis environment on the AMD GPU with seed 42, the same configuration, the same frozen low-level locomotion model, and a 100-step cap. The ONNX runtime provider was explicitly recorded as CPU; `--backend gpu` refers to Genesis physics.

| controller | observed steps | falls | goals | mean / min / final base-to-ball | mean reward | termination |
|---|---:|---:|---:|---|---:|---|
| ONNX `chase_v8` | 100 | 0 | 0 | 0.388 / 0.131 / 0.144 m | 0.482 | step limit |
| deterministic rule | 41 | 1 | 0 | 1.348 / 0.123 / 4.599 m | 0.241 | fallen/orientation limit |

The ONNX controller completed the full evaluation without a fall and finished 0.144 m from the ball. The deterministic high-level rule baseline terminated at step 41 after a fall/orientation event. This is football-task evidence because both controllers acted on the same simulated ball task; it is separate from the low-level locomotion-only gate.

## Realized reward components

These are measured per-step raw means; the JSON files also contain raw and weighted sum/min/max values.

| component | ONNX | rule |
|---|---:|---:|
| approach ball | 0.00552 | -0.08843 |
| ball control | 0.67101 | 0.16653 |
| ball contact | 0.00000 | 0.00000 |
| ball progress | 0.00901 | 0.02915 |
| goal scored | 0.00000 | 0.00000 |
| fall indicator | 0.00000 | 0.02439 |

The rule controller moved the ball farther before falling, while the ONNX controller produced substantially stronger approach/control signals and remained stable for the full horizon. No goal or explicit foot-contact event occurred in this short fixed-seed comparison.

Commands:

```bash
/opt/venv/bin/python scripts/eval_hierarchical_short.py --controller onnx --backend gpu --steps 100 --seed 42 --output match_logs/single_onnx_components.json
/opt/venv/bin/python scripts/eval_hierarchical_short.py --controller rule --backend gpu --steps 100 --seed 42 --output match_logs/single_rule_components.json
```

Raw JSON and console logs are stored beside this report. Model and configuration SHA-256 values are embedded in each JSON result.
