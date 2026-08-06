# Track 3 Competition Acceptance Target

## One-sentence goal

Deliver a reproducible robot-football reinforcement-learning project on AMD ROCm that demonstrates learning progress, measurable policy improvement, multi-robot independent role control, and GPU performance—not merely a runnable demo.

## Required evidence

### 1. Training convergence

- Show the episode-reward curve and the selected best checkpoint.
- Report the important reward components: approach ball, ball control/contact, ball progress, goal scored, and fall penalty.
- Report at least one task metric such as goal rate, success rate, mean time to reach the ball, or mean distance to the ball.
- Do not claim convergence solely from training iterations or a visually plausible demo.

### 2. Baseline comparison

Compare at least two of the following under the same evaluation conditions:

- deterministic/rule baseline;
- existing RL policy;
- improved configuration or policy.

The comparison must include fall rate plus at least one football metric. Preserve the existing measured locomotion evidence:

- rule-walk: stance and gait both fell after 11 steps;
- pretrained `models/pretrained/t1_walk.pt`: stance 60 steps with zero falls; forward gait 150 steps with zero falls and 6.423 m displacement.

These locomotion results validate the low-level controller only; they are not evidence that the full multi-robot match has passed.

### 3. Reproducibility and original contribution

- Document environment and reward changes made by this project.
- Record algorithm, network, hyperparameters, training command, evaluation command, configuration, and model checksum/path.
- Explain the data source. If training uses online simulation rollouts, state that directly rather than presenting them as an external dataset.
- A clean run must be possible from the canonical project directory.

### 4. AMD ROCm/HIP performance

Record on the competition GPU:

- GPU and ROCm versions;
- parallel environment count;
- training throughput in steps/s;
- inference latency or FPS;
- peak VRAM usage.

Measurements must include command, configuration, run duration, and timestamp.

### 5. Multi-robot scope

The required target is reliable independent control and role assignment, not a new real-time communication architecture:

- load multiple robots in the match;
- control each robot independently;
- assign understandable roles such as striker, support, and defender;
- demonstrate a complete match lifecycle without orphan GPU processes or false-success exits.

Shared world state or lightweight coordination is optional. Learned inter-robot communication is out of scope unless all required evidence is already complete.

## Final demo evidence chain

The submission must tell one verifiable story:

`project changes -> AMD GPU training -> convergence evidence -> checkpoint comparison -> multi-robot role demo -> ROCm performance`

## Go/no-go checklist

- [ ] Local automated tests pass.
- [ ] Canonical local and remote source files have recorded checksums or commit IDs.
- [ ] Low-level locomotion gate passes.
- [ ] Short single-agent football evaluation passes.
- [ ] Short multi-robot lifecycle test exits cleanly.
- [ ] Full demonstration produces logs and an artifact/video.
- [ ] Reward curves and task metrics are exported.
- [ ] ROCm performance measurements are recorded.
- [ ] README commands match the tested commands.
- [ ] GitHub contains the accepted source, configuration, and documentation without secrets or oversized runtime artifacts.

## Scope guard

With two days remaining, do not add features that do not strengthen the evidence chain above. Prioritize measurable correctness, reproducibility, and a stable demonstration over complex communication or architectural expansion.
