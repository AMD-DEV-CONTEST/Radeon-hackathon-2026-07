# Q-Forge Demo Storyboard

Target: 1920×1080, 16:9, 4 minutes 39 seconds, English narration and English
subtitles. Subtitle cues use ElevenLabs character-level speech timestamps; each
cue is exactly one text line on a transparent background with a thin outline.

| Time | Visual | Narration purpose |
|---|---|---|
| 00:00–00:18 | Q-Forge title, 42% → 68%, AMD Radeon | Hook and result |
| 00:18–00:58 | Task and Base-policy card | Define model, inputs, and task |
| 00:58–01:38 | Architecture and rollout-data animation | Explain automatic labels and 300P diversity |
| 01:38–02:20 | Critic and constrained-guidance architecture | Explain MC → TD/Cal-QL and trust region |
| 02:20–02:57 | Real side-by-side state-1 video | Base timeout versus guided success |
| 02:57–03:17 | Main result chart | Compare all four methods |
| 03:17–03:34 | Paired transition figure | Show 19 improvements, 6 regressions, exact p |
| 03:34–04:10 | AMD platform and attention backend card | Prove Radeon execution and engineering work |
| 04:10–end | Closing card with author/repository | Restate contribution |

## Paired episode evidence

```text
Task:             LIBERO-Spatial Task 7
Reset state:      1
Inference seed:   2001
Actions/replan:   5
Base:             failure, timeout at 240 steps
Q-guidance:       success at 173 steps
Mean Q gain:      0.0247138
Mean action delta:0.0081027
```

The single-episode recorder preserves CPU, GPU, and NumPy RNG around its adapter
diagnostic so the episode follows the exact sweep random stream.
