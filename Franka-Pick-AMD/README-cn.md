# 基于 AMD ROCm 的 Franka 机械臂抓取项目

## 1. 项目简介

### 问题定义

机器人策略学习的核心问题是：**让模型学会从「视觉观测 + 语言任务」映射到「机器人动作」**。

真实机械臂采集数据面临四大痛点：
1. **设备昂贵**：Franka 等研究级机械臂价格不菲
2. **采集速度慢**：一次真实抓取需要数秒到数十秒
3. **碰撞有安全风险**：错误动作可能损坏硬件
4. **实验难以重复**：光照、摩擦、初始位置难以精确复现

### 解决方案

本项目使用 **Genesis 仿真器** 替代真实机械臂完成数据采集与评估：

- **数据生成**：Genesis 中的 IK（逆运动学）专家控制器自动生成抓取示范数据，无需人工示教
- **模型训练**：在预训练 **SmolVLA**（Vision-Language-Action）模型上微调，冻结视觉编码器，仅训练 expert 层和状态投影层
- **闭环评估**：将微调后的模型放回 Genesis，仅凭视觉观测自主控制 Franka 完成抓取

### 核心指标

|指标|数值|
|-|-|
|机器人|Franka Panda，7 臂关节 + 2 夹爪（9 维动作空间）|
|观测|顶视 + 手腕两路相机图像 + 9D 关节状态 + 语言任务|
|数据频率|30 FPS|
|单条轨迹长度|135 帧（约 4.5 秒）|
|模型总参数|~450M（可训练 ~100M，冻结 ~350M）|
|闭环成功率|85%（1000 episodes 训练，8000 步）|

### 技术栈

整个项目自底向上分为 6 层：

```
┌─────────────────────────────────────────────────────────┐
│  第 6 层：SmolVLA                                        │
│           视觉 + 语言 + 机器人状态 → 机器人动作          │
├─────────────────────────────────────────────────────────┤
│  第 5 层：LeRobot + Transformers + Accelerate            │
│           数据集管理、策略接口、模型配置、权重加载        │
├─────────────────────────────────────────────────────────┤
│  第 4 层：Genesis + Taichi                               │
│           机器人仿真、碰撞检测、IK 求解、相机渲染         │
├─────────────────────────────────────────────────────────┤
│  第 3 层：PyTorch + AOTriton                             │
│           张量计算、自动求导、模型训练、Attention 加速    │
├─────────────────────────────────────────────────────────┤
│  第 2 层：ROCm + HIP + Mesa                              │
│           AMD GPU 计算与图形渲染平台                     │
├─────────────────────────────────────────────────────────┤
│  第 1 层：AMD GPU + amdgpu 驱动                          │
│           实际执行计算和渲染                              │
└─────────────────────────────────────────────────────────┘
```

**核心依赖关系**：Genesis 生成仿真数据 → LeRobot 按标准格式保存 → SmolVLA 读取并训练 → 评估时将模型放回 Genesis 做闭环推理。

---

## 2. 开发过程

### 关键决策

**为什么选 SmolVLA 而不是从零训练？**

- SmolVLA 已在海量视觉-语言数据上预训练，具备基本的场景理解和语言跟随能力
- 本项目只需微调与机器人动作预测相关的层（expert + state projection），大幅降低对数据量和算力的需求
- 可训练参数仅约 22%，在 AMD GPU 上单卡即可完成训练

**为什么用仿真数据而不是真实数据？**

- 仿真可无限生成多样化场景，自动随机化方块位置，避免数据分布单一
- IK 控制器作为"上帝视角"专家，生成的标注动作精准无噪声
- 零碰撞风险，可反复运行同一任务，保证实验可复现

### 遇到的困难与解决

|困难|解决方案|
|-|-|
|模型泛化能力不足，抓取成功率低于 80%|微调学习率参数（增加 warmup、调整衰减策略），增大 batch size 和训练步数|

### 如果继续优化

- 采用泛化能力更强的模型如 **Pi0.5** 替代 SmolVLA
- 增加多场景、多物体的训练数据，提升跨场景迁移能力
- 引入数据增强（光照变化、背景扰动）提高视觉鲁棒性
- 尝试从仿真到真实的 Sim-to-Real 迁移

---

## 3. 代码来源说明

### 基础项目

本项目基于 [PhysicalAI-AIM / Robot Synthetic Data Generation Workshop](https://github.com/PhysicalAI-AIM/Robot_synthetic_data_generation_workshop) 进行整理和二次开发。

### 依赖的开源项目

|项目|用途|链接|
|-|-|-|
|LeRobot (Hugging Face)|机器人学习数据格式与训练框架|https://github.com/huggingface/lerobot|
|Genesis Embodied AI|机器人仿真环境|https://genesis-embodied-ai.github.io/|
|SmolVLA|视觉-语言-动作模型|https://huggingface.co/blog/smolvla|
|AMD ROCm|AMD GPU 加速计算平台|https://rocm.docs.amd.com/|

### 修改与原创部分

|部分|说明|
|-|-|
|**目录结构重组**|将原项目扁平结构重组为 `src/`（核心代码）、`data/`（数据生成脚本）、`configs/`（场景配置）的分层结构|
|**训练参数扩展**|新增 `--lr`、`--lr-warmup-steps`、`--lr-decay-steps`、`--lr-decay-end`、`--vlm-backbone` 等参数，支持更灵活的训练调优|
|**完整中英文文档**|补充环境安装、模型准备、参数说明、实验结果等完整文档|

---

## 4. 团队分工

|成员|职责|
|-|-|
|**star**|模型微调、代码维护、结果分析|
|**Be_Yourself**|环境配置、模型训练、文档编写|
|**coC.3**|环境配置、模型训练、演示视频制作|

协作方式：团队成员通过 Git 进行代码协作，star 负责核心代码修改与模型调优，Be_Yourself 和 coC.3 负责环境搭建、训练执行与结果验证，三人共同完成文档与演示材料。

---

## 5. 安装与运行

### 5.1 环境要求

|组件|版本/要求|
|-|-|
|操作系统|Ubuntu 22.04|
|GPU|AMD GPU|

### 5.2 安装步骤

#### 1) 安装 Python 依赖

```bash
python -m pip install \
torch==2.11.0 \
torchvision==0.26.0 \
torchaudio==2.11.0 \
triton==3.6.0 \
--index-url https://download.pytorch.org/whl/rocm7.2

pip install -r requirements.txt
```

#### 2) 安装 Genesis

Genesis 负责机器人仿真、IK 求解和相机渲染，需要安装 GitHub `main` 分支：

```bash
cd /workspace
git clone --depth 1 https://github.com/Genesis-Embodied-AI/Genesis.git Genesis
python -m pip install /workspace/Genesis
```

#### 3) 安装 FFmpeg 与 TorchCodec

LeRobot 将相机帧编码为视频存储，需要视频编解码支持：

```bash
# 安装 FFmpeg
apt-get update
apt-get install -y ffmpeg libavcodec-dev libavformat-dev libavutil-dev \
  libavdevice-dev libavfilter-dev libswscale-dev libswresample-dev

# 安装 TorchCodec
bash setup_torchcodec.sh
```

#### 4) 验证安装

```bash
python - <<'PY'
import torch; assert torch.cuda.is_available(), "ROCm not available"
import genesis; print("Genesis OK")
import lerobot; print("LeRobot OK")
import torchcodec; print("TorchCodec OK")
import transformers, accelerate, safetensors; print("All deps OK")
PY
```

### 5.3 模型准备

本项目需要两个预训练模型，通过 Hugging Face 下载：

```bash
pip install huggingface_hub

# SmolVLA 策略模型
huggingface-cli download lerobot/smolvla_base \
  --local-dir /workspace/models/smolvla_base

# SmolVLM2 视觉语言骨干
huggingface-cli download HuggingFaceTB/SmolVLM2-500M-Video-Instruct \
  --local-dir /workspace/models/SmolVLM2-500M-Video-Instruct
```

模型目录结构：

```
/workspace/models/
├── smolvla_base/
│   ├── config.json
│   ├── model.safetensors
│   ├── preprocessor_config.json
│   └── processor_config.json
└── SmolVLM2-500M-Video-Instruct/
    ├── config.json
    ├── model.safetensors
    ├── preprocessor_config.json
    └── processor_config.json
```

如果无法访问 Hugging Face，可在其他机器下载后复制到对应目录。

#### 离线运行

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

### 5.4 运行流程

完整流程：**生成数据 → 训练 → 评估**

```
Genesis 生成专家轨迹
        ↓ (保存为 LeRobot 格式)
LeRobot 数据集
        ↓ (SmolVLA 读取训练)
微调后的 SmolVLA 策略
        ↓ (放回 Genesis 中评估)
闭环抓取成功率
```

---

#### 5.4.1 生成专家抓取数据

首先下载场景资源：

```bash
bash data/download_kitchen_assets.sh
```

执行数据生成：

```bash
python data/generate_expert_data.py \
  --scene rustic_kitchen \
  --anchor floor_origin \
  --camera-layout up_wrist \
  --n-episodes 1000 \
  --repo-id local/franka-pick \
  --seed 42
```

**参数说明**：

|参数|默认值|说明|
|-|-|-|
|`--repo-id`|`local/kitchen-pick`|LeRobot 数据集名称，`local/` 前缀表示保存到本地缓存|
|`--scene`|`rustic_kitchen`|场景名称（需与训练和评估一致）|
|`--anchor`|`floor_origin`|场景锚点，决定 Franka 底座位置和朝向|
|`--camera-layout`|`up_side`|相机布局：`up_wrist` = 顶视 + 手腕，`up_side` = 顶视 + 侧面|
|`--n-episodes`|`10`|生成多少条完整抓取轨迹|
|`--seed`|`42`|随机种子，保证实验可复现|
|`--fps`|`30`|数据采集帧率|
|`--task`|`Pick up the cube.`|语言任务描述|
|`--add-goal`|`False`|是否将 cube 的 (x,y) 坐标附加到 observation.state|
|`--add-phase`|`False`|是否将归一化时间 t/T 附加到 observation.state|
|`--no-videos`|`False`|是否以 PNG 代替视频存储|

**生成过程**：每条轨迹 135 帧（约 4.5 秒），专家控制器依次执行接近 → 下降 → 闭合夹爪 → 抬起。每帧记录顶视/手腕相机图像、关节状态、专家目标动作和语言任务。

典型输出：
```
[gen] ep 1/1 [OK]  lift=0.1448m  sustain=39
```

---

#### 5.4.2 训练

```bash
python src/train.py \
  --dataset-id local/franka-pick \
  --pretrained /workspace/models/smolvla_base \
  --vlm-backbone /workspace/models/SmolVLM2-500M-Video-Instruct \
  --n-steps 10000 \
  --lr-decay-end 2.5e-6 \
  --lr-decay-steps 6000 \
  --batch-size 32 \
  --num-workers 4 \
  --save-every 0 \
  --log-every 20 \
  --seed 42 \
  --output-dir ./output \
  --run-name smolvla_franka_pick
```

**参数说明**：

|参数|默认值|说明|
|-|-|-|
|`--dataset-id`|`local/so101-genesis-pick`|LeRobot 数据集 ID（与数据生成的 `--repo-id` 一致）|
|`--pretrained`|`lerobot/smolvla_base`|SmolVLA 预训练模型目录或 HF model id|
|`--vlm-backbone`|`HuggingFaceTB/SmolVLM2-500M-Video-Instruct`|VLM 视觉语言骨干模型路径|
|`--n-steps`|`2000`|训练总步数|
|`--batch-size`|`8`|每步 batch 大小|
|`--lr`|`None`|峰值学习率（`None` 时使用默认值 `1e-4`）|
|`--lr-warmup-steps`|`200`|学习率线性预热步数（`0` = 关闭）|
|`--lr-decay-steps`|`2000`|余弦衰减步数|
|`--lr-decay-end`|`1e-5`|衰减终点学习率|
|`--num-workers`|`2`|DataLoader 进程数（`0` 可避免视频解码器崩溃）|
|`--save-every`|`500`|每隔多少步保存 checkpoint（`0` = 仅最终）|
|`--log-every`|`50`|每隔多少步打印日志|
|`--seed`|`None`|随机种子（`None` = 不固定）|
|`--output-dir`|`./output`|输出根目录|
|`--run-name`|`smolvla_pick`|实验名称，模型保存在 `output/train/<run-name>/`|

**训练结果**：

```
output/train/smolvla_franka_pick/
├── final/                  # 最终模型（可直接用于评估）
├── train_summary.json      # 训练汇总（参数、Loss、显存、耗时）
└── train_metrics.json      # 逐步指标（step/loss/grad_norm/lr/step_time）
```

---

#### 5.4.3 闭环评估

将训练好的模型放回 Genesis，仅凭视觉观测自主控制 Franka 抓取方块：

```bash
python src/eval.py \
  --checkpoint output/train/smolvla_franka_pick/final \
  --dataset-id local/franka-pick \
  --vlm-backbone /workspace/models/SmolVLM2-500M-Video-Instruct \
  --scene rustic_kitchen \
  --anchor floor_origin \
  --camera-layout up_wrist \
  --action-horizon 20 \
  --n-episodes 100 \
  --seed 99 \
  --record-video \
  --run-name smolvla_franka_pick
```

**参数说明**：

|参数|默认值|说明|
|-|-|-|
|`--policy-type`|`smolvla`|策略类型：`bc` / `act` / `smolvla`|
|`--checkpoint`|必填|训练好的 checkpoint 目录|
|`--dataset-id`|`local/kitchen-pick`|数据集 ID，用于读取归一化统计量|
|`--task`|`Pick up the red cube.`|语言任务描述|
|`--vlm-backbone`|`HuggingFaceTB/SmolVLM2-500M-Video-Instruct`|VLM 骨干模型路径|
|`--scene`|`rustic_kitchen`|场景名称（需与训练一致）|
|`--anchor`|`floor_origin`|场景锚点|
|`--camera-layout`|`up_side`|相机布局：`up_wrist` / `up_side`|
|`--n-episodes`|`10`|评估 episode 数|
|`--max-steps`|`150`|每 episode 最大仿真步数|
|`--action-horizon`|`1`|每次推理执行的动作步数|
|`--max-delta-rad`|`0.15`|相邻帧动作最大变化量（弧度）|
|`--seed`|`42`|随机种子（决定 cube 初始位置序列）|
|`--success-lift-m`|`0.02`|成功最小抬升高度（米）|
|`--success-sustain`|`8`|成功最小持续帧数|
|`--success-final-m`|`0.01`|成功最终最小高度（米）|
|`--record-video`|`False`|是否录制评估视频|
|`--output-dir`|`./output`|输出根目录|
|`--run-name`|`kitchen_eval`|评估名称，结果保存在 `output/eval/<run-name>/`|

**评估结果**：

```
output/eval/smolvla_franka_pick/
├── eval_summary.json      # 评估汇总（成功率、每个 episode 详情）
└── videos/
    ├── ep000_success_up.mp4
    ├── ep000_success_side.mp4
    ├── ep001_fail_up.mp4
    └── ep001_fail_side.mp4
```

|文件|说明|
|-|-|
|`eval_summary.json`|总 episode 数、成功数、成功率、场景信息、每个 episode 的详细结果（方块位置、抬升高度、持续帧数等）|
|`videos/`|评估视频目录（需开启 `--record-video`）|

视频文件命名：`ep{编号}_{success|fail}_{up|side}.mp4`。对比成功和失败视频可直观分析模型的常见错误模式（错过方块、夹爪闭合时机不对、抬升后滑落等）。

---

### 5.5 参考结果

以下为 1000 episodes 训练 8000 步、评估 100 次的参考结果：

|阶段|指标|数值|
|-|-|-|
|数据生成|每条轨迹帧数|135|
|数据生成|数据频率|30 FPS|
|训练|训练步数|8000|
|训练|Batch Size|32|
|训练|初始 Loss|2.8322|
|训练|最终 Loss|0.0116|
|训练|训练时间|~5032s|
|训练|峰值显存|~5.8 GB|
|评估|闭环成功率|80/100 = 80%|
