# Track 3 Submission — Radeon Grasp-BC: Vision-Based Robotic Grasping on AMD ROCm

**Name:** Yogita Singh (solo submission)
**Track:** 3 — Physical AI Challenge

## Links
- Source code: https://github.com/YScoder123too/amd-radeon-grasp-bc
- Demo video: <coming soon>

## Summary
A Franka Panda arm learns to grasp randomly-positioned objects using a privileged-teacher → vision-only-student pipeline: an RL policy first learns with direct access to object position (fast to train), then is distilled into a lightweight CNN-based policy that grasps using only stereo camera images and joint state — the way a real robot would have to operate. Runtime control loop runs closed-loop vision-to-action at ~40Hz, with a scripted grasp-close/lift primitive completing the pick.

## AMD Radeon GPU / ROCm usage
Both the RL teacher training (2048 parallel Genesis environments) and the BC student distillation (300 iterations) run on an AMD Radeon GPU via ROCm/HIP, using Genesis's `gs.amdgpu` backend explicitly (Genesis defaults to a CUDA-only path otherwise). Inference during closed-loop control also runs on the same ROCm backend, averaging 24.55 ms/step (40.7 Hz).

## Results
- Grasp success: 2/3 (67%) across randomized object positions
- Inference latency: 24.55 ms/step, 40.7 Hz control rate
- Full technical report, architecture, setup, and honest limitations: see repo README (linked above)
