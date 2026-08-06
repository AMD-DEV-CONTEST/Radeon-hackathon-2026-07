# Latency-Aware VLA

**Track 3: Physical AI Challenge** · AMD AI DevMaster Hackathon 2026

**Author:** Zhang Boyu · [boyuzhang1218@gmail.com](mailto:boyuzhang1218@gmail.com) · [github.com/zby1218](https://github.com/zby1218)

> End-to-end Physical AI on one AMD Radeon GPU: Genesis demos → SmolVLA/π0.5 train →
> Sync / Async / RTC latency eval → Env-B held-out perturbation.

**Demo (3–5 min):** https://youtu.be/rXQQ4s-CxEE  
**PR title:** `Track 3, Zhang Boyu, Latency-Aware VLA`

**Headline (seed=99):** SmolVLA Sync **2/20** · Sync+200 ms **0/20** · Async+200 ms **1/20** place / **4/20** lift ·
π0.5 expert-only **0/20** → B1d **1/20** · Env-B → **0/20** place · chunk P50 ≈305/343 ms · B1d train VRAM **32.3 GB**.  
Details: [`artifacts/formal/RESULTS.md`](./artifacts/formal/RESULTS.md).

---

## Official Track 3 checklist

| Requirement | Where |
|---|---|
| Technical report (application, architecture, data, AMD use, innovation, deliverables, team) | [`artifacts/technical-report.pdf`](https://github.com/zby1218/Radeon-hackathon-2026-07/releases/download/track3-artifacts/technical-report.pdf) · longer paper PDF on same Release · [`paper/`](./paper/) |
| Project source | this directory |
| Docker (preferable) | [`Dockerfile`](./Dockerfile) — ROCm recipe; formal runs used Radeon Cloud `/workspace/rdna` |
| Reproducibility README | **this file** + [`ENVIRONMENT.md`](./ENVIRONMENT.md) + [`requirements-lock.txt`](./requirements-lock.txt) + [`DATA_AND_WEIGHTS.md`](./DATA_AND_WEIGHTS.md) |
| Demo video 3–5 min | https://youtu.be/rXQQ4s-CxEE |
| Supplementary figures | Release [`track3-artifacts`](https://github.com/zby1218/Radeon-hackathon-2026-07/releases/tag/track3-artifacts) |

---

## Environment setup

**Contest / Radeon Cloud (matches frozen numbers):**

```bash
source /workspace/rdna/bin/activate   # Python 3.12, torch 2.9.1+rocm7.2.1, lerobot 0.4.4, genesis 1.3.1
export HF_LEROBOT_HOME=/workspace/cache/huggingface/lerobot
cd latency_aware_vla
```

Pins: [`ENVIRONMENT.md`](./ENVIRONMENT.md). Dependencies: [`requirements-lock.txt`](./requirements-lock.txt).

**Docker (preferable packaging):**

```bash
docker build -t latency-aware-vla:track3 .
# Requires AMD ROCm device passthrough; mount models/datasets per DATA_AND_WEIGHTS.md
```

---

## Step-by-step reproduction

1. Obtain Env-A dataset + base/finetuned weights ([`DATA_AND_WEIGHTS.md`](./DATA_AND_WEIGHTS.md)).
2. (Optional) regenerate demos: `bash scripts/run_gen_env_a.sh`
3. Train: `bash scripts/run_train_smolvla_b0.sh` then `bash scripts/run_pi05_continue_train.sh`
4. Eval: `bash scripts/run_formal_eval_matrix.sh` · `bash scripts/run_rtc_story_matrix.sh` · `bash scripts/run_env_b_matrix.sh`
5. Compare tables to `artifacts/formal/*/eval_summary.json` — do not hand-edit scores.

Frozen task string: `Pick up the fruit and place it in the basket.`  
Success = lift (≥2 cm, ≥8 frames) **and** fruit in basket.

---

## Formal results (summary)

| Setting | Place | Lift |
|---|---:|---:|
| SmolVLA Sync-full native | 2/20 | 3/20 |
| SmolVLA Sync-full +200 ms | 0/20 | 2/20 |
| SmolVLA Async E=10 +200 ms | **1/20** | **4/20** |
| SmolVLA RTC E=10 +200 ms | 0/20 | 1/20 |
| π0.5 B1d Sync-full | 1/20 | 1/20 |
| Env-B SmolVLA / π0.5 B1d | **0/20** / **0/20** | 1/20 / 1/20 |

**Claims:** Async vs Sync under delay; RTC continuity without place uplift; B1d unlocks grasp; Env-B pose sensitivity; measured AMD VRAM/latency.  
**Not claimed:** language generalization, open-world objects, sim-to-real, RTC place win.

---

## Layout

```text
latency_aware_vla/
  README.md  ENVIRONMENT.md  DATA_AND_WEIGHTS.md  Dockerfile  LICENSE
  requirements-lock.txt
  configs/   scripts/   paper/
  artifacts/formal/     # frozen JSON + RESULTS.md
```

---

## License

Apache-2.0 — [`LICENSE`](./LICENSE).
