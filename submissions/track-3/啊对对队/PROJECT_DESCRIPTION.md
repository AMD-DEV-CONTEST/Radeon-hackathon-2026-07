# Project Description

Parcel Sorter ROCm runs parcel pick, lift, transport, and placement in Genesis
on one AMD Radeon GPU with ROCm 7.2.1. The repository exercises two simulated
robot configurations: a fixed single-arm Franka Panda workcell and an
omnidirectional mobile Bi-Franka platform with two Panda arms.

The current submission is an **Agent-conditioned, v21 PI0.5 VLA-routed,
scripted-motion hybrid**. A bounded Responses Agent selects high-level task
intent, the fine-tuned v21 mode head votes on the grasp family, and a
deterministic controller executes continuous motion under workspace, force,
IK, and tool-command gates.

Three delivered hybrid episodes complete grasp, lift, 0.531-0.554 m transport,
supported placement, and release. Placement error is 11.5-25.0 mm, and v21
selects `side_suction` by a 3/3 vote in every delivered episode. Overview and
left-wrist videos are retained for all three runs. The public demonstration is
available on [Bilibili](https://www.bilibili.com/video/BV1Qkun6qEKn/).

Controller attribution is part of the result. The Agent emits no low-level
robot command, v21 continuous actions run in shadow mode with zero applied
physics steps, and scripted control owns continuous motion. Strict pure-VLA
parcel control remains 0/3 and is not combined with the hybrid result.

The repository includes source code, fixed configurations, dataset-generation
and audit scripts, training evidence, dual-view source videos, model hashes,
and reproducible Radeon commands. The complete PI0.5 DROID base and v21 LoRA
adapter are released separately through
[Hugging Face](https://huggingface.co/L2658183739/agengt-vla).
