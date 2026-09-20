# AMD 上与模型无关的 BiGym + 3DGS 闭环评测

该目录负责统一的仿真评测侧：BiGym/MuJoCo、ROCm PyTorch + gsplat、AMD
3DGS 厨房壳、闭环执行、三相机 MP4、完整轨迹、原子 manifest、哈希和结果校验。

推理实现不再和评测代码混在一起。该目录只包含外部服务客户端、协议探针、BiGym
闭环、录像和校验器；统一接口见 [`INFERENCE_PROTOCOL.md`](INFERENCE_PROTOCOL.md)。
本分支不包含模型运行时、权重、下载器或推理服务器。

## 运行结构

```text
第三方推理进程                         BiGym 评测进程
/health + /process_frame   <------->  MuJoCo + 严格 3DGS 三相机
模型/权重/推理框架                     录像 + 轨迹 + manifest + 校验
```

推理服务必须位于本分支之外，运行时也应与 PyTorch/gsplat ROCm 仿真器保持为
两个独立进程。

## 快速开始

```bash
export AMD_PIPELINE_ROOT=/workspace/amd-bigym-3dgs-rocm
export INFERENCE_PROVIDER=external
export INFERENCE_BASE_URL=http://127.0.0.1:7891
export INFERENCE_GPU=0
export SIM_GPU=0

./evaluation/bigym-3dgs/bin/preflight_amd.sh
./evaluation/bigym-3dgs/bin/bootstrap_bigym_source.sh
export VENV=/workspace/amd-bigym-3dgs/.venv
./evaluation/bigym-3dgs/bin/bootstrap_bigym_runtime.sh
hf auth login
./evaluation/bigym-3dgs/bin/download_shell.sh

# 在本分支之外启动兼容推理服务后：
./evaluation/bigym-3dgs/bin/probe_inference.sh
./evaluation/bigym-3dgs/bin/run_eval.sh smoke
./evaluation/bigym-3dgs/bin/run_eval.sh formal
```

标准比较口径仍是 32 个不同 seed；代码支持任意正整数条数。每条 episode 都会
保存 head、left wrist、right wrist 三路视频、逐步 JSONL、动作前后状态、
reward/done/info、请求 ID、推理耗时、原子 manifest 和 SHA-256。任务失败轨迹
保留用于诊断，但不能冒充成功示范数据。

`evidence/` 只允许提交通过完整录像校验、结果校验和三相机人工验收的正式评测
回执。smoke、中断运行和任务失败轨迹仅留在本地结果目录；当前版本不包含已验收的
正式策略评测回执。

原先随仓库提供的模型推理实现和兼容入口完整保留在
[`interence`](https://github.com/eust-w/amd-bigym-3dgs-rocm/tree/interence)
分支；当前分支仅依赖上述外部 HTTP 契约。

完整目录、验收门禁和兼容入口说明见 [English README](README.md)。
