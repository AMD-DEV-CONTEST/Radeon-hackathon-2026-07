# HighwayEnv Safety DQN on AMD ROCm

## Submission Information

- Track: Track 3 — Physical AI Challenge
- Participant: Lucas Lei
- Application: HighwayEnv Safety DQN on AMD ROCm

## Deliverables

- Source code repository:
  https://github.com/fwr6926996-commits/HighwayEnv-Safety-DQN-ROCm

- Technical report:
  https://github.com/fwr6926996-commits/HighwayEnv-Safety-DQN-ROCm/blob/main/docs/competition_report.md

- Reproducibility README:
  https://github.com/fwr6926996-commits/HighwayEnv-Safety-DQN-ROCm/blob/main/README.md

- Demonstration video:
  https://github.com/fwr6926996-commits/HighwayEnv-Safety-DQN-ROCm/blob/main/outputs/videos/highway_safety_dqn_competition_demo.mp4

## Project Summary

This project develops a safety-oriented Deep Q-Network for autonomous
highway-driving simulation using HighwayEnv, Stable-Baselines3,
PyTorch and AMD ROCm.

Across two independent evaluation seed ranges and 100 episodes per model:

- Mean reward increased from 62.14 to 87.35.
- Collision rate decreased from 80% to 30%.
- Collision-free rate increased from 20% to 70%.
- Mean policy inference latency remained approximately 0.74 ms on an
  AMD Radeon GPU.

Training and evaluation were performed using PyTorch 2.9.1 with
ROCm 7.2.1 and HIP 7.2.

## Contributions

Lucas Lei completed the environment setup, AMD ROCm validation,
baseline reproduction, Safety DQN optimization, evaluation,
reproducibility packaging, technical report and demonstration video.
