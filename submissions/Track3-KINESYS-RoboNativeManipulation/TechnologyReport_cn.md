# AMD Radeon-hackathon-2026-07 Track 3 (Physical AI) Technology Report


## RoboNativeManipulation：用高保真仿真数据，填平机器人与家电之间的鸿沟

![](./assets/Flat_combined.jpg)

**目标应用**：让机器人在照片级真实的家庭场景里学会操作家电。本项目以 BiGym 的「洗碗机餐具收纳」长程任务为闭环验证载体，构建一条「真实场景 3DGS 重建 → 数据回放采集 → 双框架 VLA 后训练 → AMD 单卡推理 → 闭环评测」的端到端管线，全部关键阶段在单张 AMD Radeon GPU 上跑通。

## 核心成果一览

全部环节在**单张 AMD Radeon PRO W7900D（gfx1100，48 GB）+ ROCm 7.2.1** 上端到端跑通。下表为各阶段实测口径（实跑，非估算）：

| 阶段 | 关键指标 |
| --- | --- |
| 3DGS 外壳重建 | 352 张 1080p 照片 → 约 145 万高斯（清理后 1,458,354），留出视角 **PSNR 27.9 / SSIM 0.937** |
| 3DGS 运行时渲染 | 三相机（head 480×848、左右腕 480×640）约 **2.7 GiB** 显存（Pi0.5 评测侧实测） |
| 训练 · Pi0.5（JAX+ROCm） | 稳态 **1.2 s/step**，峰值显存 **35.3 GiB**（稳态均值 33.6 GiB），GPU 利用率 **95.6%** |
| 训练 · DM0.5（PyTorch+ROCm） | 实测 **1.5295 samples/s**（micro-batch 12 × accum 4），峰值显存 **28.74 GiB**，GPU 利用率 **99.47%**；优化方法在 ReachTarget 吞吐基准上较基线 +24.4% |
| 推理 · Pi0.5 | 端到端 **≈240 ms/次**（≈4.2 次/秒） |
| 推理 · DM0.5 | 端到端 **438.72 ms/次**（4 步扩散算子基准；发布成功率协议用 10 步），峰值显存 **12.79 GiB**，GPU 利用率 **67.68%** |
| 闭环 · DM0.5（50 种子） | native **25/50 = 50%** · 3DGS 外壳 **20/50 = 40%** |
| 闭环 · Pi0.5（50 种子） | 3DGS 外壳 **5/50 = 10%**（未做 native 评测） |
| 双框架验证 | 同一张卡跑通 **PyTorch+ROCm（DM0.5）** 与 **JAX+ROCm（Pi0.5）** 两条 SOTA VLA 路径 |

**与 BiGym 论文基线对比（任务：dishwasher unload cutlery long）：**

> **关键前提**：BiGym 论文的 7 个基线**全部在干净的原生 BiGym 场景（无 3DGS 外壳）上评测**；而本工作的结果（除 native 行外）**均在带照片级 3DGS 外壳的更难视觉域上得到**——也就是说，我们是在更难的赛道上和论文比。

| 方法 | 评测场景 | 成功率 |
| --- | --- | --- |
| BiGym 论文 · BC | 干净（无 3DGS） | 1.3 ± 2.3 |
| BiGym 论文 · ACT | 干净（无 3DGS） | 14.7 ± 8.3 |
| BiGym 论文 · DiffPolicy | 干净（无 3DGS） | 5.3 ± 5.8 |
| BiGym 论文 · DrQV2 / AWAC / IQL / CQN | 干净（无 3DGS） | 0.0 ± 0.0 |
| **本工作 · DM0.5（native）** | **干净（无 3DGS）** | **50%** |
| **本工作 · DM0.5（PyTorch+ROCm）** | **带 3DGS 外壳** | **40%** |
| **本工作 · Pi0.5（JAX+ROCm）** | **带 3DGS 外壳** | **10%** |

- **同场对比（干净场景，与论文同口径）**：DM0.5 native **50%**，是论文最强基线 ACT（14.7%）的约 3.4 倍；论文其余基线（BC / DiffPolicy / DrQV2 / AWAC / IQL / CQN）仅 0–5%。
- **更难场景对比（带 3DGS 外壳）**：即便换成照片级视觉域，DM0.5 仍有 **40%**，仍显著高于论文**全部**干净场景基线；Pi0.5 在此前提下给出 **10%** 基线，DM0.5 相对该基线提升约 **300%（4 倍）**。

## 背景与痛点

软件正在经历「AI Native 化」——无需重写代码，只需封装一层 Skill 即可被 AI 接管。家庭场景中的电器也将迎来同样的范式迁移，从"为人设计"转向"为机器人可用"，我们称之为 Robotics Native。

然而，现实世界仍是为人设计的。行业押注人形机器人以适配人类环境，但受限于成本，当前机器人的灵巧度与关节自由度仍不及真人。一边是精密复杂的人造家电，一边是能力尚存差距的机器人本体，这道 "形态与能力的错配"，正是机器人进入家庭场景的最大阻碍。

## 我们的管线

用 3DGS 把家庭场景重建出来，将电器的数字资产放入这个仿真场景，让机器人在极真实的环境里反复「熟悉」一台台电器、跑通日常操作，源源不断地产出「机器人操作这些物件」的数据。

- **短期 · 轻量化后训练（Post-training）**：基于 DM0.5 和 Pi0.5 开源基础模型，用管线产出的数据做高效微调，单张 AMD 卡即可让机器人掌握特定电器的操作技能，同时保留通用常识——最贴近落地，适合电器厂家针对自家产品快速验证。
- **长期 · 高价值预训练（Pre-training）赋能**：管线产出的高质量操作数据以高密度样本形式注入下一代基础模型的预训练语料，使未来基座模型原生内化家电操作能力，而非依赖后期补丁，真正实现 Robotics Native。

## 为什么选这两个模型

我们刻意选择分属两大主流框架的两个 SOTA VLA 基础模型，用以验证 ROCm 对主流深度学习生态的覆盖成熟度：

- **Pi0.5（JAX）**：使用 **JAX** 框架——工业界广泛使用的深度学习框架。打通它，等于验证 ROCm 对工业主流技术栈的支持。
- **DM0.5（PyTorch）**：知名的 VLA 基础模型，使用 **PyTorch** 框架——同样是我们想要打通的主流框架。

两者都是**大规模预训练**的基础模型，本身已内化大量通用操作常识；我们只需在其上做**轻量后训练（LoRA 微调，单卡即可）**，就能以较小代价在特定家电任务上达到不错的效果——这正是后训练范式相对从零训练的核心优势。

## 总体架构：三仓库协同、单卡闭环

整条 Physical-AI 管线由三个仓库分工协同，在单张 AMD 卡上构成闭环。**核心仓库 `rocm_bigym_3dgs` 是中枢**，负责 3DGS 外壳生成、带外壳的数据回放采集，以及最后的闭环评测编排；数据产出后，**分别喂给 Pi0.5（JAX）与 DM0.5（PyTorch）两条训练路径**，各自在 AMD 卡上起推理服务，再交回核心仓库提供的中立评测器与 HTTP 协议做闭环评测，得到成功率。

```text
   【阶段一】3DGS 外壳生成   (核心仓库 rocm_bigym_3dgs)
   真实厨房照片 → 改造后 OpenSplat/HIP 重建  →  高斯房间壳
        (gfx1100, PSNR 27.9)

   【阶段二】带外壳数据回放   (核心仓库)
   BiGym + gsplat 渲染回放  →  LeRobot v3 数据集 (32 条)
                              │
              ┌───────────────┴─────────────────┐
              ▼                                   ▼
   【阶段三】Pi0.5 训练 (JAX+ROCm)       DM0.5 训练 (PyTorch+ROCm)
              │                                   │
              ▼                                   ▼
   【阶段四】Pi0.5 HTTP 推理服务          DM0.5 HTTP 推理服务
              │                                   │
              └───────────────┬───────────────────┘
                              ▼
   【阶段五】闭环评测编排   (核心仓库 · run_model_matrix)
     BiGym+3DGS 仿真  ↔  推理服务  →  成功率
```

**三个仓库的职责：**

| 仓库 | 角色 | 框架/栈 |
| --- | --- | --- |
| `rocm_bigym_3dgs`（核心仓库） | 3DGS 外壳生成 + 数据回放采集 + 闭环评测编排 | PyTorch + gsplat + MuJoCo / HIP |
| `rocm_pi05`（openpi 改造） | Pi0.5 微调 + HTTP 推理服务 | **JAX + ROCm**（+ CPU torch） |
| `rocm_dm05`（OpenDM 改造） | DM0.5 微调 + 合并 + 推理 + 评测 | **PyTorch + ROCm** |

**标准化是这条管线能贯通的前提**：三个仓库统一用 LeRobot Dataset v3.0 管数据、统一用 provider-neutral 的 HTTP 接口（`/health` + `/process_frame`，协议 v2）管推理、统一用同一套 BiGym+3DGS 仿真做评测。换模型只改一个服务地址，不动仿真与录像代码——这也是后面能公平对比两个模型的根本原因。

## 阶段一：3DGS 外壳生成

机器人要学会操作家电，必须先有一个足够真实的环境去反复练习。真实厨房太贵、不可重复、也不安全；纯仿真厨房又太假。3DGS（3D Gaussian Splatting）能从一组真实照片合成出接近照片级的新视角，于是我们用它把一个真实商业厨房重建出来搬进仿真。

这里用到的重建器是 **OpenSplat**。OpenSplat 官方不支持 AMD ROCm/HIP，**我们对其做了 AMD 适配改造**（构建补丁 `reconstruction/patches/opensplat-rocm-home.patch`、`opensplat-force-rocm-include.patch`，使其能在 gfx1100 上用原生 HIP 后端编译运行），并在改造后的 OpenSplat 上完成了从重建到采集、评测的全链路。整段重建在单张 W7900D 上完成。

这里有一个关键工程判断：3DGS 在管线里出现在**两个完全不同的阶段**，必须分开处理。第一阶段是从照片训练高斯模型并导出的「训练重建」，用的是 **改造后的 OpenSplat 原生 HIP 后端**——因为 gsplat 在 gfx1100 的 wave32 目标上会触发 rocPRIM 的 wave64 静态断言、官方预编译 wheel 也不含 gfx1100 代码对象，连编译都过不了。第二阶段是 BiGym 运行时三相机的实时「渲染」，用的是 **gsplat 1.4 + 我们打的 gfx1100 兼容补丁**（详见后文「AMD/ROCm 工程要点」）。两步各自验收、互不替代：能 import gsplat 不算通过，必须真正跑通一次栅格化、做 GPU 同步、验证输出有效。

第二个关键设计是把真实厨房做成**纯视觉背景**，和物理彻底解耦：MuJoCo 负责物理（碰撞、奖励、控制），3DGS 负责外观，两者合成到同一帧——从 MuJoCo 取相机内外参与分割图，让 gsplat 渲染厨房背景，再依分割图把机器人、工作台和任务物体覆盖回去。回执强制记录背景物理为空（body/geom/collision 三个计数为 0），但这只能证明「3DGS 没进物理世界」，不能替代人眼验收。

![真实厨房原始照片与 3DGS 重建渲染对比](./rocm_bigym_3dgs/docs/images/amd-rocm-heldout-vs-reference.png)

![重建所用真实厨房原始照片拼接](./rocm_bigym_3dgs/docs/images/canonical-source-contact-sheet.jpg)

左上为留出的真实帧、右上为 AMD Radeon PRO W7900D 上训练 15000 步后的重建渲染，左下为重建所用的真实厨房原始照片。

![重建出的 3DGS 厨房自由视角 / 环视绕场飞行](./rocm_bigym_3dgs/docs/images/20260806-205335.gif)

重建并不局限于上面那一个留出视角：相机可围绕场景自由环绕，厨房从连续的任意新视角都能稳定渲染，BiGym 的 Unitree H1 机器人也被合成到工作台前。这段连续的自由视角绕场，是证明 3DGS 房间外壳真正三维、视角一致的最直观证据，而非绑定在单一训练位姿上的固定反向投影。

**实测结果**：从 352 张 1920×1080 照片、训练 15000 步，得到约 145 万个高斯（清理后 1,458,354）的厨房场景，留出视角 **PSNR 27.9、SSIM 0.937**；清理掉投影拉丝与全相机不可见的悬浮离群点后，导出墙/地/顶分层的房间壳。运行时三相机渲染与策略服务同卡共存时仅占约 **2.7 GiB** 显存，不触发 OOM。

## 阶段二：带外壳的数据回放与采集

有了真实厨房外壳，下一步是让机器人在里面干活，把「怎么操作这个家电」录成训练数据。我们用 BiGym（基于 MuJoCo 的双臂人形机器人 H1 + 两个带腕关节夹爪）跑在重建出的 3DGS 厨房里，执行「把餐具从洗碗机收纳到抽屉」任务，从头部和左右手腕三个视角同步录像，对齐到业界主流的 LeRobot v3 格式（状态/动作均 16 维）。

![3DGS 厨房中的 BiGym 机器人运行演示](./rocm_bigym_3dgs/docs/images/bigym-3dgs-runtime-demo.gif)

![餐具任务的头部相机预览](./rocm_bigym_3dgs/docs/images/cutlery-cam-high-preview.gif)

> 完整 31 秒演示视频（含头部、左右腕、外部视角）：[bigym-3dgs-shell-reference.mp4](./rocm_bigym_3dgs/docs/videos/bigym-3dgs-shell-reference.mp4)

这里有个真实且棘手的问题：BiGym 官方演示轨迹**不是「拿来就能用」**——录制时是 BiGym 4.0 / MuJoCo 3.1.5，采集时是 4.1 / 3.10，版本对不上；轨迹里还混了 absolute / delta 两种动作表示。任意一点漂移都会把可播放轨迹变成失败的（reward 归零），照单全收等于把失败数据当训练数据。

解法是一个「只放行真正成功数据」的两阶段 fail-closed 流程：① 先做无相机、无 3DGS 的纯物理预检，只有 reward=1 的轨迹才写入正式采集计划；② delta 源动作转成 absolute 标签并在另一个 absolute 环境核对误差。采集健壮性上，每条 episode 独立落盘（metadata 缓存设 1、成功后立即关闭写入器、可重读才更新进度），杜绝容器重启导致的「视频已存、Parquet 没写完」半成品。

正式采集 32 条前，必须先跑通一条冒烟（683 帧、2052 次 3DGS 渲染），同时满足 replay reward=1.0、三路 H.264 完整解码、3DGS 严格模式零错误零 fallback、渲染次数精确等于（帧数+复位）×3、背景物理为空。全部通过后才启动正式 32 条，最终产出一份干净、标准化、每条都是真实成功样本的数据集，直接喂给两条训练路径。

> **数据集证据边界（诚实声明）**：本次发布的 32 条 LeRobot 回放数据是一份**跨平台参考基线**（manifest `data/manifests/cutlery32-dataset.public.json`，`runtime: reference-baseline`、`status: technical_pass_visual_approval_pending`）——其运行环境为历史对比基线（非 ROCm），**仅用于溯源与对照，不应作为「AMD ROCm 主线训练/采集已验收完成」的证据**。AMD ROCm 主线的对外声明与复现链路以单卡 gfx1100 为准：标准房间重建已在 Radeon 上实机复现（回执 `amd_rocm_reproduction_passed`），核心仓库也提供完整的、面向 AMD 的数据生成工具链（`make collect` / `make validate` 的 gfx1100 原生路径）。但 32 条正式回放在 AMD 上的独立验收（原生 gsplat rasterization、严格三相机回放、全视频解码、人工视觉复核）仍是尚未关闭的独立验收阶段，不会因重建回执通过而自动判定为通过。

## 阶段三：双框架训练（同一数据集，两条 AMD 路径）

同一份 LeRobot v3 数据集，分别走 JAX 与 PyTorch 两条路径在单张 gfx1100 上微调。

### Pi0.5（JAX + ROCm）
针对单卡做了 ROCm-only 端到端交付（开源 `WuChao-2024/openpi_lerobot_plus`，`rocm` 分支）。整套 ROCm 栈只用系统 python3.12 + apt ffmpeg + 一个 `.venv` 装起，**不依赖 conda**；单卡 48 GiB 跑 pi05 必须用 **LoRA**（冻结 base、全参单卡放不下）。落地中还有两项实用改造：**解除 3 相机硬编码**（π05 网络本身无相机数量绑定的学习参数，原仓库写死 3 相机只是预处理硬编码，改造后支持任意命名相机、相机身份只由输入顺序决定），以及**一键 CLI 训练 + HTTP 推理**（`compute_norm_stats.py`/`train_jax.py`/`inference_server.py` 全纯命令行，无需改 config.py），并支持任意 action 维度适配（32 维基模 ↔ 16 维机器人）。

| 指标 | 实测值（Pi0.5 LoRA，horizon 20，bs=4） |
| --- | --- |
| 稳态吞吐 | **1.2 s/step**（≈ 0.83 step/s，≈ 3.33 samples/s） |
| 峰值显存 | **35.3 GiB**（稳态均值 33.6 GiB） |
| 稳态 GPU 利用率 | **95.6%** |
| loss 轨迹 | 0.2649 → ≈0.0165（单调收敛） |

### DM0.5（PyTorch + ROCm）
开源 `Kyrie-w8/amd-bigym-3dgs-opendm`，在 W7900D + ROCm 7.2.1 + PyTorch 2.8 上完成 LoRA（r32/alpha16，全线性模块，micro-batch 12、梯度累积 4、有效 batch 48，10000 步，模型序列长度 896）微调与可恢复续训。我们对 DM0.5 在 AMD 上的训练吞吐做了一轮系统调优，用 ROCprofiler 定位到 GEMM 是最大耗时类别，据此逐项优化：

| 配置 | step 时间 | 吞吐 | 峰值显存 |
| --- | --- | --- | --- |
| 长期参考基线 | 6.430 s | 1.244 samples/s | ~56% |
| 缓存 episode 元数据（序列 896） | 5.614 s | 1.425 samples/s | 57% |
| + 缩短序列 896→880（仅 ReachTarget 吞吐基准实验） | 5.505 s | 1.453 samples/s | 55% |
| + TunableOp 全量 GEMM 形状离线调优回放（**最终**） | **5.169 s** | **1.548 samples/s** | **~55%** |

最终配置较基线**吞吐提升 24.4%**，匹配 ROCprofiler 显示总 kernel 时间 −9.03%、**GEMM 时间 −14.29%**。注：上表"896→880"一行是为隔离软件吞吐而在 ReachTarget 上做的基准实验；正式发布的 CutleryLong 模型训练序列长度保持 **896**。落到正式 CutleryLong 训练（micro-batch 12 × 梯度累积 4，有效 batch 48），实测：吞吐 **1.5295 samples/s**、峰值显存 **28.74 GiB（≈60%）**、稳态 **GPU 利用率 99.47%**（mb12 在 mb8/12/16 同配置扫参中吞吐最高，已设为发布默认）。三项生效的优化是：persistent worker 内缓存 JSONL 元数据（消除逐帧重复解析）、对训练图里实际出现的 90 个 GEMM 形状离线调优 rocBLAS/hipBLASLt 实现后只回放（关闭在线调优，避免每步抖动）。每个 checkpoint 都含 adapter/optimizer/scheduler/trainer state/归一化统计，可精确续训。

## 阶段四：推理服务（AMD 卡上各起一个）

两个模型训练完成后，各自在 AMD 卡上起一个 HTTP 推理服务，对外提供统一的 `/health` + `/process_frame`（协议 v2）接口，接受三路 RGB + 16 维状态、返回有限的 action chunk。这样评测端不用关心后面是哪个框架的模型。

| 指标 | Pi0.5（JAX） | DM0.5（PyTorch） |
| --- | --- | --- |
| 端到端延迟 | **≈240 ms/次**（p50 216 / p95 284） | **438.72 ms/次** |
| 模型前向（去 HTTP/解码） | 150–180 ms | — |
| 持续吞吐 | ≈4.2 次/秒 | — |
| 推理峰值显存 | ≈10 GiB | **12.79 GiB** |
| 推理 GPU 利用率 | — | **67.68%** |

延迟差异主要来自模型架构：Pi0.5 一次前向直接给出 action chunk，端到端 ≈240 ms；DM0.5 是多步 Flow Matching 扩散（发布成功率协议用 10 步；4 步算子基准端到端 438.72 ms），故单次更慢。我们在 DM0.5 推理侧做了三项无损优化——直接加载已合并权重（去掉空 LoRA 包装的冗余 GEMM）、`torch.inference_mode()` 去掉 autograd 记账、Action Expert KV 工作区复用（稳定前缀只拷一次、只更新后缀，省掉每次调用约 10.1 ms 的 `aten::cat`）——且动作张量逐元素不变。优化后 DM0.5 推理（4 步算子基准）端到端 **438.72 ms**、峰值显存 **12.79 GiB**、GPU 利用率 **67.68%**（训练侧则接近打满，见阶段三 99.47%）。

## 阶段五：闭环评测与双模型对比

策略训出来后，最根本的问题是：它到底能不能完成任务？成功率多少？而且必须公平、可复现、对任何模型一视同仁。核心仓库的 `evaluation/bigym-3dgs/src/run_model_matrix.py` 是这条评测编排入口；各模型仓库基于这套中立评测器与 HTTP 协议各自跑闭环，得到下表成功率。

它是一个**真正的闭环**：仿真器把当前三个相机画面、机器人状态和任务指令经 HTTP 发给推理服务，服务返回动作，机器人在仿真里执行，再看任务有没有完成——测的是策略在真实闭环交互里的表现，而非离线指标。最关键的设计是**和模型无关**：推理服务在 `/health` 里自报身份（提供方/模型/版本/适配器哈希），评测前逐项校验并冻结，同一条 episode 内任何字段对不上直接判失败，杜绝「评测中途偷换模型」。

**为什么评测必须拆成两个进程**：JAX（策略）与 PyTorch/gsplat（仿真+3DGS 渲染）各自带一套 ROCm 运行时，塞进同一进程会触发 MIOpen/rocBLAS 符号冲突。因此闭环拆成策略服务与仿真客户端两个独立进程，在单卡上时分共享 GPU，绝不把两者框架栈塞进同一进程——这是评测侧不被任一模型绑死的运行时防线，源码级还有测试断言编排器不出现 `import torch/jax/transformers`。

评测协议：DM0.5 为任务 `DishwasherUnloadCutleryLong`、种子 200000–200049、50 集、20Hz、chunk 16、10 步扩散、execute 8、最大 800 步、序列长度 896；Pi0.5 为同一任务、50 集、带 3DGS 外壳、horizon 20（Pi0.5 未做 native 评测）。评测器支持任意自定义 episode 数，两模型的 50 集结果即基于同一套中立评测代码与同一张 AMD 卡。

**实测成功率（同一 3DGS 外壳、同一份种子口径、单卡 AMD）：**

| 模型（框架） | native BiGym | 带 3DGS 外壳 |
| --- | --- | --- |
| **DM0.5（PyTorch+ROCm）** | **25/50 = 50%** | **20/50 = 40%** |
| **Pi0.5（JAX+ROCm）** | —（未测） | 5/50 = 10% |

这是一组**诚实、未经修饰的公平对比**：同一厨房、同一任务、同一套评测代码、同一张 AMD 卡。DM0.5 在这条长程家务任务上明显更强（3DGS 下 40% vs Pi0.5 的 10%，相对提升约 300%），且从 native 到 3DGS 仅下降 10 个百分点，说明策略对照片级视觉域迁移相当稳健；Pi0.5 用 32 条 demo 做 LoRA 微调，在该长程任务上偏弱。这组数字的价值不在于绝对分高，而在于证明：**两个分属主流框架的 SOTA VLA，都能在单张 Radeon 上完成「数据→训练→推理→闭环评测」的全流程，并给出可量化、可证伪、彼此可比、且显著超过 BiGym 论文基线的成功率**，而不是一段不可复现的演示视频。

评测期整卡资源占用（Pi0.5 + gsplat 同卡）：GPU 利用率 **≈100%**（持续），显存 **38.68 GiB（约占 48 GB 卡的 80%）**恒定（jax 策略预占 ~36 GiB + gsplat/MuJoCo ~2.7 GiB）。DM0.5 的 3DGS 严格端到端运行门禁（seed 200009）单 episode：567 控制步、71 次模型调用、闭环内单次 `policy.infer()` 均值 726.6 ms、墙钟 91.9 s（高于阶段四 4 步独立推理基准的 438.72 ms：该门禁为 10 步、且每调用含评测框架额外开销）。

验收分层独立：服务就绪、契约探针、闭环结果、录像校验、汇总，最后人眼复核三路相机——只有全部通过的正式评测才算数，冒烟和失败轨迹都不是发布证据。

## AMD/ROCm 工程要点

这条管线能跑通，靠的是把几个 gfx1100 / ROCm 专属的硬坑逐个解决（这些正是赛道「Physical AI on AMD」最看重的工程深度）：

- **OpenSplat 的 AMD 适配**：OpenSplat 官方不支持 ROCm/HIP。我们用构建补丁（`opensplat-rocm-home.patch`、`opensplat-force-rocm-include.patch`）让它定位 ROCm 工具链、强制 HIP include，从而在 gfx1100 上用原生 HIP 后端编译运行，支撑了重建→采集→评测全链路。
- **gsplat 1.4.0 的 bfloat16 编译修复**：HIP 内核在 ROCm 7.2.1 编不过，根因在 hipify 机制——它每次从 `cuda/csrc/types.cuh` 重新生成 `hip/csrc/types.cuh`，而 ROCm 7.2.1 已把 `__hip_bfloat16` 重命名为 `hip_bfloat16`，所以改 `hip/csrc/*` 无效（被覆盖），必须在源头 `cuda/csrc/types.cuh` 改 token，再补一个空的 `cooperative_groups/reduce.h` 垫片。编译用仓库自带的 ROCm 编译器 wrapper，不改 `/opt/rocm`。
- **Pi0.5 的 JAX 选型与依赖**：AMD 不在 PyPI 发 ROCm JAX，**JAX 0.6.0（rocm7.0.2）是唯一**既满足 orbax≥0.5 下限、又离 fork 生态最近的版本；**ml-dtypes 必须 0.5.4**（jaxlib 0.6.0 运行时要 `float4_e2m1fn`，0.4.1 会在 `import jax` 崩，是最隐蔽的坑）；torch 走 CPU 以避开 jax-rocm 与 torch-rocm 双 ROCm 运行时符号冲突。
- **训练 segfault 与 autotune**：gfx1100 / jax0.6.0 上 `bs=4 horizon=20` 默认 autotune 会在 step 500–600 `SIGSEGV`（XLA gemm-fusion 自动调优挑到坏内核），设 `XLA_FLAGS=--xla_gpu_autotune_level=1` 关掉它即过，残留偶发用 `--resume` 续跑兜底；**注意该 flag 只能用于训练**，推理设它会让输出全 NaN，推理须用默认 autotune。
- **DM0.5 的 GEMM 调优**：用 TunableOp 对 90 个实际 GEMM 形状离线调优、正式训练只回放，关掉在线调优抖动，把吞吐拉高 24.4%。
- **两进程评测**：JAX 策略与 PyTorch/gsplat 仿真分进程、单卡时分共享，规避 MIOpen/rocBLAS 符号冲突。

## 上游开源社区贡献

比赛期间我们把通用改进拆成小型上游 PR，回馈 gsplat、BiGym、OpenDM 等多个上游项目，重点改善 AMD/ROCm 平台支持；其中 **OpenDM PR #1（共享 DM0.5 policy loader + `/health`/`/process_frame` 协议 v2 服务）已于 2026-08-06 合并进上游 `main`**，是本工作唯一已合并的上游 PR。**完整 PR 清单与每条用处见 [`README_cn.md` § 上游开源贡献](./README_cn.md)**（状态于 2026-08-06 核验，明细亦见核心仓库 `docs/upstream-contributions.md`）。

## 交付物清单

| 交付物 | 位置 / 链接 | 说明 |
| --- | --- | --- |
| 3DGS 厨房外壳 | `eustance/amd-bigym-3dgs-kitchen-shell` @ `amd-rocm-w7900d-20260804` | W7900D 实拍标定；combined shell SHA-256 `67ab42e9…`（CC BY-NC 4.0） |
| DM0.5 权重 | `wangbin08/DM05-BiGym-CutleryLong-50pct` | native 50% / 3DGS 40% 的全量合并 checkpoint |
| Pi0.5 LoRA 权重 | `WuChao-Cauchy/AMD_OpenSource_dishwasher_unload_cutlery_long_pi05_lora` | horizon 20，可直接推理 / 评测；评测版本锁定 `WuChao-Cauchy/pi05_ckpts` rev `b20a8efa` |
| 机器人数据集 | `eustance/openSource_AMD_AI_DevMaster_Hackathon_202608`；`WuChao-Cauchy/bigym_plus` | 32 条 LeRobot v3 `DishwasherUnloadCutleryLong` 成功轨迹（**跨平台参考基线**，`status: technical_pass_visual_approval_pending`；证据边界见「阶段二」） |
| 演示视频 | `rocm_bigym_3dgs/docs/videos/bigym-3dgs-shell-reference.mp4`（31.45s / 1696×960） + 两个 runtime GIF | 三视角运行参考 |
| 三个源码仓库 | `rocm_bigym_3dgs` / `rocm_pi05` / `rocm_dm05` | 见「总体架构」职责表 |

## 基础组件

### BiGym
基于 MuJoCo 的双臂机器人灵巧操作仿真基准，使用宇树 H1 人形机器人配两个 Robotiq 2F-85 夹持器（各带一个驱动腕关节），提供洗碗机、橱柜等铰接式家具的多任务场景与专家演示轨迹，用于数据生成与策略评测。

### 3DGS（3D Gaussian Splatting）
从一组真实照片合成接近照片级新视角的表征方法。本项目中它有两个阶段：改造后的 OpenSplat/HIP 做「训练重建」（导出 PLY 房间壳），gsplat 1.4 + gfx1100 补丁做「运行时三相机渲染」，且只作纯视觉背景、不进物理世界。

### DM0.5（PyTorch 路径）
原力灵机（Dexmal）面向开放世界的具身原生基础大模型，继承 DM0 原生训练路线，面向开放指令、长程任务、动态干扰、多机器人本体。本项目在单张 W7900D 上完成 LoRA 微调（`Kyrie-w8/amd-bigym-3dgs-opendm`）、吞吐调优（+24.4%）与推理无损优化（4 步基准端到端 438.72 ms），3DGS 闭环成功率 40%（native 50%）。

### Pi0.5（JAX 路径）
Physical Intelligence 开源的 VLA 基础模型。本项目针对单张 gfx1100 做了 ROCm-only 端到端改造（`WuChao-2024/openpi_lerobot_plus`）：无需 conda 的 `.venv+apt` 路线、任意相机数量、一键 CLI 训练+HTTP 推理、任意 action 维度适配，并放出可直接推理的 LoRA 权重。3DGS 闭环成功率 10%。



---

## Team Contributions

- Team Name: KINESYS
- Application Name: RoboNativeManipulation
- Note: All members are registered in the AMD Developer Program at https://developer.amd.com.cn.

| Contributor | AMD Developer Program | GitHub | Contribution |
|-------------|-----------------------|--------|--------------|
| Bin Wang    | No. 00037411          | Kyrie-w8 | Built the DM0.5 model on AMD ROCm (PyTorch) and produced a working robot policy. |
| LongTao Wu  | No. 00039028          | eust-w | Built the BiGym data pipeline and the reproducible closed-loop evaluation, and prototyped the 3DGS scene-reconstruction pipeline (incl. the OpenSplat AMD adaptation) for photorealistic data augmentation. |
| Chao Wu     | No. 00037405          | WuChao-2024 | Built the Pi0.5 model on AMD ROCm (JAX) and produced a working robot policy.  |

---

## 许可证

### 仓库

| 名称 | 网址 | 协议 |
|------|------|------|
| Physical-Intelligence/openpi | https://github.com/Physical-Intelligence/openpi | Apache-2.0 |
| NeuracoreAI/bigym | https://github.com/NeuracoreAI/bigym | Apache-2.0 |
| dexmal/opendm | https://github.com/dexmal/opendm | Apache-2.0 |
| eust-w/amd-bigym-openpi-eval | https://github.com/eust-w/amd-bigym-openpi-eval | Apache-2.0 |
| WuChao-2024/openpi_lerobot_plus | https://github.com/WuChao-2024/openpi_lerobot_plus | Apache-2.0 |
| WuChao-2024/bigym_plus | https://github.com/WuChao-2024/bigym_plus | Apache-2.0 |

### 权重

| 名称 | 网址 | 协议 |
|------|------|------|
| pi0 / pi0.5 base | https://huggingface.co/physical-intelligence/pi0.5 | Gemma Terms of Use |
| Dexmal DM0.5 | https://huggingface.co/Dexmal/DM05 | Gemma Terms of Use |
| Gemma / PaliGemma | https://ai.google.dev/gemma/terms | Gemma Terms of Use |

### 数据集

| 名称 | 网址 | 协议 |
|------|------|------|
| openSource_AMD_AI_DevMaster_Hackathon_202608 | https://huggingface.co/datasets/WuChao-Cauchy/openSource_AMD_AI_DevMaster_Hackathon_202608 | CC BY-NC 4.0 |
| bigym_plus_datasets | https://huggingface.co/datasets/WuChao-Cauchy/bigym_plus_datasets | CC BY-NC 4.0 |
| BiGym demos | https://github.com/NeuracoreAI/bigym_data | Apache-2.0 |
| DL3DV-10K | https://github.com/DL3DV-10K/Dataset | CC BY-NC 4.0 |
| amd-bigym-3dgs-kitchen-shell | https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell | CC BY-NC 4.0 |

注：上述两数据集的视觉观测含源自 DL3DV（CC-BY-NC）的重建背景，机器人轨迹源自 BiGym（Apache-2.0）演示，故整体沿用 CC-BY-NC 4.0 条款，下游须遵守非商用限制并保留来源署名。

### 库

| 名称 | 网址 | 协议 |
|------|------|------|
| MuJoCo | https://github.com/google-deepmind/mujoco | Apache-2.0 |
| JAX | https://github.com/google/jax | Apache-2.0 |
| PyTorch | https://github.com/pytorch/pytorch | BSD-3-Clause |
| LeRobot | https://github.com/huggingface/lerobot | Apache-2.0 |
| gsplat | https://github.com/nerfstudio-project/gsplat | Apache-2.0 |
| OpenSplat | https://github.com/pierotofy/OpenSplat | GPL-3.0 |
| Liger Kernel | https://github.com/linkedin/Liger-Kernel | BSD-2-Clause |
| transformers | https://github.com/huggingface/transformers | Apache-2.0 |
| Flax | https://github.com/google/flax | Apache-2.0 |
| Orbax | https://github.com/google/orbax | Apache-2.0 |
| Chex | https://github.com/deepmind/chex | Apache-2.0 |
| Optax | https://github.com/deepmind/optax | Apache-2.0 |
| ml-dtypes | https://github.com/jax-ml/ml_dtypes | Apache-2.0 |
