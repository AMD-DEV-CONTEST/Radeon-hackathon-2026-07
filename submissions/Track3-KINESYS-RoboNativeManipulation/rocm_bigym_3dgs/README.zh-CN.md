<div align="center">
  <h1>AMD Radeon BiGym + 3DGS 厨房环境</h1>
  <p><strong>从 DL3DV 厨房重建到可替换策略的 AMD ROCm 闭环评测</strong></p>
  <p>
    <a href="https://github.com/eust-w/amd-bigym-3dgs-rocm/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/eust-w/amd-bigym-3dgs-rocm/ci.yml?branch=main&amp;style=flat-square&amp;label=CI" alt="CI 状态"></a>
    <a href="evidence/amd-rocm-main-status.json"><img src="https://img.shields.io/badge/Reproduction-passed-22C55E?style=flat-square" alt="AMD 复现通过"></a>
    <a href="evidence/amd-rocm-main-status.json"><img src="https://img.shields.io/badge/AMD%20Radeon%20PRO-W7900D-ED1C24?style=flat-square&amp;logo=amd&amp;logoColor=white" alt="AMD Radeon PRO W7900D"></a>
    <a href="reconstruction/README.md"><img src="https://img.shields.io/badge/ROCm-HIP%20%7C%20gfx1100-6F42C1?style=flat-square" alt="ROCm HIP gfx1100"></a>
    <a href="patches/bigym-3dgs-shell-and-collector.patch"><img src="https://img.shields.io/badge/BiGym-4.1-2563EB?style=flat-square" alt="BiGym 4.1"></a>
    <a href="#amdrocm-快速开始"><img src="https://img.shields.io/badge/MuJoCo-3.10-0891B2?style=flat-square" alt="MuJoCo 3.10"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/Code%20license-Apache--2.0-F59E0B?style=flat-square" alt="Apache 2.0 代码许可"></a>
    <a href="https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell/tree/amd-rocm-w7900d-20260804"><img src="https://img.shields.io/badge/Hugging%20Face-AMD%20artifacts-FFD21E?style=flat-square" alt="Hugging Face AMD 产物"></a>
  </p>
  <p>
    <a href="#bigym--3dgs-运行演示">运行演示</a> ·
    <a href="#amd-radeon-实机复现">AMD 结果</a> ·
    <a href="#amdrocm-快速开始">快速开始</a> ·
    <a href="#仓库校验">仓库校验</a> ·
    <a href="https://github.com/eust-w/amd-bigym-3dgs-rocm/tree/main">AMD/ROCm main</a>
  </p>
  <p><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a></p>
</div>

这是 AMD Radeon/ROCm 端到端主实现：重建 DL3DV 厨房、在 BiGym 中加载
3D Gaussian 房间壳、连接外部策略进行闭环评测、录制三相机并校验完整轨迹。
下面的重建结果和可下载 shell 均由 AMD Radeon PRO W7900D 生成。

## BiGym + 3DGS 运行演示

[![3DGS 厨房中的 BiGym 机器人与洗碗机工作台动态演示](docs/images/bigym-3dgs-runtime-demo.gif)](docs/videos/bigym-3dgs-shell-reference.mp4)

上面的 6 秒动态图会在 GitHub 内直接循环播放。点击即可观看完整的
[31 秒、`1696x960` MP4](docs/videos/bigym-3dgs-shell-reference.mp4)，其中同时
包含头部第一视角、左右腕部相机和外部视角。该视频仅作为运行集成效果参考，
不代表独立的 32 条采集已经通过 AMD 回放验收。

## AMD Radeon 实机复现

![DL3DV 留出原图与 AMD ROCm 15000-step 重建渲染对比](docs/images/amd-rocm-heldout-vs-reference.png)

左侧是 `1920x1080` 留出原图，右侧是 AMD Radeon PRO W7900D 上
OpenSplat/HIP 训练 15,000 steps 的渲染结果。清晰预览门禁以 PSNR
`27.9066`、SSIM `0.9370` 通过；导出 shell 前已去除明显投影拉丝点和
1 个所有相机均不可见的空间离群点。

| AMD 结果 | 已校验值 |
| --- | --- |
| GPU | AMD Radeon PRO W7900D，`gfx1100` |
| 运行时 | PyTorch ROCm/HIP |
| 重建 | 352 张 `1920x1080` 图像，OpenSplat 15,000 steps |
| 清理后结果 | 1,458,354 个 Gaussian |
| 房间壳 | 中央 `3x3m` 工作区净空，新增物理/碰撞为 0 |
| 机器状态 | `amd_rocm_reproduction_passed` |

## 源素材

![DL3DV 商业厨房源轨迹抽样视图](docs/images/canonical-source-contact-sheet.jpg)

该联系表用于溯源。本 README 中的 PLY 下载和 BiGym shell 配置始终
指向下方锁定的 AMD Hugging Face revision。

32 条 LeRobot 重放数据来自 `data/manifests/cutlery32-dataset.public.json`，
其 manifest 标注了 `status: "technical_pass_visual_approval_pending"`，且属于参考采集工单；
该条目不应当作 AMD ROCm 主线训练完成证据。

## AMD 证据边界

| 产物 | 当前结论 |
| --- | --- |
| GitHub `main` | AMD 重建代码、回执和可复现校验 |
| HF revision `amd-rocm-w7900d-20260804` | AMD 清理后 PLY、分层/合并 shell、alignment、profile 和预览 |
| BiGym 采集 | 不由重建回执自动提升；三相机采集是独立验收阶段 |

标准房间重建现在已在 Radeon 上实机复现。但这**不代表**
32 条采集已经在 AMD 上重放：后续采集验收仍要通过原生 gsplat
rasterization、严格三相机回放、全视频解码和独立人工视觉检查。

AMD 机器可读状态见
[`evidence/amd-rocm-main-status.json`](evidence/amd-rocm-main-status.json)。

## 唯一标准输入

| 内容 | 唯一标准 |
| --- | --- |
| AMD 3DGS 房间壳 | [HF revision `amd-rocm-w7900d-20260804`](https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell/tree/amd-rocm-w7900d-20260804) |
| DL3DV 来源 | [DL3DV/DL3DV-ALL-2K](https://huggingface.co/datasets/DL3DV/DL3DV-ALL-2K)，revision `e035bc5efd8dc5b2fa1e704cb2b1086fd9ec2c5c` |
| Scene hash | `90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947` |
| AMD 清理后重建 | 1,458,354 个 Gaussian，SHA-256 `d49bcf7219f63a92ee0d40f8d86e618176892ec89853fecc5e217829bff42b9b` |
| AMD 合并 shell | 1,458,255 个 Gaussian，SHA-256 `67ab42e99833749d17db499f4ea1c968b193db26760f567244632f41ae58cb17` |

由于标准素材继续受 DL3DV 和其他上游条款约束，两个 Hugging Face 仓库保持
人工审批下载。

## AMD/ROCm 快速开始

目标环境：

- 能报告 `gfx1100` 的 AMD Radeon GPU；
- AMD Radeon `gfx1100` 上的 ROCm PyTorch；
- 重建使用 OpenSplat commit
  `9fb62fde8b7b8c416121d3cbdcda278ffd9682f7`；
- 下游运行时渲染使用 Python 3.12、MuJoCo 3.10、BiGym 4.1 和
  gsplat 1.4。

先构建 OpenSplat 原生 HIP trainer，下载精确锁定的受控源包，然后运行 AMD
端到端重建：

```bash
git clone https://github.com/pierotofy/OpenSplat.git /root/OpenSplat
git -C /root/OpenSplat checkout --detach \
  9fb62fde8b7b8c416121d3cbdcda278ffd9682f7
export OPENSPLAT_SOURCE=/root/OpenSplat
make build-opensplat

hf auth login
make download-reference-data
cp reconstruction/config/rocm.env.example .rocm.env
set -a && source .rocm.env && set +a
make reconstruct-rocm
```

只有回执状态为 `amd_rocm_reproduction_passed` 才算重建通过；精确门禁见
[`reconstruction/README.md`](reconstruction/README.md)。

下载锁定 HF revision 上的 AMD shell，根据
[`evidence/amd-rocm-main-status.json`](evidence/amd-rocm-main-status.json)
核对哈希，然后生成 AMD 运行目录：

```bash
hf auth login
hf download eustance/amd-bigym-3dgs-kitchen-shell \
  --repo-type dataset --revision amd-rocm-w7900d-20260804 \
  --local-dir data/private/amd-rocm-kitchen-shell

export SHELL_WALLS="$PWD/data/private/amd-rocm-kitchen-shell/walls_fixed_kitchen.ply"
export SHELL_FLOOR="$PWD/data/private/amd-rocm-kitchen-shell/floor_perimeter.ply"
export SHELL_CEILING="$PWD/data/private/amd-rocm-kitchen-shell/ceiling_lights.ply"
export SHELL_DIR="$PWD/data/private/amd-runtime-shell"
make stage-shell
```

只有原生 AMD 渲染门禁通过后，才能运行 32 条标准 replay plan：

```bash
export REPLAY_PLAN=/absolute/path/to/cutlery32-replay-plan.json
export DATASET_ROOT=/absolute/path/to/amd-cutlery32
make collect
make validate
```

回放失败必须继续排除；已发布的 AMD 重建回执不会将独立的
32 条回放阶段误标为通过。

## 已实现内容

- 不修改 `/opt/rocm` 的隔离编译器 wrapper；
- 在 `gfx1100` 上锁定 OpenSplat 原生 HIP 重建；
- held-out PSNR/SSIM 与保守的全相机不可见异常点清理；
- `gsplat==1.4.0` `gfx1100` 兼容补丁和真实 rasterization smoke；
- 不增加 MuJoCo 物理对象的 BiGym 纯视觉 shell 合成；
- 禁止 fallback 的 head、左右腕部三相机严格渲染；
- 外部推理 HTTP v2 客户端契约；本分支不包含模型运行时或权重；
- 闭环评测、三相机同步 MP4、追加式轨迹与原子 manifest；
- 不同 demonstration 的 replay plan 校验；
- LeRobot v3 结构、有限数值和全视频解码校验；
- CI 使用的无数据许可 CPU 合成重建 smoke。

ROCm 构建边界见 [`docs/02-rocm-gsplat.md`](docs/02-rocm-gsplat.md)，坐标与
合成路径见 [`docs/01-end-to-end.md`](docs/01-end-to-end.md)。

## 端到端闭环评测

主仓库已经打通重建、房间壳、外部推理、BiGym 闭环、三相机录像、轨迹和结果校验：

```text
DL3DV -> OpenSplat/HIP -> AMD 3DGS 房间壳 -> BiGym/MuJoCo
                                                   ^
外部推理服务 -> HTTP protocol v2 ------------------+
                                                   |
                           MP4 + JSONL + manifest + 校验
```

先准备仿真侧，并指向仓库外部的推理服务：

```bash
export AMD_PIPELINE_ROOT=/workspace/amd-bigym-3dgs-rocm
export INFERENCE_PROVIDER=external
export INFERENCE_BASE_URL=http://127.0.0.1:7891
export INFERENCE_GPU=0
export SIM_GPU=0

make eval-preflight
make eval-bootstrap
make eval-download-shell
```

在本分支之外启动兼容服务后，依次运行 `make eval-probe`、`make eval-smoke` 和
`make eval-formal`。客户端协议见
[`evaluation/bigym-3dgs/INFERENCE_PROTOCOL.md`](evaluation/bigym-3dgs/INFERENCE_PROTOCOL.md)。
原先随仓库提供的推理实现完整保留在
[`interence`](https://github.com/eust-w/amd-bigym-3dgs-rocm/tree/interence)
分支。

## 仓库校验

仿真评测主线现在与模型无关，位于
[`evaluation/bigym-3dgs/`](evaluation/bigym-3dgs/README.zh-CN.md)。这里只保留外部
服务客户端、协议探针、BiGym 闭环、录像和校验器；本分支不跟踪模型服务器、推理
框架、权重或下载器。任意兼容服务均可通过 `INFERENCE_BASE_URL` 接入，不需要修改
录像与校验代码，且运行时仍与 PyTorch/gsplat 仿真器保持为独立进程。
可复用的上游 BiGym 改进状态单独记录在
[`docs/upstream-contributions.md`](docs/upstream-contributions.md)。

默认先跑 3 条 smoke，再以 32 个不同 seed 正式评测
`DishwasherUnloadCutleryLong`。评测器也支持任意正整数条数；32 条是可横向比较的
正式 benchmark 口径，不是代码限制。

新版评测器会把每次 reset 和 transition 立即写入追加式 JSONL，并同步录制 head、
left wrist、right wrist 三路 MP4；状态、模型动作、环境动作、裁剪动作与 mask、
reward、成功/终止标记、info、请求 ID，以及客户端与服务端推理耗时都会保留。
每个 transition 都会显式标明动作前/后的 16 维状态、MuJoCo 时间，以及动作前后
画面所在的记录序号，避免把下一帧错配为当前动作输入。每条 episode 有原子
manifest、代码/权重身份、视频元数据和 SHA-256。任务失败轨迹不会被丢弃或冒充
成功；旧的摘要型评测必须重新运行，才能补齐这些原本没有采集的数据。

默认分支只发布通过正式评测、完整录像校验和三相机人工验收的策略回执。smoke 与
任务失败轨迹仅保留在本地结果目录用于诊断，不作为仓库发布证据。

```bash
make verify
make verify-evaluation
make smoke-reconstruction
python scripts/check_markdown_links.py
```

GitHub CI 会检查公开文件哈希、JSON 契约、两个补丁、Markdown 链接和无许可依赖
的 shell exporter；真实 Radeon GPU 结果另有机器可读回执和不可变哈希。

## 许可

代码默认采用 Apache-2.0。DL3DV 源数据、派生房间壳、预览和采集画面继续受
CC BY-NC 4.0 与 DL3DV 现行条款约束；BiGym demonstrations 保留上游许可。
