# Track 3 - cybertronic Franka Genesis Study

## English

This submission demonstrates a Franka Panda robot arm following a moving fruit target in Genesis on AMD ROCm. The demo uses inverse kinematics for target tracking and joint PD control for smooth execution. It records an offscreen MP4 video and writes metrics for tracking error, IK latency, runtime, and GPU/backend information.

The enhanced demo extends the baseline into a vision-guided closed-loop controller. Instead of controlling only from the fruit's simulation coordinates, it detects the red fruit in rendered camera frames, estimates image-space error, and converts that observation into visual-servo target corrections for the Franka end effector.

For the final competition demo, the repository also includes a vision-guided apple-to-plate pick-and-place sequence. It detects the red apple, approaches it, closes the gripper, transports the apple to a plate target, and releases it into the plate to provide a clearer manipulation result than tracking alone.

## Submission Info / 提交信息

- Competition: 2026 AMD AI DEVMASTER Hackathon
- Track: Track 3 Physical AI
- Team: cybertronic
- GitHub ID: cybertronic23
- Repository: <https://github.com/cybertronic23/Radeon-hackathon-2026-07>
- Final demo video (YouTube): <https://youtu.be/97QB_RQYRvQ>
- Final demo video (Bilibili): <https://www.bilibili.com/video/BV1fKuJ6GEgE/>
- Main demo: Vision-Guided Franka Apple-to-Plate Pick-and-Place

Recommended Pull Request information:

- PR title: `[Physical AI] cybertronic - Vision-Guided Franka Apple-to-Plate Pick-and-Place`
- PR description should include the project summary, final demo video links, team name, GitHub ID, and reproduction command.

## 1. Project Introduction / 项目简介

### English

This project focuses on a vision-guided robotic manipulation task in Genesis on AMD ROCm. The main competition demo is **Vision-Guided Franka Apple-to-Plate Pick-and-Place**: a Franka Panda robot detects a red apple from rendered camera frames, approaches it, closes the gripper, transports it to a visible plate target, and releases it into the plate.

Problem definition:

- Move from coordinate-scripted manipulation toward perception-driven robot control.
- Demonstrate a reproducible Physical AI pipeline on AMD Radeon GPU and ROCm.
- Produce a clear task-level video, not only a tracking visualization.

Solution:

- Genesis simulation with Franka Panda.
- Lightweight red-object visual detection from camera frames.
- Stage-based manipulation policy: detect, approach, grasp, lift, transport, lower, release.
- Genesis inverse kinematics and joint PD control.
- Annotated MP4 output plus JSON metrics.

Core metrics:

- Detection rate
- Grasp success
- Place success
- Apple lift height
- Final place error
- IK latency
- Runtime and GPU/backend information

Technology stack:

- AMD Radeon GPU
- ROCm
- PyTorch ROCm build
- Genesis 1.3.1
- NumPy
- imageio / imageio-ffmpeg

### 中文

本项目聚焦于 AMD ROCm + Genesis 环境下的视觉引导机械臂操作任务。最终推荐参赛 Demo 是 **Vision-Guided Franka Apple-to-Plate Pick-and-Place**：Franka Panda 机械臂从相机渲染画面中检测红色苹果，靠近目标，闭合夹爪，将苹果搬运到可见盘子目标区域，并释放到盘子中。

问题定义：

- 从依赖仿真真值坐标的脚本控制，升级到基于相机感知的机器人控制。
- 展示可复现的 AMD Radeon GPU / ROCm Physical AI 流程。
- 生成具有明确任务完成感的机械臂操作视频，而不只是跟随演示。

解决方案：

- 使用 Genesis 构建 Franka Panda 仿真场景。
- 使用轻量红色目标检测从相机帧中定位苹果。
- 使用阶段式操作策略：检测、靠近、抓取、抬起、搬运、下降、释放。
- 使用 Genesis IK 和关节 PD 控制执行轨迹。
- 输出带视觉标注的视频和 JSON 指标。

核心指标：

- 目标检测成功率
- 抓取成功状态
- 放置成功状态
- 苹果抬升高度
- 最终放置误差
- IK 求解延迟
- 运行时间和 GPU/后端信息

技术栈：

- AMD Radeon GPU
- ROCm
- PyTorch ROCm build
- Genesis 1.3.1
- NumPy
- imageio / imageio-ffmpeg

## 2. Development Process / 开发过程

### English

Key decisions:

- The original baseline used known simulation coordinates for fruit following. For the competition version, the project adds camera-based target detection to make the control loop perception-driven.
- A lightweight threshold detector is used instead of a trained model. This keeps the demo reproducible under a short deadline and avoids large model weights.
- The final demo uses apple-to-plate pick-and-place instead of tracking only. This gives the video a clearer task objective and a visible success condition.
- The manipulation object is kinematically attached after grasp in the competition demo. This avoids unstable contact/friction tuning while preserving a clear pick, transport, and place behavior.

Challenges and solutions:

- Genesis camera return formats can vary by version, so `vision_tracking.py` normalizes ndarray, tuple/list, dict, and tensor-like frames.
- Generated videos and full per-frame metrics can be large, so they are written to `outputs/`, which is ignored by Git.
- ROCm PyTorch installation is environment-sensitive, so the README recommends reusing the cloud image's working Genesis/ROCm environment.

Future improvements:

- Add model-based object detection.
- Add multi-object sorting.
- Export LeRobot-style datasets.
- Replace kinematic attachment with stable contact-rich grasping.
- Add sim-to-real calibration.

### 中文

关键决策：

- 原始 baseline 使用仿真真值坐标进行水果跟随。参赛版本加入相机目标检测，让控制链路从脚本坐标控制升级为感知驱动控制。
- 视觉模块采用轻量阈值检测，而不是训练模型。这样不需要大模型权重，便于在比赛 deadline 前稳定复现。
- 最终 Demo 选择 apple-to-plate pick-and-place，而不是只做跟随或只抓起。这样视频有更明确的任务目标和成功结果。
- 参赛 Demo 在抓取后使用运动学附着方式让苹果跟随末端执行器，避免真实接触/摩擦调参带来的不稳定，同时保留抓取、搬运、放置的完整任务表达。

遇到的困难与解决：

- Genesis 相机 API 返回格式可能随版本变化，因此 `vision_tracking.py` 对 ndarray、tuple/list、dict 和 tensor-like frame 都做了兼容。
- 视频和逐帧指标可能较大，因此统一输出到被 Git 忽略的 `outputs/` 目录。
- ROCm PyTorch 安装对环境敏感，因此 README 推荐复用云服务器中已验证可运行的 Genesis/ROCm 环境。

后续优化方向：

- 加入模型式目标检测。
- 扩展为多物体分拣。
- 导出 LeRobot 风格数据集。
- 将运动学附着替换为稳定的接触抓取。
- 加入 sim-to-real 标定。

## 3. Code Sources / 代码来源说明

### English

Based on:

- Genesis official examples and assets, especially the Franka Panda MJCF asset `xml/franka_emika_panda/panda.xml`.
- The open-source PhysicalAI ROCm Quickstart repository: <https://github.com/JasonZhw/PhysicalAI-ROCm-Quickstart.git>. The original Franka fruit-following demo is used as a baseline reference and starting point.

Original work in this submission:

- `src/vision_tracking.py`: camera frame normalization, red apple detection, detection metrics, and overlay rendering.
- `src/franka_vision_servo.py`: vision-guided tracking experiment.
- `src/franka_vision_pick.py`: vision-guided pick-and-lift sequence.
- `src/franka_vision_pick_place.py`: apple-to-plate pick-and-place sequence.
- `configs/`: reproducible task and detector configuration.
- `docs/`: implementation notes and extension planning.

Modified from baseline:

- The original `scripts/franka_fruit_follow.py` entry point is preserved as a compatibility launcher.
- The baseline implementation is kept in `src/franka_fruit_follow.py`.
- New scripts extend the baseline with perception, task phases, success metrics, and annotated videos.
- The competition submission changes the task objective from coordinate-based fruit following to vision-guided apple pick-and-place into a plate.

Originality and compliance statement:

- This submission is not a direct fork-only submission. The competition work adds new vision-guided tracking, pick-and-lift, and apple-to-plate pick-and-place modules on top of the baseline learning demo.
- The upstream quickstart is cited explicitly to keep code provenance transparent. The submitted value is the new perception-control pipeline, task logic, reproducible configuration, metrics, documentation, and final demonstration video.
- No external model weights are included.
- No private datasets are included. Generated videos and full per-frame metrics are written to `outputs/` and intentionally ignored by Git.
- No API keys, passwords, or private credentials are required by the project code.
- The lightweight summary JSON files in `results/` are generated from local/cloud runs and are included for reproducibility and result verification.

### 中文

基于的开源/参考项目：

- Genesis 官方示例与资产，尤其是 Franka Panda MJCF 资产 `xml/franka_emika_panda/panda.xml`。
- 开源 PhysicalAI ROCm Quickstart 仓库：<https://github.com/JasonZhw/PhysicalAI-ROCm-Quickstart.git>。其中原始 Franka fruit-following Demo 被用作 baseline 参考和起点。

本提交中的原创部分：

- `src/vision_tracking.py`：相机帧归一化、红色苹果检测、检测指标和视频标注。
- `src/franka_vision_servo.py`：视觉引导跟随实验。
- `src/franka_vision_pick.py`：视觉引导抓取并抬起流程。
- `src/franka_vision_pick_place.py`：苹果放入盘子的 pick-and-place 流程。
- `configs/`：可复现任务参数和检测器配置。
- `docs/`：实现说明和扩展规划。

相对 baseline 的修改：

- 保留原 `scripts/franka_fruit_follow.py` 作为兼容入口。
- baseline 主实现放在 `src/franka_fruit_follow.py`。
- 新增脚本扩展了视觉感知、任务阶段、成功指标和标注视频输出。
- 参赛提交将任务目标从基于坐标的水果跟随，扩展为视觉引导的苹果抓取并放入盘子。

原创性与合规声明：

- 本提交不是仅直接 fork 后无修改的项目。参赛工作在 baseline 学习 Demo 基础上新增了视觉引导跟随、抓取抬升和苹果放入盘子的 pick-and-place 模块。
- README 中明确引用上游 quickstart，是为了让代码来源透明可查。参赛价值主要体现在新增的感知控制链路、任务逻辑、可复现配置、指标、文档和最终演示视频。
- 仓库中不包含外部模型权重。
- 仓库中不包含私有数据集。生成视频和完整逐帧指标统一写入 `outputs/`，并被 Git 忽略。
- 项目代码不需要 API Key、密码或私有凭证。
- `results/` 下提交的轻量 summary JSON 来自本地/云服务器运行结果，用于复现和结果核对。

## 4. Team Contributions / 团队分工

### English

Team: cybertronic.

GitHub ID: cybertronic23.

- Project design: selected the vision-guided manipulation direction and scoped it for deadline-safe delivery.
- Simulation and control: implemented Franka task phases, IK targets, gripper commands, and apple-to-plate placement logic.
- Perception: implemented lightweight red apple detection and annotated video overlays.
- Evaluation: added JSON metrics for detection, grasp, placement, IK latency, runtime, and GPU/backend information.
- Documentation: organized the repository structure, bilingual README, implementation notes, and reproducible cloud-server commands.

### 中文

团队：cybertronic。

GitHub ID：cybertronic23。

- 项目设计：选择视觉引导机械臂操作方向，并将范围控制在 deadline 前可稳定交付。
- 仿真与控制：实现 Franka 任务阶段、IK 目标、夹爪控制和苹果放入盘子的逻辑。
- 视觉感知：实现轻量红色苹果检测和标注视频叠加。
- 实验评估：加入检测、抓取、放置、IK 延迟、运行时间和 GPU/后端信息等 JSON 指标。
- 文档整理：组织规范仓库结构、中英双语 README、实现说明和云服务器复现命令。

## 5. Installation and Run / 安装与运行

### Repository Structure

```text
.
├── README.md
├── LICENSE
├── requirements.txt
├── src/
│   ├── franka_fruit_follow.py
│   ├── franka_vision_pick.py
│   ├── franka_vision_pick_place.py
│   ├── franka_vision_servo.py
│   └── vision_tracking.py
├── scripts/
│   ├── franka_fruit_follow.py
│   ├── franka_vision_pick.py
│   ├── franka_vision_pick_place.py
│   └── franka_vision_servo.py
├── configs/
│   ├── franka_fruit_follow.json
│   ├── franka_vision_pick.json
│   ├── franka_vision_pick_place.json
│   └── franka_vision_tracking.json
├── data/
│   └── README.md
├── docs/
│   ├── extension_plan.md
│   └── implementation.md
├── results/
│   ├── franka_fruit_follow.json
│   ├── franka_vision_pick_place_summary.json
│   ├── franka_vision_pick_summary.json
│   └── franka_vision_servo_summary.json
└── videos/
    └── README.md
```

### Entry Points vs Implementation / 入口脚本与核心实现

The project intentionally keeps both `scripts/` and `src/`:

- `scripts/` contains short command-line launchers. These are the files evaluators should run directly, for example `python scripts/franka_vision_pick_place.py`.
- `src/` contains the actual implementation. This includes Genesis scene setup, camera rendering, red apple detection, inverse kinematics, joint PD control, task phases, video recording, and metrics export.
- Some files share the same name, such as `scripts/franka_vision_pick_place.py` and `src/franka_vision_pick_place.py`. The `scripts/` file imports and calls `main()` from the matching `src/` module. This keeps the run commands simple while keeping reusable logic in `src/`.

In short, use `scripts/` to reproduce the demos and inspect `src/` to review or modify the implementation.

本项目有意同时保留 `scripts/` 和 `src/`：

- `scripts/` 存放很短的命令行启动脚本。评委复现时应直接运行这里的入口，例如 `python scripts/franka_vision_pick_place.py`。
- `src/` 存放真正的核心实现，包括 Genesis 场景构建、相机渲染、红色苹果检测、逆运动学、关节 PD 控制、任务阶段、视频录制和指标导出。
- 部分文件同名，例如 `scripts/franka_vision_pick_place.py` 和 `src/franka_vision_pick_place.py`。其中 `scripts/` 下的文件只负责导入并调用 `src/` 中对应模块的 `main()`，这样既保证运行命令简单，也让核心逻辑保持可复用和可维护。

简单来说：复现实验运行 `scripts/`，查看或修改实现看 `src/`。

### Environment / 环境要求

Use a Linux AMD ROCm environment with a ROCm-enabled PyTorch build. This project
does not pin `torch` in `requirements.txt`, because installing a generic PyPI
Torch wheel can accidentally replace the ROCm build with a CPU/CUDA build. If
PyTorch is not already installed in the cloud image, install the ROCm build that
matches the server by using the official PyTorch selector:
<https://docs.pytorch.org/get-started/locally/>.

After the ROCm PyTorch environment is ready, install the project dependencies:

```bash
pip install -r requirements.txt
```

The validated environment used for the included metrics was:

| Component | Validated version |
| --- | --- |
| OS | Ubuntu 24.04 container environment |
| Python | 3.12 |
| ROCm | 7.2.1 |
| PyTorch | 2.9.1 + ROCm 7.2.1 |
| Triton | 3.5.1 + ROCm 7.2.1 |
| Genesis | 1.3.1 |
| GPU | AMD Radeon Graphics |

Check AMD GPU and ROCm first:

```bash
rocm-smi
# or
amd-smi
```

On Radeon Cloud, check whether the image provides prebuilt ROCm PyTorch wheels:

```bash
ls -lh /torch-*.whl /triton-*.whl
```

If those wheel files exist, prefer installing them because they are built for
the current Radeon Cloud image. The filenames below match the validated
environment. If the platform filenames differ, replace them with the actual
files printed by `ls -lh /torch-*.whl /triton-*.whl`.

```bash
python -m pip install \
  /triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl \
  /torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
```

Verify the runtime before running the demo:

```bash
python - <<'PY'
import torch
import genesis as gs

print("torch:", torch.__version__)
print("hip:", torch.version.hip)
print("gpu_available:", torch.cuda.is_available())
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
print("genesis:", getattr(gs, "__version__", "unknown"))

if torch.cuda.is_available():
    x = torch.randn(1024, 1024, device="cuda")
    y = x @ x
    print("ROCm matrix multiplication:", y.shape, y.device)
PY
```

Expected: `torch.version.hip` is not `None`, `gpu_available` is `True`, and
Genesis imports successfully. ROCm PyTorch still uses the `torch.cuda` and
`cuda:0` API names, but it runs on AMD ROCm/HIP underneath.

Genesis AMD GPU smoke test:

```bash
python - <<'PY'
import genesis as gs

backend = gs.amdgpu if hasattr(gs, "amdgpu") else gs.gpu
gs.init(backend=backend)

scene = gs.Scene(show_viewer=False)
scene.add_entity(gs.morphs.Plane())
scene.add_entity(gs.morphs.Box(size=(0.1, 0.1, 0.1), pos=(0.0, 0.0, 0.2)))
scene.build()

for _ in range(20):
    scene.step()

print("Genesis AMD GPU smoke test: OK")
PY
```

Expected logs should include an AMD GPU backend such as `gs.amdgpu` and
`Genesis AMD GPU smoke test: OK`. The first Genesis scene build may be slower
because kernels are compiled and cached.

### Run / 运行命令

From this project folder:

```bash
python scripts/franka_fruit_follow.py
```

Run the vision-guided enhanced demo:

```bash
python scripts/franka_vision_servo.py
```

Run the competition-oriented pick-and-lift demo:

```bash
python scripts/franka_vision_pick.py
```

Run the final apple-to-plate pick-and-place demo:

```bash
python scripts/franka_vision_pick_place.py
```

Optional smoke test:

```bash
python scripts/franka_fruit_follow.py \
  --frames 60 \
  --video outputs/videos/franka_fruit_follow_smoke.mp4
```

Vision-guided smoke test:

```bash
python scripts/franka_vision_servo.py \
  --frames 60 \
  --video outputs/videos/franka_vision_servo_smoke.mp4 \
  --annotated-video outputs/videos/franka_vision_servo_smoke_annotated.mp4
```

Pick-and-lift smoke test:

```bash
python scripts/franka_vision_pick.py \
  --frames 120 \
  --video outputs/videos/franka_vision_pick_smoke.mp4 \
  --annotated-video outputs/videos/franka_vision_pick_smoke_annotated.mp4
```

Apple-to-plate smoke test:

```bash
python scripts/franka_vision_pick_place.py \
  --frames 180 \
  --video outputs/videos/franka_vision_pick_place_smoke.mp4 \
  --annotated-video outputs/videos/franka_vision_pick_place_smoke_annotated.mp4
```

Compare with a coordinate-control baseline using the same enhanced script:

```bash
python scripts/franka_vision_servo.py --mode baseline
```

Generated outputs are written to `outputs/`, which is intentionally ignored by Git.

### Metrics / 指标输出

The vision-guided demo writes:

- `outputs/metrics/franka_vision_servo.json`: full per-frame metrics
- `results/franka_vision_servo_summary.json`: lightweight summary suitable for committing
- `outputs/metrics/franka_vision_pick.json`: full pick-and-lift metrics
- `results/franka_vision_pick_summary.json`: lightweight pick-and-lift summary suitable for committing
- `outputs/metrics/franka_vision_pick_place.json`: full apple-to-plate metrics
- `results/franka_vision_pick_place_summary.json`: lightweight apple-to-plate summary suitable for committing

Important metrics include detection rate, mean image-space error, end-effector tracking error, IK latency, runtime, GPU information, and annotated-video path.

### Cloud Server Reproduction / 云服务器复现

Use these steps on the AMD ROCm/Genesis cloud server.

```bash
cd /workspace/persistent
git clone git@github.com:cybertronic23/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/submissions/track3-cybertronic-franka-genesis-study
```

If the repository already exists:

```bash
cd /workspace/persistent/Radeon-hackathon-2026-07
git pull
cd submissions/track3-cybertronic-franka-genesis-study
```

Preferred path: activate the cloud image's existing Genesis/ROCm environment,
then install the small project-level dependencies:

```bash
pip install -r requirements.txt
```

If you need to create an isolated virtual environment, first make sure the
matching ROCm PyTorch package is installed inside that environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
# Install the ROCm PyTorch build that matches the server from the official
# PyTorch selector if torch is not already available in this venv.
pip install -r requirements.txt
```

If `import torch` fails, install the ROCm PyTorch package that matches the cloud
server ROCm version from the official PyTorch installation selector, then rerun
`pip install -r requirements.txt`.

On Radeon Cloud, the preferred installation path is:

```bash
ls -lh /torch-*.whl /triton-*.whl
python -m pip install \
  /triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl \
  /torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
python -m pip install -r requirements.txt
```

If the wheel filenames differ, use the actual filenames shown by `ls`.
Installing Genesis may take several minutes because it includes rendering,
mesh, and VTK-related dependencies.

Check the environment:

```bash
python - <<'PY'
import torch
import genesis as gs

print("torch:", torch.__version__)
print("hip:", torch.version.hip)
print("gpu_available:", torch.cuda.is_available())
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
print("genesis:", getattr(gs, "__version__", "unknown"))

if torch.cuda.is_available():
    x = torch.randn(1024, 1024, device="cuda")
    y = x @ x
    print("ROCm matrix multiplication:", y.shape, y.device)
PY
```

Run a Genesis AMD GPU smoke test:

```bash
python - <<'PY'
import genesis as gs

backend = gs.amdgpu if hasattr(gs, "amdgpu") else gs.gpu
gs.init(backend=backend)

scene = gs.Scene(show_viewer=False)
scene.add_entity(gs.morphs.Plane())
scene.add_entity(gs.morphs.Box(size=(0.1, 0.1, 0.1), pos=(0.0, 0.0, 0.2)))
scene.build()

for _ in range(20):
    scene.step()

print("Genesis AMD GPU smoke test: OK")
PY
```

Run a quick baseline smoke test:

```bash
python scripts/franka_fruit_follow.py \
  --frames 60 \
  --video outputs/videos/franka_fruit_follow_smoke.mp4
```

Run a quick vision-guided smoke test:

```bash
python scripts/franka_vision_servo.py \
  --frames 60 \
  --video outputs/videos/franka_vision_servo_smoke.mp4 \
  --annotated-video outputs/videos/franka_vision_servo_smoke_annotated.mp4
```

Run the final 300-frame vision-guided demo:

```bash
python scripts/franka_vision_servo.py
```

Run the final 300-frame pick-and-lift demo:

```bash
python scripts/franka_vision_pick.py
```

Run the final apple-to-plate pick-and-place demo, recommended as the main competition video:

```bash
python scripts/franka_vision_pick_place.py
```

Recommended one-command reproduction for the submitted result:

```bash
python scripts/franka_vision_pick_place.py \
  --config configs/franka_vision_pick_place.json \
  --video outputs/videos/franka_vision_pick_place.mp4 \
  --annotated-video outputs/videos/franka_vision_pick_place_annotated.mp4 \
  --metrics outputs/metrics/franka_vision_pick_place.json \
  --summary results/franka_vision_pick_place_summary.json
```

Expected validation outputs:

- `outputs/videos/franka_vision_pick_place_annotated.mp4`: annotated simulation video.
- `results/franka_vision_pick_place_summary.json`: lightweight result summary.
- Key expected metrics from the validated run:
  - `detection_rate`: `1.0`
  - `grasp_success`: `true`
  - `place_success`: `true`
  - `fruit_lift_delta_mm`: about `242.8`
  - `final_place_error_mm`: `0.0`

Optional comparison runs:

```bash
python scripts/franka_vision_servo.py --mode baseline \
  --video outputs/videos/franka_vision_baseline.mp4 \
  --annotated-video outputs/videos/franka_vision_baseline_annotated.mp4 \
  --metrics outputs/metrics/franka_vision_baseline.json \
  --summary results/franka_vision_baseline_summary.json

python scripts/franka_vision_servo.py --mode vision \
  --video outputs/videos/franka_vision_raw.mp4 \
  --annotated-video outputs/videos/franka_vision_raw_annotated.mp4 \
  --metrics outputs/metrics/franka_vision_raw.json \
  --summary results/franka_vision_raw_summary.json

python scripts/franka_vision_servo.py --mode vision_smooth \
  --video outputs/videos/franka_vision_smooth.mp4 \
  --annotated-video outputs/videos/franka_vision_smooth_annotated.mp4 \
  --metrics outputs/metrics/franka_vision_smooth.json \
  --summary results/franka_vision_smooth_summary.json
```

Check generated files:

```bash
find outputs -maxdepth 3 -type f
find results -maxdepth 1 -type f
```

Commit only lightweight source, docs, configs, and summary JSON files. Do not commit `outputs/` or MP4 files.

Success criteria:

- Environment check shows `torch.version.hip` is not `None`.
- `torch.cuda.is_available()` is `True`.
- Genesis initializes with AMD GPU backend, normally `gs.amdgpu`.
- The smoke test creates an MP4 under `outputs/videos/`.
- The final pick-and-place run creates `outputs/videos/franka_vision_pick_place_annotated.mp4`.
- `results/franka_vision_pick_place_summary.json` contains detection, grasp, place, IK latency, runtime, and AMD GPU information.
- The run finishes without a Python traceback.

Common non-fatal Genesis warnings:

- `Approximating tendon by joint actuator`
- `Neutral robot position exceeds joint limits`
- `Constraint solver time constant`
- Neutral configuration self-collision filtering

If the script still generates the video and JSON metrics, these warnings are
usually not fatal for this demo.

Troubleshooting:

- If `torch.cuda.is_available()` is `False`, a CPU/CUDA PyTorch wheel may have
  replaced the ROCm build. Reinstall the Radeon Cloud `/torch-*.whl` and
  `/triton-*.whl` files or use the official PyTorch ROCm selector.
- If pip installation appears stuck while installing Genesis, wait and check
  `ps aux | grep -E '[p]ip|[p]ython'`; Genesis has many rendering and mesh
  dependencies.
- Keep the repository under `/workspace/persistent` on Radeon Cloud so files are
  not lost when the instance is destroyed.

### Demo Video / 演示视频

Do not commit large MP4 files to GitHub. The final uploaded demo video is:

- YouTube: <https://youtu.be/97QB_RQYRvQ>
- Bilibili: <https://www.bilibili.com/video/BV1fKuJ6GEgE/>

The same link is also recorded in `videos/README.md`.

Before final submission:

- Upload the final video to YouTube or Bilibili. Done:
  - YouTube: <https://youtu.be/97QB_RQYRvQ>
  - Bilibili: <https://www.bilibili.com/video/BV1fKuJ6GEgE/>
- Keep the duration under 3 minutes.
- Add Chinese and English subtitles.
- Make the link public.
- Put the final public link in `videos/README.md`.

## 中文

本项目展示了 Franka Panda 机械臂在 AMD ROCm 环境下使用 Genesis 进行水果目标跟随。Demo 通过逆运动学计算末端执行器目标姿态，并使用关节 PD 控制完成平滑跟随。程序会生成离屏录制视频，并输出跟踪误差、IK 耗时、运行时间和 GPU/后端信息等指标。

增强版在 baseline 基础上加入视觉闭环：程序从 Genesis 相机渲染图像中检测红色水果，计算图像空间误差，再将视觉误差转换成机械臂末端目标修正量，实现基于感知的视觉伺服跟随。

为了让比赛视频更有任务完成感，项目还新增了视觉引导 apple-to-plate pick-and-place 演示：检测红色苹果后，机械臂执行靠近、闭合夹爪、搬运到盘子、放入盘子的完整流程。这个版本比单纯跟随或只抓起更适合作为最终展示视频。

### 仓库结构

```text
.
├── README.md              # 中英双语说明
├── LICENSE                # MIT 协议
├── requirements.txt       # Python 依赖
├── src/                   # 源代码
├── scripts/               # 兼容启动脚本
├── configs/               # 默认运行参数
├── data/                  # 数据说明或生成脚本
├── docs/                  # 补充技术文档
├── results/               # 轻量指标文件
└── videos/                # 视频链接说明，不提交大视频
```

### 运行方式

请使用 Linux AMD ROCm 环境，并确保安装的是支持 ROCm 的 PyTorch。本项目没有在
`requirements.txt` 中固定 `torch`，原因是直接安装通用 PyPI Torch 可能会把云服务器
中可用的 ROCm 版 PyTorch 替换成 CPU/CUDA 版。如果云镜像中没有 PyTorch，请根据
官方 PyTorch 安装选择器选择和服务器 ROCm 版本匹配的命令：
<https://docs.pytorch.org/get-started/locally/>。

确认 ROCm PyTorch 可用后，再安装项目依赖：

```bash
pip install -r requirements.txt
```

本次结果验证环境：

| 组件 | 验证版本 |
| --- | --- |
| 操作系统 | Ubuntu 24.04 容器环境 |
| Python | 3.12 |
| ROCm | 7.2.1 |
| PyTorch | 2.9.1 + ROCm 7.2.1 |
| Triton | 3.5.1 + ROCm 7.2.1 |
| Genesis | 1.3.1 |
| GPU | AMD Radeon Graphics |

先检查 AMD GPU 和 ROCm：

```bash
rocm-smi
# 或
amd-smi
```

在 Radeon Cloud 上，先检查镜像是否提供预编译 ROCm PyTorch wheel：

```bash
ls -lh /torch-*.whl /triton-*.whl
```

如果这些 wheel 存在，优先安装镜像自带版本。下面文件名对应本项目验证环境；
如果平台文件名变化，请用 `ls -lh /torch-*.whl /triton-*.whl` 输出的实际文件名替换。

```bash
python -m pip install \
  /triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl \
  /torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
```

运行前建议先检查环境：

```bash
python - <<'PY'
import torch
import genesis as gs

print("torch:", torch.__version__)
print("hip:", torch.version.hip)
print("gpu_available:", torch.cuda.is_available())
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
print("genesis:", getattr(gs, "__version__", "unknown"))

if torch.cuda.is_available():
    x = torch.randn(1024, 1024, device="cuda")
    y = x @ x
    print("ROCm matrix multiplication:", y.shape, y.device)
PY
```

预期结果：`torch.version.hip` 不是 `None`，`gpu_available` 为 `True`，且 Genesis 可以成功导入。ROCm 版 PyTorch 仍然使用 `torch.cuda` 和 `cuda:0` 接口名，但底层实际运行的是 AMD ROCm/HIP。

Genesis AMD GPU 最小测试：

```bash
python - <<'PY'
import genesis as gs

backend = gs.amdgpu if hasattr(gs, "amdgpu") else gs.gpu
gs.init(backend=backend)

scene = gs.Scene(show_viewer=False)
scene.add_entity(gs.morphs.Plane())
scene.add_entity(gs.morphs.Box(size=(0.1, 0.1, 0.1), pos=(0.0, 0.0, 0.2)))
scene.build()

for _ in range(20):
    scene.step()

print("Genesis AMD GPU smoke test: OK")
PY
```

关键日志应包含 AMD GPU backend，例如 `gs.amdgpu`，以及 `Genesis AMD GPU smoke test: OK`。第一次构建 Genesis 场景时会编译并缓存内核，因此可能比后续运行慢。

运行完整 Demo：

```bash
python scripts/franka_fruit_follow.py
```

运行视觉闭环增强 Demo：

```bash
python scripts/franka_vision_servo.py
```

运行比赛展示用 pick-and-lift Demo：

```bash
python scripts/franka_vision_pick.py
```

运行最终推荐的 apple-to-plate pick-and-place Demo：

```bash
python scripts/franka_vision_pick_place.py
```

快速 smoke test：

```bash
python scripts/franka_fruit_follow.py \
  --frames 60 \
  --video outputs/videos/franka_fruit_follow_smoke.mp4
```

视觉闭环快速测试：

```bash
python scripts/franka_vision_servo.py \
  --frames 60 \
  --video outputs/videos/franka_vision_servo_smoke.mp4 \
  --annotated-video outputs/videos/franka_vision_servo_smoke_annotated.mp4
```

pick-and-lift 快速测试：

```bash
python scripts/franka_vision_pick.py \
  --frames 120 \
  --video outputs/videos/franka_vision_pick_smoke.mp4 \
  --annotated-video outputs/videos/franka_vision_pick_smoke_annotated.mp4
```

apple-to-plate 快速测试：

```bash
python scripts/franka_vision_pick_place.py \
  --frames 180 \
  --video outputs/videos/franka_vision_pick_place_smoke.mp4 \
  --annotated-video outputs/videos/franka_vision_pick_place_smoke_annotated.mp4
```

同一增强脚本也支持 baseline 对比：

```bash
python scripts/franka_vision_servo.py --mode baseline
```

生成的视频和运行指标位于 `outputs/`，该目录已被 `.gitignore` 忽略，避免把大文件直接提交到 GitHub。

视觉闭环 Demo 会额外输出：

- `outputs/metrics/franka_vision_servo.json`：完整逐帧指标
- `results/franka_vision_servo_summary.json`：轻量汇总指标
- `outputs/metrics/franka_vision_pick.json`：pick-and-lift 完整逐帧指标
- `results/franka_vision_pick_summary.json`：pick-and-lift 轻量汇总指标
- `outputs/metrics/franka_vision_pick_place.json`：apple-to-plate 完整逐帧指标
- `results/franka_vision_pick_place_summary.json`：apple-to-plate 轻量汇总指标

### 云服务器部署与比赛复现步骤

在 AMD ROCm/Genesis 云服务器上执行以下步骤。

如果服务器上还没有仓库：

```bash
cd /workspace/persistent
git clone git@github.com:cybertronic23/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/submissions/track3-cybertronic-franka-genesis-study
```

如果服务器上已经有仓库：

```bash
cd /workspace/persistent/Radeon-hackathon-2026-07
git pull
cd submissions/track3-cybertronic-franka-genesis-study
```

推荐路径：优先激活云服务器镜像中已经可用的 Genesis/ROCm 环境，然后安装项目级依赖：

```bash
pip install -r requirements.txt
```

如果确实需要创建独立虚拟环境，请先确保该环境里安装了和服务器 ROCm 版本匹配的 PyTorch：

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
# 如果当前 venv 中还没有 torch，请先根据官方 PyTorch selector 安装匹配的 ROCm PyTorch。
pip install -r requirements.txt
```

如果 `import torch` 报错，请先通过官方 PyTorch 安装选择器安装与云服务器 ROCm 版本匹配的
ROCm PyTorch，再重新执行 `pip install -r requirements.txt`。

在 Radeon Cloud 上，推荐安装方式是：

```bash
ls -lh /torch-*.whl /triton-*.whl
python -m pip install \
  /triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl \
  /torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
python -m pip install -r requirements.txt
```

如果 wheel 文件名不同，请使用 `ls` 看到的实际文件名。Genesis 依赖渲染、网格和 VTK 相关包，第一次安装可能需要数分钟。

检查环境：

```bash
python - <<'PY'
import torch
import genesis as gs

print("torch:", torch.__version__)
print("hip:", torch.version.hip)
print("gpu_available:", torch.cuda.is_available())
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
print("genesis:", getattr(gs, "__version__", "unknown"))

if torch.cuda.is_available():
    x = torch.randn(1024, 1024, device="cuda")
    y = x @ x
    print("ROCm matrix multiplication:", y.shape, y.device)
PY
```

运行 Genesis AMD GPU 最小测试：

```bash
python - <<'PY'
import genesis as gs

backend = gs.amdgpu if hasattr(gs, "amdgpu") else gs.gpu
gs.init(backend=backend)

scene = gs.Scene(show_viewer=False)
scene.add_entity(gs.morphs.Plane())
scene.add_entity(gs.morphs.Box(size=(0.1, 0.1, 0.1), pos=(0.0, 0.0, 0.2)))
scene.build()

for _ in range(20):
    scene.step()

print("Genesis AMD GPU smoke test: OK")
PY
```

先跑 baseline 快速测试：

```bash
python scripts/franka_fruit_follow.py \
  --frames 60 \
  --video outputs/videos/franka_fruit_follow_smoke.mp4
```

再跑视觉闭环快速测试：

```bash
python scripts/franka_vision_servo.py \
  --frames 60 \
  --video outputs/videos/franka_vision_servo_smoke.mp4 \
  --annotated-video outputs/videos/franka_vision_servo_smoke_annotated.mp4
```

如果 smoke test 正常，运行最终 300 帧视觉闭环 Demo：

```bash
python scripts/franka_vision_servo.py
```

运行最终 300 帧 pick-and-lift Demo，建议作为比赛主视频：

```bash
python scripts/franka_vision_pick.py
```

运行最终 apple-to-plate pick-and-place Demo，推荐作为比赛主视频：

```bash
python scripts/franka_vision_pick_place.py
```

推荐用于复现提交结果的一条主命令：

```bash
python scripts/franka_vision_pick_place.py \
  --config configs/franka_vision_pick_place.json \
  --video outputs/videos/franka_vision_pick_place.mp4 \
  --annotated-video outputs/videos/franka_vision_pick_place_annotated.mp4 \
  --metrics outputs/metrics/franka_vision_pick_place.json \
  --summary results/franka_vision_pick_place_summary.json
```

预期验证输出：

- `outputs/videos/franka_vision_pick_place_annotated.mp4`：带标注的仿真视频。
- `results/franka_vision_pick_place_summary.json`：轻量结果汇总。
- 已验证运行中的关键指标：
  - `detection_rate`: `1.0`
  - `grasp_success`: `true`
  - `place_success`: `true`
  - `fruit_lift_delta_mm`: 约 `242.8`
  - `final_place_error_mm`: `0.0`

可选：运行 baseline、原始视觉控制和平滑视觉控制三组对比实验：

```bash
python scripts/franka_vision_servo.py --mode baseline \
  --video outputs/videos/franka_vision_baseline.mp4 \
  --annotated-video outputs/videos/franka_vision_baseline_annotated.mp4 \
  --metrics outputs/metrics/franka_vision_baseline.json \
  --summary results/franka_vision_baseline_summary.json

python scripts/franka_vision_servo.py --mode vision \
  --video outputs/videos/franka_vision_raw.mp4 \
  --annotated-video outputs/videos/franka_vision_raw_annotated.mp4 \
  --metrics outputs/metrics/franka_vision_raw.json \
  --summary results/franka_vision_raw_summary.json

python scripts/franka_vision_servo.py --mode vision_smooth \
  --video outputs/videos/franka_vision_smooth.mp4 \
  --annotated-video outputs/videos/franka_vision_smooth_annotated.mp4 \
  --metrics outputs/metrics/franka_vision_smooth.json \
  --summary results/franka_vision_smooth_summary.json
```

查看生成物：

```bash
find outputs -maxdepth 3 -type f
find results -maxdepth 1 -type f
```

提交时只提交源码、配置、文档和 `results/` 下的轻量 summary JSON。不要提交 `outputs/` 目录和 MP4 大文件。

成功标准：

- 环境检查显示 `torch.version.hip` 不是 `None`。
- `torch.cuda.is_available()` 返回 `True`。
- Genesis 使用 AMD GPU backend 初始化，通常为 `gs.amdgpu`。
- smoke test 成功在 `outputs/videos/` 下生成 MP4。
- 最终 pick-and-place 运行生成 `outputs/videos/franka_vision_pick_place_annotated.mp4`。
- `results/franka_vision_pick_place_summary.json` 包含检测、抓取、放置、IK 延迟、运行时间和 AMD GPU 信息。
- 运行结束时没有 Python traceback。

Genesis 可能输出以下非致命警告：

- `Approximating tendon by joint actuator`
- `Neutral robot position exceeds joint limits`
- `Constraint solver time constant`
- neutral configuration self-collision filtering

如果程序仍然成功生成视频和 JSON 指标，这些通常不是本 Demo 的致命错误。

常见问题：

- 如果 `torch.cuda.is_available()` 返回 `False`，通常是 CPU/CUDA 版 PyTorch 覆盖了 ROCm 版。请重新安装 Radeon Cloud 的 `/torch-*.whl` 和 `/triton-*.whl`，或使用官方 PyTorch ROCm selector。
- 如果安装 Genesis 时长时间停在 `Installing collected packages`，可以用 `ps aux | grep -E '[p]ip|[p]ython'` 检查；只要 pip 进程仍在，通常继续等待即可。
- 在 Radeon Cloud 上请把仓库放在 `/workspace/persistent`，避免实例销毁后文件丢失。
