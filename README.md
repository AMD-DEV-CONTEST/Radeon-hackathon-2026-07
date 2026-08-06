# RoboPilot — YCB 颜色分类抓取放置（SmolVLA + Qwen3-VL on AMD ROCm）

**AMD Radeon Hackathon 2026-07 · Track 3 · Physical AI Challenge**

Franka Panda 机械臂在 Genesis 物理引擎中，将 YCB 物体按颜色分类抓取放置到对应的凹槽容器中。系统采用**双 VLM 分层闭环**：Qwen3-VL-8B 负责视觉感知与任务规划，SmolVLA-450M 负责 30Hz 实时闭环控制。

---

## 1. 环境要求

| 组件 | 版本/要求 |
|------|----------|
| GPU | AMD Radeon（ROCm 7.2，推荐 ≥48GB VRAM） |
| 物理引擎 | Genesis 1.2.3（GPU 并行） |
| 框架 | LeRobot 0.6.0 |
| PyTorch | 2.11（ROCm 后端） |
| Transformers | ≥4.57 |
| Python | 3.12 |

## 2. 模型与权重

| 模型 | 位置 | 用途 |
|------|------|------|
| SmolVLA-450M 基础 | `/workspace/models/smolvla_base` | 策略微调起点 |
| Qwen3-VL-8B | `/workspace/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct` | 视觉感知/规划（ModelScope 本地下载） |

> 注：`lerobot/smolvla_base` 离线环境不可解析，须用本地路径 `/workspace/models/smolvla_base`。

## 3. 场景与物体

**训练物体（颜色各异，均可靠可抓）：**
| 物体 | 颜色 | 容器 | 尺寸 |
|------|------|------|------|
| 011_banana | 黄 | yellow | 6.9cm 短轴 |
| 018_plum | 紫 | purple | 5.3cm |
| red_cube（几何） | 红 | red | 5.0cm 立方体 |

**Eval 物体：** 014_lemon（黄，held-out 泛化）

> **物体选择准则**：Franka 夹爪最大张开 7.62cm，可靠抓取需物体短轴 ≤6cm。圆滑大物体（apple/orange 7.2cm+）超出可靠范围，故用红色几何立方体替代。

## 4. 完整工作流

### 步骤 1：录制专家数据集
```bash
cd color_sort
source /workspace/rdna/bin/activate
python record_dataset_parallel.py \
  --episodes 220 --n-envs 32 --split train \
  --repo-id color_sort/train_ycb4 --root ../datasets/train_ycb4 \
  --overwrite --jitter 0.02
```
- 每 batch 开头重置环境；**批级 NaN 恢复**自动跳过偶发解算器发散，不中断录制
- 产出 ~227 成功 episodes（含世界+腕部相机视频 + 9D 关节动作）

### 步骤 2：验证数据集
```bash
python inspect_dataset.py ../datasets/train_ycb4
```

### 步骤 3：训练 SmolVLA
```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python train_policy.py smolvla \
  --repo-id color_sort/train_ycb4 \
  --steps 10000 --batch-size 64 --save-freq 5000 --num-workers 8 \
  --device cuda --policy-path /workspace/models/smolvla_base
```
- 训练耗时约 3.4 小时（batch=64, fp32）
- 输出：`../outputs/train/smolvla_train_ycb4/checkpoints/{005000,010000}`

### 步骤 4：闭环评估（SmolVLA 策略）
```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python eval_policy.py \
  --policy-path ../outputs/train/smolvla_train_ycb4/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb4 --dataset-root ../datasets/train_ycb4 \
  --episodes 20 --split train --seed 1000 --device cuda --jitter 0.02
```

### 步骤 5：全链路闭环（Qwen3-VL 规划 + SmolVLA 执行）
```bash
cd color_sort
source /workspace/rdna/bin/activate
HF_HOME=/workspace/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python eval_policy.py \
  --policy-path ../outputs/train/smolvla_train_ycb4/checkpoints/010000/pretrained_model \
  --repo-id color_sort/train_ycb4 --dataset-root ../datasets/train_ycb4 \
  --episodes 3 --split train --seed 1000 --device cuda --jitter 0.02 \
  --qwen-plan      # 启用 Qwen3-VL 视觉规划（识别颜色→选目标）
```
> `--qwen-verify` 可同时启用 Qwen3-VL 放置结果验证（Stage C2）。

## 5. 专家演示（单物体）
```bash
cd color_sort
python sk_grasp_demo.py --pick red_cube    # red_cube / 011_banana / 018_plum
python sk_grasp_demo.py --pick 011_banana
```

## 6. 评估结果

| 版本 | 训练物体 | 成功率 |
|------|---------|--------|
| v6（几何基元） | cube/cylinder | 50% |
| YCB v4 | banana/plum/red_cube | **70%** |
| 闭环（Qwen3-VL 规划） | 3 episodes | **100%** |

分物体：banana **100%**，plum 57%，red_cube 25%。

## 7. 项目结构
```
color_sort/
├── build_scene.py           # Genesis 场景构建（YCB 物体 + 5-box 容器）
├── scene_config.py          # 布局/颜色/容器/几何物体配置
├── sk_grasp_demo.py         # 专家抓取放置脚本
├── record_dataset_parallel.py  # 并行数据集录制（批级 NaN 恢复）
├── train_policy.py          # SmolVLA/ACT 训练封装
├── eval_policy.py           # 闭环评估（含 Qwen3-VL 规划/验证）
├── qwen_planner.py          # Qwen3-VL 视觉任务规划
├── qwen_verifier.py         # Qwen3-VL 放置验证
├── inspect_dataset.py       # 数据集检查
└── xml/                     # Franka 模型
```

## 8. 技术报告
详见 [`docs/compose/reports/technical-report.md`](docs/compose/reports/technical-report.md)，含架构图、AMD ROCm GPU 使用数据、训练耗时、创新点。
