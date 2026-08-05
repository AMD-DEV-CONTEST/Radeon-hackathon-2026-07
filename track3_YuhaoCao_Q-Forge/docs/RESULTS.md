# Audited Results

The authoritative compact values are in `results/main_results.json` and
`results/critic_and_guidance.json`. They were checked against frozen per-reset
metrics and critic/grid JSON in the original experiment workspace.

## Primary paired result

| Method | Success | Net vs Base | Exact McNemar p |
|---|---:|---:|---:|
| Base | 21/50 (42%) | — | — |
| Q selection N=4 | 18/50 (36%) | −3 | 0.25 |
| Q-guidance | 34/50 (68%) | +13 | 0.014633298 |
| QVGM residual | 32/50 (64%) | +11 | 0.0009765625 |

Q-guidance failure→success states:

```text
1, 5, 6, 7, 11, 12, 13, 16, 18, 19, 21, 22, 26, 27, 28, 32, 34, 38, 40
```

Q-guidance success→failure states:

```text
10, 15, 17, 23, 41, 49
```

The `+13` means thirteen additional successful reset states. The success-rate
difference is `+26` percentage points, from 42% to 68%.

## Critic and selected guidance

```text
TD validation loss:      0.006273849
Q(success):              0.421292365
Q(failure):              0.234153494
Q(dataset):              0.287930429
Q(random):              -0.361172169
action gradient norm:    0.007518786, finite

guidance:                10 steps / 0.02 step size / 0.05 max delta
validation transitions:  12,124
mean predicted-Q gain:    0.044556219
improved fraction:        1.0
mean absolute delta:      0.008992091
saturation increase:      0.003131923
```

## Evidence boundary

This audit confirms consistency among existing experiment artifacts. It does not
turn the single-task, paired-seed protocol into a broader generalization result.

