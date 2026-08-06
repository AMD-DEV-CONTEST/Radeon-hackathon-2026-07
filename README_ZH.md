# Pick Fruit by SmolVLA on AMD ROCm

[English](README.md) | 中文

基于Genesis、LeRobot、SmolVLA、AMD Radeon GPU与ROCm的Franka多模态水果抓取系统。仓库包含比赛技术报告、最小核心源码、正式结果和图表；训练数据和模型权重作为外部制品管理，不直接提交到Git。

[技术报告](docs/TECHNICAL_REPORT_ZH.md) · [可复现说明](docs/REPRODUCIBILITY_ZH.md) · [制品清单](artifacts/manifest.json)

## SmolVLA英文演示与闭环示例

以下视频均为微调后的SmolVLA模仿学习策略闭环输出，不是脚本专家回放：

![香蕉、柠檬和李子成功示例预览](docs/video/preview.gif)

[观看英文旁白演示视频](docs/video/smolvla_success_failure_demo.mp4)

### 视频内容

该视频时长约3分20秒，采用英文语音旁白和1080p三路同步视角，展示微调后SmolVLA的真实闭环行为，而不是脚本专家回放。主要内容包括：

- 600个成功episode及Domain Randomization训练数据；
- 香蕉、柠檬和李子的完整成功夹取与放置；
- 柠檬和李子的已保存失败回合；
- HIP Graph部署评估成功率：香蕉99%、柠檬94%、李子34%；
- 接近偏差、弱夹持、抬升失败和运输掉落等失败原因；
- HIP Graph与Targeted Compile的ROCm推理性能和正确性取舍。

视频中的成功示例用于直观展示策略能力，正式结论仍以每类水果100回合的统计结果为准。当前保存的10个香蕉可视化回合全部成功，因此没有使用旧模型的香蕉失败录像替代；这不表示香蕉没有失败，因为100回合正式评估仍记录了1次失败。视频重建和旁白说明见[NARRATION_EN.md](docs/video/NARRATION_EN.md)。

### 独立闭环录像

- [香蕉成功示例](docs/video/success_examples/banana_success.mp4)
- [柠檬成功示例](docs/video/success_examples/lemon_success.mp4)
- [李子成功示例](docs/video/success_examples/plum_success.mp4)
- [柠檬失败示例](docs/video/failure_examples/lemon_failure.mp4)
- [李子失败示例](docs/video/failure_examples/plum_failure.mp4)

## 核心结果

| 内容 | 结果 |
|---|---|
| 领域随机化数据 | 600个成功episode，香蕉/柠檬/李子各200个 |
| SmolVLA微调 | 20,000步，batch size 128 |
| HIP Graph完整推理 | 153.81 → 102.76 ms，1.497×，严格验证零误差 |
| Targeted compile完整推理 | 153.81 → 63.86 ms，2.409×，存在数值误差 |
| HIP Graph闭环 | 224/300 → 227/300，稳态推理1.248× |
| Targeted compile闭环 | 218/300 → 222/300，稳态推理1.354× |
| Lift residual SAC | 34/100 → 43/100，初步结果，未独立验证 |

## 已完成训练记录

以下数据来自原始checkpoint元数据与训练日志，而不是根据配置文件推测：

| 训练 | 已完成记录 | 产物 |
|---|---|---|
| SmolVLA微调 | 20,000步，batch 128，seed 1000；每2,000步保存，共10个周期checkpoint | 最终模型906,712,520 bytes |
| Lift-only Residual SAC | 100,000步，warmup 10,000，batch 256；每10,000步保存 | `last.pt`记录step 100,000、状态62维、残差9维 |

Residual训练日志记录361个完整episode，其中169个成功（46.8%），最后100个训练episode为45/100。这是在线强化学习过程的训练监控数据，不是独立测试集；项目结论仍使用固定seeds 2000–2099的配对评估34/100→43/100。SmolVLA原输出没有逐步loss日志，因此不提供无法由现有证据复原的loss曲线。完整记录见[历史训练记录](results/training/README_ZH.md)。

HIP Graph是当前稳定部署候选。Targeted compile性能更高，但严格离线验证存在数值偏差，因此保留为实验后端。两套闭环实验使用不同seed范围，只能分别与各自的eager基线比较。

![核心成果](docs/figures/fig10_results_dashboard.png)

## 系统流程

```text
Genesis仿真
  → 脚本专家与Domain Randomization
  → 600回合LeRobot数据集
  → SmolVLA微调
  → Eager / HIP Graph / Targeted compile
  → Franka闭环抓取
  → 李子失败诊断与Residual SAC探索
```

![完整流水线](docs/figures/fig5_full_pipeline.png)

## 仓库内容

```text
Pick-Fruit-By-SmolVLA/
├── README.md                    # 英文默认入口
├── README_ZH.md                 # 中文项目说明
├── pyproject.toml               # Python项目与核心依赖
├── .gitignore                   # 忽略数据、权重、复现输出和视频中间段
├── docs/
│   ├── TECHNICAL_REPORT.md      # 英文技术报告（默认）
│   ├── TECHNICAL_REPORT_ZH.md   # 中文技术报告
│   ├── REPRODUCIBILITY.md       # 英文可复现性说明（默认）
│   ├── REPRODUCIBILITY_ZH.md    # 中文可复现性说明
│   ├── figures/                 # 架构、性能、成功率和Residual RL图表
│   └── video/
│       ├── smolvla_success_failure_demo.mp4  # 3分20秒英文旁白演示
│       ├── preview.gif                     # 三水果成功动态预览
│       ├── success_examples/               # 香蕉、柠檬、李子成功原片
│       ├── failure_examples/               # 柠檬、李子失败原片
│       ├── NARRATION_EN.md                  # 英文旁白与证据边界说明
│       └── build_success_failure_video.sh   # 可重复构建视频
├── franka_fruit_pick/
│   ├── build_scene.py           # Genesis场景与Franka/YCB资产加载
│   ├── randomize.py             # Domain Randomization
│   ├── record_dataset.py        # LeRobot专家数据录制
│   ├── aggregate_datasets.py     # 合并三种水果的LeRobot数据集
│   ├── train_policy.py          # LeRobot/SmolVLA训练入口
│   ├── eval_policy.py           # Eager/加速后端闭环评估
│   └── residual_rl/             # 特权状态Residual SAC实现
├── optimization/
│   ├── common.py                # 模型加载与统一测速工具
│   └── runtime/                 # HIP Graph、Targeted Compile、测速与验证
├── scripts/
│   ├── train_smolvla_fruit_pick.sh
│   ├── train_residual_sac_lift.sh
│   ├── benchmark_rocm_backends.sh
│   ├── validate_rocm_backends.sh
│   └── evaluate_rocm_closed_loop.sh
├── configs/
│   ├── smolvla_train_config.json
│   └── residual_sac_lift_config.json
├── results/
│   ├── runtime/                 # 完整推理测速与严格验证
│   ├── closed_loop/             # HIP Graph/Compile闭环A/B汇总
│   ├── residual_rl/             # Residual配对评估与消融
│   └── training/
│       ├── README.md            # 英文历史训练记录（默认）
│       └── README_ZH.md         # 中文历史训练记录
├── artifacts/
│   ├── manifest.json            # 外部数据/权重大小、SHA256和下载URL
│   └── README.md                # 制品放置与校验说明
├── assets/                      # 运行场景所需Franka与YCB资产
└── docker/Dockerfile            # AMD ROCm运行环境
```

开发阶段的一次性脚本、历史AMD微基准、debug/handoff、旧ACT流程、训练数据、checkpoint和视频编码中间段均未迁移。训练数据与权重通过`artifacts/manifest.json`管理，新实验输出统一写入被Git忽略的`reproductions/`。

## 采集训练数据

仓库包含完整的数据采集入口：`franka_fruit_pick/record_dataset.py`调用脚本专家在Genesis中执行抓取，只把成功回合写成LeRobot数据集；`franka_fruit_pick/aggregate_datasets.py`负责把三个单水果数据集合并。以下命令会在`reproductions/datasets/`新建数据，不会覆盖`artifacts/`中的正式数据：

```bash
mkdir -p reproductions/datasets

for spec in \
  "011_banana banana 2000" \
  "014_lemon lemon 3000" \
  "018_plum plum 4000"; do
  set -- $spec
  xvfb-run -a -s '-screen 0 1920x1080x24' \
    python franka_fruit_pick/record_dataset.py \
      --episodes 200 --max-attempts 2000 --seed "$3" \
      --pick "$1" --repo-id "demo/${2}_pick_dr_200ep" \
      --root "reproductions/datasets/${2}_pick_dr_200ep" --vcodec h264 \
      --dr-appearance --dr-object-color --dr-table-jitter 0.15 \
      --dr-fov-jitter 2.0 --dr-rebuild-every 5 \
      --dr-runtime --dr-friction 0.6 1.4 --dr-mass 0.8 1.2 \
      --dr-cam-pos 0.01 --dr-cam-lookat 0.02
done

python franka_fruit_pick/aggregate_datasets.py \
  --dataset-root reproductions/datasets/banana_pick_dr_200ep \
  --dataset-root reproductions/datasets/lemon_pick_dr_200ep \
  --dataset-root reproductions/datasets/plum_pick_dr_200ep \
  --out reproductions/datasets/fruit_pick_dr_600ep \
  --aggr-repo-id demo/fruit_pick_dr_600ep
```

`--episodes 200`表示保存200个成功回合；失败尝试默认丢弃，`--max-attempts`限制总尝试次数。采集同时启用外观、物体颜色、相机、初始位置姿态、摩擦和质量随机化。运行前需要安装项目完整依赖、可用的Genesis GPU环境、`xvfb-run`和H.264编码器。可先运行以下命令查看全部参数：

```bash
python franka_fruit_pick/record_dataset.py --help
python franka_fruit_pick/aggregate_datasets.py --help
```

## 模型训练

训练脚本位于`scripts/`，默认读取`artifacts/`下的外部数据或权重，并将新结果写到被Git忽略的`reproductions/`，不会覆盖随仓库提供的正式结果。

### 1. 微调SmolVLA

准备好600回合LeRobot数据集后执行：

```bash
bash scripts/train_smolvla_fruit_pick.sh
```

该脚本复现本项目的主要训练设置：SmolVLA base、20,000步、batch size 128、每2,000步保存一次，使用AMD ROCm GPU（PyTorch设备名为`cuda`）。最终模型通常位于：

```text
reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model/
```

可以先检查最终命令而不启动训练：

```bash
DRY_RUN=1 bash scripts/train_smolvla_fruit_pick.sh
```

通过环境变量覆盖常用参数，例如：

```bash
PYTHON_BIN=/path/to/python STEPS=100 BATCH_SIZE=4 \
  DATASET_ROOT=/path/to/fruit_pick_dr_600ep \
  bash scripts/train_smolvla_fruit_pick.sh
```

如果上游base已经下载为本地目录，可设置`POLICY_PATH=/path/to/smolvla_base`；否则默认从Hugging Face解析`lerobot/smolvla_base`。训练器完整输出同时保存在`<OUTPUT_DIR>.launcher.log`，脚本会把LeRobot打印traceback但错误返回0的情况强制标记为失败。

完整的历史训练配置快照见[configs/smolvla_train_config.json](configs/smolvla_train_config.json)。

### 2. 训练Residual SAC

Residual SAC冻结已经微调的SmolVLA，只训练李子抓取的9维特权状态残差策略：

```bash
bash scripts/train_residual_sac_lift.sh
```

默认执行lift-only、100,000步训练，输出到`reproductions/rl/plum_residual_sac/`。运行前同时需要600回合数据集和SmolVLA checkpoint。只检查命令可使用：

```bash
DRY_RUN=1 bash scripts/train_residual_sac_lift.sh
```

若使用刚重新训练的SmolVLA：

```bash
POLICY_PATH="$PWD/reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model" \
  bash scripts/train_residual_sac_lift.sh
```

参数快照见[configs/residual_sac_lift_config.json](configs/residual_sac_lift_config.json)，算法和评估说明见[Residual SAC说明](franka_fruit_pick/residual_rl/README.md)。逐步环境安装、数据放置和训练后验证流程见[可复现性说明](docs/REPRODUCIBILITY_ZH.md)。

两个入口均已在AMD GPU上完成真实的临时1-step测试，包括模型和数据加载、参数更新及checkpoint保存；临时测试产物已删除，不计入上述正式训练记录。

## AMD ROCm推理加速复现

三个必要入口位于`scripts/`：

```bash
# Eager、HIP Graph、Targeted Compile完整sample_actions测速
bash scripts/benchmark_rocm_backends.sh

# HIP Graph和Targeted Compile相对Eager的数值验证
bash scripts/validate_rocm_backends.sh

# 默认复现Eager vs HIP Graph，每类水果100回合
bash scripts/evaluate_rocm_closed_loop.sh
```

Targeted Compile闭环使用：

```bash
CANDIDATE=targeted-compile SEED=<报告对应seed> POLICY_SEED=<报告对应seed> \
  bash scripts/evaluate_rocm_closed_loop.sh
```

所有新输出写入`reproductions/`。可先用`DRY_RUN=1`查看命令；调试时可设置`ITERATIONS=1 WARMUP=0 BACKENDS=eager`，或设置`EPISODES=1 FRUITS=banana`只运行香蕉的一对闭环。完整300回合闭环耗时较长。HIP Graph应通过严格验证；Targeted Compile虽然更快，但报告中的严格验证结果为数值不匹配。

## 外部制品

仓库不包含以下大型文件：

```text
artifacts/datasets/fruit_pick_dr_600ep/
artifacts/models/smolvla_fruit_pick_dr_600ep/
artifacts/models/plum_residual_sac_lift/last.pt
```

正式下载URL尚需在[artifacts/manifest.json](artifacts/manifest.json)中填写。SmolVLA主权重和Residual SAC权重的大小、SHA256已经记录。没有这些制品时仍可阅读报告、核查已保存结果、运行无需模型的汇总和CLI检查，但不能重新执行模型推理或闭环仿真。

## 环境摘要

- Ubuntu 24.04
- Python 3.12
- ROCm 7.2.1
- ROCm PyTorch 2.9.1
- ROCm Triton 3.5.1
- LeRobot 0.6.0
- Genesis 1.1.2或兼容版本
- 开发/容器目标：AMD Radeon AI PRO R9700

PyTorch在ROCm中沿用`torch.cuda`接口，所以代码中的`device=cuda`表示HIP设备。

## 快速核查（不需要权重）

```bash
python -m compileall -q franka_fruit_pick optimization

python -m optimization.runtime.summarize_results \
  --results-dir results/runtime

python -m optimization.runtime.summarize_closed_loop_ab \
  results/closed_loop/hip_graph/raw \
  --episodes 100
```

最后一条命令仅在同时提供逐回合raw JSON时适用；当前精简仓库直接提供已生成的闭环CSV和Markdown汇总。

## 获取制品后运行

阅读[可复现性说明](docs/REPRODUCIBILITY_ZH.md)，按以下顺序执行：

1. 安装或构建ROCm环境；
2. 将数据和权重放到manifest指定位置；
3. 检查GPU、依赖和制品哈希；
4. 运行单回合闭环Smoke Test；
5. 复现完整推理测速与正确性；
6. 按需运行耗时较长的闭环评估。

## 主要材料

- [中文技术报告](docs/TECHNICAL_REPORT_ZH.md)
- [英文技术报告](docs/TECHNICAL_REPORT.md)
- [中文可复现性说明](docs/REPRODUCIBILITY_ZH.md)
- [英文可复现性说明](docs/REPRODUCIBILITY.md)
- [正式结果说明](results/README.md)
- [模型与数据制品说明](artifacts/README.md)
- [英文旁白成功与失败分析视频](docs/video/smolvla_success_failure_demo.mp4)
- [香蕉成功示例](docs/video/success_examples/banana_success.mp4)
- [柠檬成功示例](docs/video/success_examples/lemon_success.mp4)
- [李子成功示例](docs/video/success_examples/plum_success.mp4)
- [柠檬失败示例](docs/video/failure_examples/lemon_failure.mp4)
- [李子失败示例](docs/video/failure_examples/plum_failure.mp4)
- [ROCm runtime说明](optimization/runtime/README.md)
- [Residual SAC说明](franka_fruit_pick/residual_rl/README.md)

## 已知限制

- 李子成功率明显低于香蕉和柠檬；
- Targeted compile存在严格数值误差和冷编译成本；
- Residual SAC使用仿真特权状态，34%→43%尚未独立seed验证；
- 当前结果来自仿真，尚未部署到真实Franka；
- 模型推理加速被相机渲染、预处理和物理仿真开销稀释；
- 外部制品URL和最终依赖锁仍是发布前待办。

## 许可证

Franka、YCB、Genesis、LeRobot和SmolVLA保持各自上游许可证。正式发布前需要补充`LICENSE`和`THIRD_PARTY_NOTICES.md`，并核对模型、数据和资产的再分发条款。
