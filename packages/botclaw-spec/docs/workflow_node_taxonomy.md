# BotClaw Workflow Node Taxonomy v0.9

This taxonomy aligns BotverseX workflow nodes with the Qualia Studio categories
used in the Agent Package notes. v0.9 does not implement every Qualia node; it
defines the buckets so the UI and API grow in the same direction.

## Categories

| Category | Qualia Meaning | BotverseX Nodes | Current Status |
| --- | --- | --- | --- |
| `SOURCES` | Load datasets or demonstration sources | `dataset_load`, legacy `robot_connect` | Implemented |
| `TRANSFORMS` | Map/augment/preprocess data | `camera_map`, future `trajectory_noise` | Partial |
| `VLAS` | Train or fine-tune policy models | `finetune_job`, legacy `train` | Implemented path |
| `OUTPUTS` | Export artifacts and monitor jobs | `job_monitor`, legacy `visualize` | Implemented path |
| `SKILLS` | Invoke runtime capabilities | `skill_invoke`, legacy `record`, legacy `deploy` | Partial |
| `GENERATIVE` | World model, diffusion reskin, IDM | future | Not implemented |
| `RL` | Reward model and RL tuning nodes | future | Not implemented |

## v0.9 Main Chain

```text
SOURCES.dataset_load
  -> TRANSFORMS.camera_map
  -> VLAS.finetune_job
  -> OUTPUTS.job_monitor
```

## v0.9 Skill Invocation Chain

```text
SKILLS.skill_invoke
  -> apps/api /api/v1/skills/{skill_id}/run
  -> apps/realtime runtime adapter
```

## UI Rule

The workflow palette should show categories using these names even when only a
subset of nodes exists. Empty future categories may be hidden in production UI,
but the taxonomy remains stable for docs and protocol discussion.
