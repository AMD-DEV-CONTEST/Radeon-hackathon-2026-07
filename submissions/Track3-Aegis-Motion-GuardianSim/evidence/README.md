# Supplemental Radeon Evidence

These compact machine-readable files support separate compute and decision
claims. They do not modify the frozen Gate 3.2 safety benchmark.

## Radeon Scale V3 endurance suite

- Full scene per world: Franka, table, and four active YCB entities.
- Frozen batch sizes: 4,096, 8,192, and 16,384 worlds.
- Five independent processes per batch.
- Per process: 200 warmup steps and 2,048 measured steps.
- Formal measurements: 15.
- Total measured steps: 293,601,280.
- Largest batch P50 / P95: 278,051.244 / 278,660.488 env-steps/s.
- Largest batch mean GPU use: 98.817%.
- Full-suite weighted mean / observed peak GPU use: 98.330% / 100%.
- Peak VRAM: 22.05 GiB.

`radeon-scale-report.json` is the immutable schema-3 report and
`radeon-scale-validation.json` is its strict validation receipt.

## Safety Swarm V2 formal decision run

- Candidate actions: 18.
- Frozen uncertainty worlds per candidate: 256.
- Candidate-world pairs: 4,608.
- Candidates passing all 256 worlds: 5.
- Selected action: 256/256 safe worlds and zero sampled clutter contacts.

`safety-swarm-v2-summary.json` is the compact derivative and
`safety-swarm-v2-validation.json` is the strict validation receipt. Full logs,
protocol, environment, and checksums remain in the V5 source release.

## Historical bounded execution-path smoke

`parallel-futures-report.json` and `parallel-futures-validation.json` preserve
an earlier 18-action × 3-repeat execution-path receipt. Its 54 futures are not
the project's main scale result or 54 independent scenarios.

## Claim boundary

Scale V3 environment steps are sustained Genesis physics throughput after
warmup. They are not PPO samples, training examples, inference tokens,
independent safety trials, or physical-robot executions. Scale V3, Safety
Swarm V2, and Gate 3.2 units remain separate throughout the submission.
