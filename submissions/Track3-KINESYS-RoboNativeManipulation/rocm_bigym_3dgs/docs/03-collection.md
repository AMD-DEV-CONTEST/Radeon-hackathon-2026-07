# 32 collection runs and failed-replay governance

## Root causes of widespread replay failures

Official BiGym demonstration data is not guaranteed successful when replayed. Source trajectories may mix absolute and delta action semantics. In this run, source replay ran on BiGym 4.0.0 / MuJoCo 3.1.5, while collection runtime used 4.1.0 / 3.10.0. Any drift in version, control frequency, or action representation can turn a valid track into `reward=0`.

Formal collection uses a two-phase fail-closed process:

1. Physics-only precheck without cameras, without video, without 3DGS, running current runtime at 20 Hz.
2. Only the unique UUIDs that pass raw task reward are written into the replay plan; no random demo is re-rendered.

Delta source actions are converted to absolute labels before `env.step()` and checked in a second absolute environment for final `qpos` error and final reward, so the training set only contains one action semantic.

## Why each episode is written separately

LeRobot v3 metadata and Parquet writer may cache multiple episodes together by default. If the container restarts, the videos may exist while Parquet footers are not yet complete. The collection patch applies three rules:

- Set metadata buffer size to 1.
- Close data/meta writer after each successful episode.
- Update `progress.json` only after reloaded records are readable.

When an empty zero-episode directory is found, it is quarantined. When a non-empty corrupted directory is found, stop immediately; do not fallback to Hub or concatenate incomplete outputs.

## Formal smoke threshold

Before official 32-run collection, at least one complete smoke run must satisfy all of the following:

- Post-replay `reward=1.0`.
- All three H.264 streams (head, left wrist, right wrist) decode fully.
- Strict 3DGS mode with no fallback and no `last_error`.
- Render count equals `(episode frames + reset) x 3`.
- `background_physics` is `0/0/0`.

This smoke run uses 683 frames and 2,052 3DGS renders; only after passing does formal 32-run collection begin.
