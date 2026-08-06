# Integrity checks and outlier cleaning

## LeRobot v3 full acceptance check

`scripts/validate_lerobot_v3_collection.py` verifies:

- `meta/info.json` has `total_episodes=32`.
- 32 Parquet chunks and 32 episode metadata rows.
- `episode_index=0..31` and continuous frame indexes.
- `state` and `action` are 16-dimensional and contain no NaN/Inf.
- Receipt contains 32 unique UUIDs, all saved, and all `reward=1`.
- Three camera keys each include 32 H.264 videos.
- Codec, dimensions, 20 fps, frame count, duration, and per-frame decode all pass.
- Exact strict 3DGS renderer render-count checks pass.
- Auto-generated `4 x 3` camera-episode contact sheet and `SHA256SUMS`.

A single Parquet chunk or video directory looking like "one file" does not imply one episode; episode_count must be decided from episode metadata, `episode_index`, and row ranges.

## Non-destructive Gaussian cleaning

Cleaning rules combine position, scale, and alpha:

```text
keep = finite
     & inside_manual_bbox
     & radius <= max_radius
     & exp(max(log_scale)) <= max_world_scale
     & sigmoid(opacity) >= min_alpha
```

Output must use a new path; the script rejects when output and input are identical. Each layer writes a JSON manifest recording input/output SHA-256, Gaussian counts, and removal reasons.

The conservative run removed 227,279 of 1,000,000 points, with 221,336 points removed due to very low alpha. One full validation episode must be rerun on cleaned output, then A/B compared with matching-frame triple-camera videos. High SSIM is not equivalent to clearer images; manual review still requires wall continuity, edge stretching, exposure smearing, and low-angle wrist artifacts.
