# Evaluation Comparison

Closed-loop success is the primary metric. The 4,000-step aligned-prompt model remains the current best submission checkpoint because it has the highest controlled result on seed 99, while the second seed shows high variance that should be disclosed.

| Run | Episodes | Success | Failure | Success rate | 95% Wilson CI | Main lesson |
|---|---:|---:|---:|---:|---:|---|
| baseline_4000_prompt_red_seed99 | 20 | 7 | 13 | 35.0% | 18.1%-56.7% | Prompt mismatch hurts VLA behavior. |
| baseline_4000_prompt_cube_seed99 | 20 | 11 | 9 | 55.0% | 34.2%-74.2% | Best controlled result; keep as submission checkpoint. |
| baseline_8000_prompt_cube_seed99 | 20 | 8 | 12 | 40.0% | 21.9%-61.3% | More training steps did not improve closed-loop success. |
| baseline_4000_prompt_cube_seed123 | 20 | 1 | 19 | 5.0% | 0.9%-23.6% | Second seed exposes large evaluation variance. |
| targeted_4000_prompt_cube_seed99 | 20 | 1 | 19 | 5.0% | 0.9%-23.6% | Hard-case-only fine-tune likely forgot the broad distribution. |

## Failure Coordinates

Coordinates are robot-local cube placement values: cube_x is forward reach and cube_y is lateral offset.

- **baseline_4000_prompt_red_seed99**: ep02 (0.628, -0.100), ep04 (0.562, 0.175), ep07 (0.671, -0.050), ep08 (0.516, 0.073), ep09 (0.446, 0.064), ep11 (0.684, 0.011), ep12 (0.632, -0.012), ep14 (0.402, -0.118), ep15 (0.697, 0.014), ep16 (0.539, 0.160), ep17 (0.582, 0.191), ep18 (0.507, -0.114), ep19 (0.676, -0.136)
- **baseline_4000_prompt_cube_seed99**: ep01 (0.454, -0.101), ep02 (0.628, -0.100), ep05 (0.547, -0.031), ep07 (0.671, -0.050), ep13 (0.521, -0.092), ep14 (0.402, -0.118), ep16 (0.539, 0.160), ep17 (0.582, 0.191), ep19 (0.676, -0.136)
- **baseline_8000_prompt_cube_seed99**: ep01 (0.454, -0.101), ep02 (0.628, -0.100), ep04 (0.562, 0.175), ep06 (0.584, -0.113), ep07 (0.671, -0.050), ep10 (0.655, -0.064), ep11 (0.684, 0.011), ep14 (0.402, -0.118), ep15 (0.697, 0.014), ep16 (0.539, 0.160), ep17 (0.582, 0.191), ep19 (0.676, -0.136)
- **baseline_4000_prompt_cube_seed123**: ep00 (0.416, -0.165), ep01 (0.522, -0.157), ep02 (0.670, -0.185), ep03 (0.561, -0.067), ep04 (0.656, -0.136), ep05 (0.501, -0.066), ep06 (0.474, -0.199), ep07 (0.531, -0.165), ep08 (0.579, -0.172), ep09 (0.495, -0.021), ep10 (0.672, -0.163), ep11 (0.443, 0.116), ep12 (0.406, 0.164), ep13 (0.572, -0.094), ep14 (0.651, 0.108), ep15 (0.503, 0.121), ep16 (0.462, 0.044), ep17 (0.558, 0.124), ep18 (0.495, -0.041)
- **targeted_4000_prompt_cube_seed99**: ep00 (0.521, -0.120), ep01 (0.454, -0.101), ep02 (0.628, -0.100), ep03 (0.515, 0.074), ep04 (0.562, 0.175), ep05 (0.547, -0.031), ep06 (0.584, -0.113), ep07 (0.671, -0.050), ep08 (0.516, 0.073), ep09 (0.446, 0.064), ep10 (0.655, -0.064), ep11 (0.684, 0.011), ep13 (0.521, -0.092), ep14 (0.402, -0.118), ep15 (0.697, 0.014), ep16 (0.539, 0.160), ep17 (0.582, 0.191), ep18 (0.507, -0.114), ep19 (0.676, -0.136)

## Interpretation

- Use output/train/smolvla_kitchen_wrist/final as the current best checkpoint, not the targeted fine-tune.
- The prompt control shows language conditioning matters: Pick up the cube. beat Pick up the red cube. under the same seed and checkpoint.
- The 8,000-step control shows imitation loss and closed-loop success can diverge.
- The targeted-only run collapsed to 5%, so the next data strategy should mix hard-case data with replay from the original broad distribution instead of replacing it.
- The second seed also scored 5%, so any public claim should present seed-99 success as the best controlled result and disclose that robustness still needs work.
