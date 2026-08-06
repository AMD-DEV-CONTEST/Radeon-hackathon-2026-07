# ColorGraph backend

本地 FastAPI + CLI 服务，负责真实媒体分析、模型推理、Typed Grade Graph、确定性 GPU 调色、质量验证和交付包生成。

当前 `pyproject.toml` 锁定 PyTorch CUDA 13.0 wheel，用于本机 NVIDIA 开发；业务代码不导入 CUDA 专属扩展，统一通过 `ComputeBackend` 使用 PyTorch device。切换到 ROCm 前必须按 `docs/ROCM_BACKEND.md` 更换 PyTorch wheel 并在 Radeon 实机执行验证清单。

新建项目使用 `colorgraph.renderer/v3`：固定 PyOpenColorIO 2.5.2 与官方 ACES 2 Studio Config，相机输入经 ACES2065-1 进入 ACEScg，创意节点显式往返 ACEScct，输出使用 ACES 2 SDR Display/View Transform。v3 使用 CCT+Duv/xy + CAT16/Bradford 白平衡、ASC CDL no-clamp 负值语义和 ACEScct/AP1 encoding-aware creative 算子；v1/v2 图仍按原版本回放，不会在读取时隐式迁移。
新建参数轨道默认使用基于实际秒数的单调 PCHIP；旧 `cubic_spline` 值继续调用原 Catmull–Rom compatibility mode。
v3 Look 默认显式使用 tetrahedral LUT；`.cube` 支持 1D shaper、3D 与组合链，CLF/CTF 通过 OCIO FileTransform 执行。旧项目固定 trilinear；缓存按文件摘要、device 和 dtype 隔离并在文件替换时失效。

## 启动

从仓库根目录运行：

```powershell
uv sync --project backend
uv run --project backend uvicorn colorgraph.api.app:app --host 127.0.0.1 --port 8010 --reload
```

首次调用场景理解或蒙版接口会下载模型。默认数据目录为 `backend/data/`，模型目录为 `backend/models/`。

## 主要 API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 服务状态 |
| GET | `/api/system/device` | 真实设备、运行时和显存 |
| POST | `/api/projects` | 上传视频并启动媒体分析 |
| GET | `/api/projects` | 列出可恢复的本地项目 |
| GET | `/api/jobs/{job_id}` | 任务状态 |
| GET | `/api/jobs/{job_id}/events` | SSE 任务进度 |
| GET/PUT | `/api/projects/{id}/grade-graph` | 读取或替换调色图 |
| POST | `/api/projects/local` | 通过绝对路径零拷贝接入本地大文件 |
| GET | `/api/projects/{id}/source?quality=1080p\|540p` | 获取可切换的浏览器播放代理，默认 1080p |
| POST | `/api/projects/{id}/color-management` | 原地切换输入色彩变换并复用代理重分析 |
| GET | `/api/projects/{id}/color-pipeline/migration-preview` | 只读生成 v2→ACES v3 候选、警告与阻止原因 |
| POST | `/api/projects/{id}/color-pipeline/migrate` | 明确确认后备份旧图并保存 ACES v3 |
| POST | `/api/projects/{id}/masks` | 生成语义/深度时序蒙版 |
| POST | `/api/projects/{id}/commands` | 自然语言增量编译 |
| POST | `/api/projects/{id}/preview` | GPU 单帧预览 |
| POST | `/api/projects/{id}/candidates` | 本地 Look 渲染与成对 A/B |
| POST | `/api/projects/{id}/render` | 视频渲染、质检和修复 |
| GET | `/api/projects/{id}/quality` | 读取质量报告 |
| POST | `/api/projects/{id}/export` | 生成 ZIP 交付包 |

交互式 OpenAPI 文档位于 `http://127.0.0.1:8010/docs`。

预览接口使用内容寻址缓存，缓存键只包含当前时间真正生效的节点和蒙版。修改 Shot 02 不会让 Shot 01 的预览失效；响应中的 `cache_hit` 和 `cache_key` 可用于验证。播放器默认使用 1080p/30 fps 高质量 H.264 代理，可切换为 540p/15 fps；精确单帧使用 1080 宽度级别的无损 RGB PNG，并保留与播放视频相同的输出信号，避免 JPEG YCbCr 矩阵和额外 sRGB 转换造成色差。

组合蒙版支持安全的小型表达式语法：

```text
sky AND NOT mountain
(sky OR water) AND NOT vegetation
```

`AND`、`OR`、`NOT` 对软蒙版分别执行 minimum、maximum 和反相运算。

## CLI

```powershell
uv run --project backend colorgraph doctor
uv run --project backend colorgraph analyze .\input.mp4 --with-masks
uv run --project backend colorgraph render <project_id> --batch-size 4
```

## 运行时选择

`COLORGRAPH_DEVICE` 支持：

- `auto`：ROCm/CUDA 可见时使用 GPU，否则回退 CPU；
- `cuda`：要求 CUDA；
- `rocm`：要求 `torch.version.hip` 和可见 GPU；
- `cpu`：强制 CPU。

视频编码默认选择：

- CUDA：`h264_nvenc`，CQ 19；
- ROCm + Windows：`h264_amf`，CQP；
- 其他：`libx264`，CRF 18。

可用 `COLORGRAPH_VIDEO_ENCODER` 显式覆盖。

## 验证

```powershell
uv run --project backend ruff format --check colorgraph tests
uv run --project backend ruff check colorgraph tests
uv run --project backend pytest
```

模型级和端到端测试素材不随产品数据目录提交；第一次运行真实模型验证需要网络或预先准备 Hugging Face 缓存。
