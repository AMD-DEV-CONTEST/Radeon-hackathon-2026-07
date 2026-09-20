# RoboNativeManipulation — KINESYS · AMD AI DevMaster Hackathon · Track 3（Physical AI）

> English：`README.md` · **简体中文：本文件 `README_cn.md`**

让机器人在照片级真实的家庭场景里学会操作家电。本项目构建一条**「真实场景 3DGS 重建 → 数据回放采集 → 双框架 VLA 后训练 → AMD 单卡推理 → 闭环评测」**的端到端管线，全部关键阶段在**单张 AMD Radeon PRO W7900D（gfx1100，48 GB）+ ROCm 7.2.1** 上跑通。

**一句话成果**：同卡、同种子、同一 3DGS 外壳下——DM0.5（PyTorch+ROCm）在原生干净场景达 **50%** 成功率、在带 3DGS 外壳的更难视觉域达 **40%**；Pi0.5（JAX+ROCm）在带外壳场景给出 **10%** 基线；3DGS 外壳重建留出视角 **PSNR 27.9 / SSIM 0.937**。

> 完整技术叙事、系统架构、各阶段详解、BiGym 论文基线对比与上游开源贡献，见**技术报告 [`TechnologyReport_cn.md`](./TechnologyReport_cn.md)**。


---

## 本次提交包含什么（交付物索引）

| 交付物 | 文件 | 说明 |
| --- | --- | --- |
| 技术报告（中） | [`TechnologyReport_cn.md`](./TechnologyReport_cn.md) | 主报告（深度叙事 + 证据） |
| 技术报告（英） | [`TechnologyReport.md`](./TechnologyReport.md) | 英文版 |
| 可复现 README（中） | `README_cn.md`（本文件） | 英文版 `README.md` 已就绪 |
| 源代码 · 核心仓库 | [`rocm_bigym_3dgs/`](./rocm_bigym_3dgs/README.md) | 3DGS 外壳生成 + 数据回放采集 + 闭环评测编排（PyTorch + gsplat + MuJoCo/HIP）· [eust-w/amd-bigym-3dgs-rocm](https://github.com/eust-w/amd-bigym-3dgs-rocm) |
| 源代码 · Pi0.5 | [`rocm_pi05/`](./rocm_pi05/README.md) | Pi0.5 LoRA 微调 + HTTP 推理（**JAX + ROCm**）· [WuChao-2024/openpi_lerobot_plus](https://github.com/WuChao-2024/openpi_lerobot_plus) |
| 源代码 · DM0.5 | [`rocm_dm05/`](./rocm_dm05/README.md) | DM0.5 微调 + 合并 + 推理 + 评测（**PyTorch + ROCm**）· [Kyrie-w8/amd-bigym-3dgs-opendm](https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm) |
| 流程总览图 | [`assets/Flat_combined.jpg`](./assets/Flat_combined.jpg) | 管线一图概览 |
| 演示视频 | _（待补）_ | 规则要求 3–5 分钟，展示命令行/运行流程与结果 |

---

## 如何复现

整条管线由三个仓库协同完成，**每个仓库都有自洽、权威的 README**。下表只做导航——告诉你要做哪一步、能得到什么、该看哪份文档；**具体命令、参数与 ROCm 踩坑都在那份文档里，此处不重复**。

| # | 阶段 | 你将得到什么 | 跟随文档（权威源） |
| --- | --- | --- | --- |
| 1 | 3DGS 外壳重建 | 照片级厨房外壳：352 张 1080p → 清理后约 145 万高斯，留出视角 **PSNR 27.9 / SSIM 0.937** | [`rocm_bigym_3dgs/docs/05-3d-reconstruction.md`](./rocm_bigym_3dgs/docs/05-3d-reconstruction.md)（另见 [`reconstruction/README.md`](./rocm_bigym_3dgs/reconstruction/README.md) 与该仓库 README 的「AMD/ROCm quick start」） |
| 2 | 外壳导入 BiGym | 三相机（头/双腕）视觉外壳合成，严格渲染无回退，不新增物理/碰撞 | [`rocm_bigym_3dgs/docs/06-shell-import.md`](./rocm_bigym_3dgs/docs/06-shell-import.md) |
| 3 | 数据回放与采集 | 32 条 LeRobot v3 `DishwasherUnloadCutleryLong` 轨迹（fail-closed，只放行真正成功的数据） | [`rocm_bigym_3dgs/docs/03-collection.md`](./rocm_bigym_3dgs/docs/03-collection.md)（`make collect` / `make validate`） |
| 4a | Pi0.5 训练（JAX+ROCm） | Pi0.5 LoRA 策略权重（horizon 20） | [`rocm_pi05/docs/amd_rocm_jax.md`](./rocm_pi05/docs/amd_rocm_jax.md) |
| 4b | DM0.5 训练（PyTorch+ROCm） | 合并后的 DM0.5 全量策略 | [`rocm_dm05/README.md`](./rocm_dm05/README.md) §3「Train and merge」（另见 [`docs/training_optimization.md`](./rocm_dm05/docs/training_optimization.md)） |
| 5 | 推理服务 | provider-neutral HTTP 服务：`/health` + `/process_frame`（协议 v2） | Pi0.5：[`rocm_pi05/docs/amd_rocm_bigym_eval.md`](./rocm_pi05/docs/amd_rocm_bigym_eval.md)；DM0.5：[`rocm_dm05/README.md`](./rocm_dm05/README.md) §5「Optional HTTP provider」 |
| 6 | 闭环评测 | 成功率：DM0.5 native **50%** / 3DGS **40%**；Pi0.5 3DGS **10%** | DM0.5 自带确定性评测 [`rocm_dm05/README.md`](./rocm_dm05/README.md) §4「Evaluate」（`run_amd_eval.sh`）；Pi0.5 + 双模型同场对比 [`rocm_bigym_3dgs/docs/07-evaluation.md`](./rocm_bigym_3dgs/docs/07-evaluation.md)（+ [`evaluation/bigym-3dgs/README.md`](./rocm_bigym_3dgs/evaluation/bigym-3dgs/README.md)） |

> - **两进程评测是硬约束**：JAX 策略与 PyTorch/gsplat 仿真各带一套 ROCm 运行时，放进同一进程会触发 MIOpen/rocBLAS 符号冲突。策略作为服务、仿真作为独立进程、两者分时共享一张卡——这正是评测器不绑定任一框架的根本原因。HTTP 契约见 [`evaluation/bigym-3dgs/INFERENCE_PROTOCOL.md`](./rocm_bigym_3dgs/evaluation/bigym-3dgs/INFERENCE_PROTOCOL.md)。
> - **环境与依赖**：各仓库 README 的环境段 + 各自依赖清单（如 [`rocm_pi05/requirements_rocm.txt`](./rocm_pi05/requirements_rocm.txt)）+ [`rocm_bigym_3dgs/docs/08-repository-revisions.md`](./rocm_bigym_3dgs/docs/08-repository-revisions.md)（锁定的仓库 / 分支 / commit 台账）。
> - **评测口径**：任务 `DishwasherUnloadCutleryLong`，种子 `200000–200049`，20 Hz，chunk 16，最长 800 步，单一 3DGS 外壳，单卡。
> - **数据集证据边界（诚实声明）**：本次发布的 32 条 LeRobot 回放数据是一份**跨平台参考基线**（`runtime: reference-baseline`、`status: technical_pass_visual_approval_pending`，运行环境为历史对比基线、非 ROCm），仅作溯源/对照，**不应作为「AMD ROCm 主线训练/采集已验收完成」的证据**。AMD ROCm 主线以单卡 gfx1100 为准——标准房间重建已实机复现（回执 `amd_rocm_reproduction_passed`）；32 条回放在 AMD 上的独立验收（严格三相机回放 + 人工视觉复核）仍是尚未关闭的阶段。详见技术报告「阶段二」。

---

## 硬件与软件

- **GPU**：AMD Radeon PRO W7900D，`gfx1100`，48 GB（整条管线单卡）
- **ROCm**：7.2.1
- **框架**：Pi0.5 用 **JAX 0.6.0（rocm7.0.2）**；DM0.5 / gsplat 用 **PyTorch 2.8（ROCm）**
- **仿真 / 数据**：MuJoCo 3.10、BiGym 4.1、LeRobot 0.6.0、gsplat 1.4.0、OpenSplat（HIP）
- **机器人**：Unitree H1 人形 + 两个 Robotiq 2F-85 夹爪（BiGym）

---

## 发布产物

| 产物 | 位置 |
| --- | --- |
| DM0.5 全量 checkpoint（native 50% / 3DGS 40%） | [`wangbin08/DM05-BiGym-CutleryLong-50pct`](https://huggingface.co/wangbin08/DM05-BiGym-CutleryLong-50pct) |
| Pi0.5 LoRA 权重（horizon 20） | [`WuChao-Cauchy/AMD_OpenSource_dishwasher_unload_cutlery_long_pi05_lora`](https://huggingface.co/WuChao-Cauchy/AMD_OpenSource_dishwasher_unload_cutlery_long_pi05_lora) |
| 3DGS 厨房外壳（CC BY-NC） | [`eustance/amd-bigym-3dgs-kitchen-shell`](https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell/tree/amd-rocm-w7900d-20260804)（rev `amd-rocm-w7900d-20260804`） |
| 机器人数据集 | [`openSource_AMD_AI_DevMaster_Hackathon_202608`](https://huggingface.co/datasets/WuChao-Cauchy/openSource_AMD_AI_DevMaster_Hackathon_202608)、[`bigym_plus_datasets`](https://huggingface.co/datasets/WuChao-Cauchy/bigym_plus_datasets) |

---

## 上游开源贡献

比赛期间我们把通用改进拆成小型上游 PR，回馈多个上游项目，重点改善 AMD/ROCm 平台支持（对应评分维度「上游开源社区贡献」）。下表状态于 2026-08-06 核验；明细亦见核心仓库 [`docs/upstream-contributions.md`](./rocm_bigym_3dgs/docs/upstream-contributions.md)。

| 上游项目 | PR | 做了什么 / 解决什么 |
| --- | --- | --- |
| [`nerfstudio-project/gsplat`](https://github.com/nerfstudio-project/gsplat) | [#1046](https://github.com/nerfstudio-project/gsplat/pull/1046) | 让 ROCm JIT 编译参数更兼容：区分 CUDA 与 ROCm 编译标志（fast-math、lineinfo、nvcc 专属警告/参数），修复 hipcc 报错来源，给 AMD 路径提供可用的编译参数集合；新增 CPU-only 构建参数测试。 |
| 同上 | [#1045](https://github.com/nerfstudio-project/gsplat/pull/1045) | 修复 lazy backend 的 ROCm 工具链探测：正确识别 hipcc，优先用 `torch.version.hip` 提供的 `ROCM_HOME` 并支持 PATH fallback，避免探测失败就把 gsplat 判为不可用；保持 CUDA nvcc 分支行为不变。 |
| [`NeuracoreAI/bigym`](https://github.com/NeuracoreAI/bigym) | [#65](https://github.com/NeuracoreAI/bigym/pull/65) | 支持可配置相机 FOV 与大分辨率观测：新增 fovy 配置、按配置扩展 MuJoCo framebuffer，支持大图观测，防止大分辨率相机初始化失败。 |
| 同上 | [#64](https://github.com/NeuracoreAI/bigym/pull/64) | fallback 转换按请求 demo 数量加载（而非全量）：降低内存与 I/O，避免只要 1–2 个 demo 也反序列化全部文件；附回归测试。 |
| 同上 | [#63](https://github.com/NeuracoreAI/bigym/pull/63) | 补一个无头 EGL 像素渲染基准：文档 + 脚本 + 验收，用于 GPU 像素观测的可复现性能/正确性 smoke 测试。 |
| 同上 | [#62](https://github.com/NeuracoreAI/bigym/pull/62) | 修复 demo recorder 状态机：save 成功后停止录制并重置状态，失败时保持可重试状态。 |
| 同上 | [#61](https://github.com/NeuracoreAI/bigym/pull/61) | demonstration 保存原子化：改成 temp 写入 + `os.replace`，减少损坏文件风险；增加异常场景回归。 |
| [`Kyrie-w8/amd-bigym-3dgs-opendm`](https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm) | [#1](https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm/pull/1) | 抽取共享 DM0.5 policy loader，提供 `/health` 与 `/process_frame` 协议 v2 服务——**已于 2026-08-06 合并进上游 `main`**（合并 commit `8f018b25…`），是本工作唯一已合并的上游 PR。 |

> - 除 OpenDM #1 已合并外，上述 gsplat / bigym PR 当前为 open（待评审）。
> - 我们还为 [`pierotofy/OpenSplat`](https://github.com/pierotofy/OpenSplat) 做了 AMD ROCm/HIP 构建适配（`opensplat-rocm-home.patch`、`opensplat-force-rocm-include.patch`，见核心仓库 `reconstruction/patches/`），使其在 gfx1100 上用原生 HIP 后端编译运行——属本地工作分支补丁，尚未提交为上游 PR。gsplat 的 gfx1100 运行时补丁 `gsplat-1.4.0-rocm-gfx1100.patch` 同属本地分支，与上表两个 gsplat 上游 PR 是不同改动。

---

## 许可证

仓库代码为 Apache-2.0（除非文件另行注明）。上游衍生资产保留各自条款：3DGS 外壳资产 CC BY-NC 4.0（+ DL3DV 条款）；模型权重 Gemma Terms of Use；BiGym 演示保留上游条款。**Git 树内不分发任何模型权重或大型场景资产。** 完整许可证表（仓库 / 权重 / 数据集 / 库）见技术报告。

> 注：发布的两数据集（`openSource_AMD_AI_DevMaster_Hackathon_202608`、`bigym_plus_datasets`）采用 CC BY-NC 4.0——其视觉观测含源自 DL3DV（CC-BY-NC）的重建背景，机器人轨迹源自 BiGym（Apache-2.0）演示，故整体沿用 CC-BY-NC 4.0 条款，下游须遵守非商用限制并保留来源署名。
