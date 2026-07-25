# Radeon-hackathon-2026-07

## how to apply and use AMD Radeon GPU
see [README](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/Radeon-Cloud-User%20Guide/README.md)

## when you submit
**pls fork this repo and open a pull request including the stuff that is mentioned in Rules&conditions of luma page. the title of pull request should be like "Track x, Team name, your application name"**

> [!NOTE]
> All submission materials, project descriptions, and Pull Requests should be submitted in English.

## Modeling simulation

This branch includes a minimal MuJoCo robot body demo.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe simulation\minimal_robot_demo.py
```

## Vision-based runway perception & takeoff control

[`vision/`](vision) is an open release — raw dataset (350 sorties, 156K
labeled frames), open weights (0.48M params), and the control law that turned
them into telemetry-free takeoffs (max centerline deviation 0.55 m). Trained
on ROCm (gfx906), deployed via MIGraphX at 2110 frames/s. Everything is in
[vision/README.md](vision/README.md).

```powershell
pip install numpy opencv-python onnxruntime
python vision\inference.py vision\assets\sample_frames\frame_00.jpg
```
