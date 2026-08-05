# Track 3 - Cybertronic Franka Genesis Study

## English

This submission demonstrates a Franka Panda robot arm following a moving fruit target in Genesis on AMD ROCm. The demo uses inverse kinematics for target tracking and joint PD control for smooth execution. It records an offscreen MP4 video and writes metrics for tracking error, IK latency, runtime, and GPU/backend information.

The enhanced demo extends the baseline into a vision-guided closed-loop controller. Instead of controlling only from the fruit's simulation coordinates, it detects the red fruit in rendered camera frames, estimates image-space error, and converts that observation into visual-servo target corrections for the Franka end effector.

For the final competition demo, the repository also includes a vision-guided pick-and-lift sequence. It detects the red fruit, approaches it, closes the gripper, and lifts the target to provide a clearer manipulation result than tracking alone.

### Repository Structure

```text
.
├── README.md
├── LICENSE
├── requirements.txt
├── src/
│   ├── franka_fruit_follow.py
│   ├── franka_vision_pick.py
│   ├── franka_vision_servo.py
│   └── vision_tracking.py
├── scripts/
│   ├── franka_fruit_follow.py
│   ├── franka_vision_pick.py
│   └── franka_vision_servo.py
├── configs/
│   ├── franka_fruit_follow.json
│   ├── franka_vision_pick.json
│   └── franka_vision_tracking.json
├── data/
│   └── README.md
├── docs/
│   └── implementation.md
├── results/
│   └── franka_fruit_follow.json
└── videos/
    └── README.md
```

### Environment

Install dependencies in the ROCm/Genesis environment:

```bash
pip install -r requirements.txt
```

The validated environment used for the included metrics was:

- Genesis 1.3.1
- PyTorch ROCm build
- AMD Radeon Graphics

### Run

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

Compare with a coordinate-control baseline using the same enhanced script:

```bash
python scripts/franka_vision_servo.py --mode baseline
```

Generated outputs are written to `outputs/`, which is intentionally ignored by Git.

### Metrics

The vision-guided demo writes:

- `outputs/metrics/franka_vision_servo.json`: full per-frame metrics
- `results/franka_vision_servo_summary.json`: lightweight summary suitable for committing
- `outputs/metrics/franka_vision_pick.json`: full pick-and-lift metrics
- `results/franka_vision_pick_summary.json`: lightweight pick-and-lift summary suitable for committing

Important metrics include detection rate, mean image-space error, end-effector tracking error, IK latency, runtime, GPU information, and annotated-video path.

### Cloud Server Reproduction

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

Create or activate the Python environment used by Genesis/ROCm, then install project dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

If the cloud image already provides a working Genesis environment, activate that environment instead of creating a new one, then run:

```bash
pip install -r requirements.txt
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

### Demo Video

Do not commit large MP4 files to GitHub. Add the final video URL in `videos/README.md`.

## 中文

本项目展示了 Franka Panda 机械臂在 AMD ROCm 环境下使用 Genesis 进行水果目标跟随。Demo 通过逆运动学计算末端执行器目标姿态，并使用关节 PD 控制完成平滑跟随。程序会生成离屏录制视频，并输出跟踪误差、IK 耗时、运行时间和 GPU/后端信息等指标。

增强版在 baseline 基础上加入视觉闭环：程序从 Genesis 相机渲染图像中检测红色水果，计算图像空间误差，再将视觉误差转换成机械臂末端目标修正量，实现基于感知的视觉伺服跟随。

为了让比赛视频更有任务完成感，项目还新增了视觉引导 pick-and-lift 演示：检测红色水果后，机械臂执行靠近、闭合夹爪、抬起目标的完整流程。这个版本比单纯跟随更适合作为最终展示视频。

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

在本项目目录下安装依赖：

```bash
pip install -r requirements.txt
```

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

创建或激活 Python 环境，并安装依赖：

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

如果云服务器镜像已经提供可用的 Genesis/ROCm 环境，就不要重新创建 venv，直接激活已有环境后执行：

```bash
pip install -r requirements.txt
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
