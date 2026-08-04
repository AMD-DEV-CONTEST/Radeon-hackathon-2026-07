# Track 3 - Cybertronic Franka Genesis Study

## English

This submission demonstrates a Franka Panda robot arm following a moving fruit target in Genesis on AMD ROCm. The demo uses inverse kinematics for target tracking and joint PD control for smooth execution. It records an offscreen MP4 video and writes metrics for tracking error, IK latency, runtime, and GPU/backend information.

### Repository Structure

```text
.
├── README.md
├── LICENSE
├── requirements.txt
├── src/
│   └── franka_fruit_follow.py
├── scripts/
│   └── franka_fruit_follow.py
├── configs/
│   └── franka_fruit_follow.json
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

Optional smoke test:

```bash
python scripts/franka_fruit_follow.py \
  --frames 60 \
  --video outputs/videos/franka_fruit_follow_smoke.mp4
```

Generated outputs are written to `outputs/`, which is intentionally ignored by Git.

### Demo Video

Do not commit large MP4 files to GitHub. Add the final video URL in `videos/README.md`.

## 中文

本项目展示了 Franka Panda 机械臂在 AMD ROCm 环境下使用 Genesis 进行水果目标跟随。Demo 通过逆运动学计算末端执行器目标姿态，并使用关节 PD 控制完成平滑跟随。程序会生成离屏录制视频，并输出跟踪误差、IK 耗时、运行时间和 GPU/后端信息等指标。

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

快速 smoke test：

```bash
python scripts/franka_fruit_follow.py \
  --frames 60 \
  --video outputs/videos/franka_fruit_follow_smoke.mp4
```

生成的视频和运行指标位于 `outputs/`，该目录已被 `.gitignore` 忽略，避免把大文件直接提交到 GitHub。
