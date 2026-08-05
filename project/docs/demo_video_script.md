# Demo Video Script (target: 3.5–4.5 minutes)

Record with any screen recorder (OBS, Loom, QuickTime, Windows Game Bar).
Show your terminal + the MuJoCo viewer/rendered video. Read the script in
your own words — it doesn't need to be verbatim.

---

## 0:00–0:30 — Intro (talking head or voiceover over title slide)

"Hi, we're boost_, and this is RadTrot, our submission for Track 3,
Physical AI, in the AMD AI DevMaster Hackathon.

Most robot locomotion demos only show a robot walking on flat, ideal
ground. Real robots need to handle unexpected pushes and different terrain
— so that's exactly what we built and tested."

## 0:30–1:15 — Problem & Approach (show README / architecture diagram or just talk over code)

"We simulate a Unitree Go1 quadruped in MuJoCo. Locomotion comes from a
Central Pattern Generator producing a trot gait — diagonal leg pairs move
together. We chose this classical approach over training an RL policy from
scratch because it's reliable and let us focus our time on two things:
robustness testing, and GPU-accelerated perception."

[Show gait_controller.py briefly on screen]

## 1:15–2:15 — Live robustness demo (screen record the sim running / play demo.mp4)

"Here's the robot walking. We test it under two conditions: high-friction
terrain like pavement, and low-friction terrain like gravel or wet
surfaces. We also inject random pushes to the torso mid-stride to simulate
real-world disturbances."

[Play your recorded demo.mp4 — show both terrain runs]

"As you can see, the robot absorbs the pushes and keeps walking without
falling over on both terrain types."

[Optionally show the results.json output on screen: distance traveled, max tilt, fell_over: false]

## 2:15–3:15 — AMD Radeon GPU / ROCm usage (screen record terminal)

"For real-world deployment, a robot would need to perceive terrain type
from an onboard camera in real time, not just have it given as a flag like
in our simulation. So we built a small CNN terrain classifier, and we
benchmarked it directly on our AMD Radeon GPU using PyTorch's ROCm
backend, comparing it against CPU inference."

[Run: python3 terrain_classifier.py --benchmark, show the printed output live]

"This shows the GPU gives us the inference speed we'd need to run this
in a real-time control loop — that's the foundation for closing the loop
between perception and gait adaptation."

## 3:15–3:45 — Real-world value & what's next

"Terrain-aware gait adaptation isn't a toy problem — it's a real
deployment challenge for legged robots. Next steps for us would be closing
the loop so the perception model actually adjusts the gait live, and
adding domain randomization for sim-to-real transfer."

## 3:45–4:00 — Close

"Thanks for watching — full code, documentation, and setup instructions
are in our GitHub repo. We're Team boost_, and this is RadTrot."

---

## Recording checklist
- [ ] Record terminal running `run_sim.py --compare --video ../docs/demo.mp4`
- [ ] Record terminal running `terrain_classifier.py --benchmark` (real ROCm output)
- [ ] Optional: record MuJoCo viewer live if you have a display, otherwise use the exported demo.mp4
- [ ] Upload to YouTube (unlisted is fine) or Bilibili, get the shareable link
- [ ] Paste that link into your PR / submission form
