[English](README.md) | [中文](README_CN.md)

# AetherDB V1.31.2

AetherDB 是面向职业小说作者、连载团队、游戏叙事设计与 IP 开发团队的本地优先世界观管理和长篇创作系统。它把 Vue 3 + Tauri 2 桌面工作区、FastAPI 控制平面、结构化 SQLite 数据库、混合检索、多模态素材流程和可审核的 AI 辅助整合在同一套应用中。

本仓库用于参加 AMD Radeon Hackathon 2026-07 Track 1：多模态内容创作工具开发。

## 核心能力

- 带自动保存、文档导航、实体抽取、冲突检查和 AI 分析的创作工作区。
- 管理角色、地点、势力、事件、物品、概念、规则、时间线、关系和标签。
- 多数据库、多作品组织，以及由迁移系统管理的 SQLite 数据层。
- 通过 FTS5、sqlite-vec 和 BGE-M3 多语言向量实现混合检索与 RAG 上下文召回。
- 使用 BGE-VL 进行图像/文本检索，并支持受管理的多模态素材和可选图像生成。
- 使用 Kokoro 82M 多语言 TTS 进行章节朗读、声音预览和发音验证。
- 模型 manifest、SHA-256 校验、隔离 Worker、资源租约和明确的后端选择。
- 仅接受请求头 `X-API-Key` 的认证、能力权限门、本地 owner token 和私有运行数据。

## 系统架构

```text
Vue 3 / Tauri 2 桌面 UI
            |
            | 动态本地回环 HTTP + X-API-Key
            v
FastAPI 控制平面（约 279 个 /api/* method/path）
       |                 |                    |
       v                 v                    v
SQLite + Alembic     运行时调度器          模型包注册表
FTS5 + sqlite-vec    资源租约              Manifest + SHA-256
       |                 |                    |
       +-----------------+--------------------+
                         v
                    隔离模型 Worker
             BGE-M3 / BGE-VL / Kokoro TTS
                   Kandinsky 可选
```

前端负责作者交互和状态呈现；后端负责认证、持久化、一致性、模型准入、调度与安全边界。前端状态不能替代后端授权。

## 模型与算法

| 模型包 | 主要用途 | 支持后端 |
| --- | --- | --- |
| AetherDB BGE-M3 | 多语言向量、语义检索、RAG 上下文 | ROCm/MIGraphX、CUDA、CPU |
| AetherDB BGE-VL Base | 角色图、地图和参考素材的图像/文本检索 | ROCm PyTorch、CUDA、CPU |
| AetherDB Kokoro 82M | 章节朗读、声音预览、发音检查 | ROCm PyTorch、CUDA、CPU |
| AetherDB Kandinsky 2.2 | 可选本地图像生成 | ROCm PyTorch、CUDA |

源码仓库不保存模型权重。模型只有在 package manifest、声明大小、许可证接受状态、必需文件和 SHA-256 哈希全部通过验证后，才能进入调度流程。

## AMD Radeon GPU 与 ROCm

比赛模式采用 fail-closed 策略，要求 Linux ROCm 设备可见、PyTorch HIP 运行时正常、真实 GPU 矩阵运算通过、模型后端兼容，并存在当前 Worker 验证证据：

```text
REQUIRE_ROCM=true
ALLOW_SILENT_FALLBACK=false
ALLOW_UNVERIFIED_MODEL=false
```

AMD 后端或模型证据不可用时，任务会被阻止，不会把 CPU 回退伪装为 GPU 成功。详见 [比赛复现说明](deploy/COMPETITION_REPRODUCTION.md) 与 [ROCm 模型兼容说明](deploy/ROCM_MODEL_COMPATIBILITY.md)。

## 环境要求

### 后端核心

- Python 3.10-3.12（主要验证环境为 Python 3.10.11）
- `requirements.txt` 中固定版本的依赖
- 支持 FTS5 的 SQLite

### 桌面端开发

- Node.js 20.19 或更高版本
- pnpm 10 或更高版本
- 稳定版 Rust 工具链
- 目标操作系统对应的 Tauri 2 平台依赖

### AMD 比赛环境

- Linux `amd64`
- 兼容的 AMD Radeon GPU 和内核驱动
- `/dev/kfd` 与 `/dev/dri/renderD*`
- Docker Engine 与 Compose
- `deploy/docker/Dockerfile.rocm` 固定的 ROCm/PyTorch 环境

## 快速开始

### 后端与浏览器界面

```bash
python -m venv venv

# Windows
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe scripts\init_runtime.py
venv\Scripts\python.exe main.py

# Linux/macOS
venv/bin/python -m pip install -r requirements.txt
venv/bin/python scripts/init_runtime.py
venv/bin/python main.py
```

打开启动时打印的动态本地回环地址，不要假定端口固定为 8000。

Windows 用户在完成虚拟环境安装后，也可以使用 `start.bat`；它会通过受支持的源码启动流程完成运行时初始化并启动后端。

### 前端开发

```bash
cd frontend
pnpm install
pnpm run dev
```

浏览器开发模式下，将 `AETHERDB_DEV_API_URL` 设置为后端打印的明确动态本地回环地址。Vite 配置会拒绝非本地 API 目标。

### Tauri 桌面开发与构建

```bash
cd frontend
pnpm install
pnpm tauri dev

# 构建本机桌面安装包与受管理的后端 sidecar
pnpm run tauri:build:host
```

原生安装包必须在每个目标操作系统上单独验收；Windows 构建成功不能作为 macOS 或 Linux 打包成功的证据。

## Docker

Docker Core 是不包含模型权重和私有运行数据的本地浏览器/服务模式：

```bash
cp deploy/docker/.env.example deploy/docker/.env
docker compose --env-file deploy/docker/.env \
  -f deploy/docker/docker-compose.yaml up --build -d
```

AMD 比赛模式使用独立文档和配置，要求不可变镜像 digest、显式 ROCm 设备映射、真实 GPU 验证与逐模型 Worker 证据。

## 测试

```bash
python -m compileall main.py api app services routes tests
python check_routes_auth.py
python -m pytest

cd frontend
pnpm run test:api
pnpm run build
```

ROCm 比赛验证必须在真实兼容的 Linux AMD 主机上执行，Windows 或仅有 CPU 的开发机无法证明该结果。

## 运行数据与隐私边界

首次初始化会创建 `config.local.yaml`、`.api_keys.json`、`app_data/` 和 `logs/` 等本地文件和目录，它们不得提交。源码和发行包规则还会排除用户数据库、用户提示词与内容、缓存、模型权重、私人模型供应商凭据和生成的 sidecar 二进制文件。

## 项目结构

```text
api/                 FastAPI API 路由
app/                 配置、部署、实例身份和数据模型
services/            数据、检索、模型运行时、多媒体与 AI 服务
frontend/            Vue 3 + Tauri 2 桌面应用
resources/           模型包和安装 manifest（不含模型权重）
deploy/              Core、本地服务和 ROCm 比赛部署文件
scripts/             初始化、验证、打包和维护工具
tests/               后端、安全、模型、多模态和发行测试
```

## 黑客马拉松提交材料

正式提交包包括：

- 中英双语 Project Profile PDF；
- 3-5 分钟 1080p 演示视频；
- 中英双语单页海报；
- 完整的净化源码树与依赖声明；
- 英文 PR 描述和最终提交检查表。

## 许可证

AetherDB 采用 [GNU Affero General Public License version 3 only](LICENSE)（`AGPL-3.0-only`）开源协议。任何个人或组织均可依照协议使用、修改和再发布本项目；基于本项目提供网络服务的修改版本必须遵守 AGPL 对对应源码可获得性的要求。

Copyright (C) 2026 陈sir。第三方依赖与模型包继续遵循各自的上游许可证、声明、署名要求和接受条件，详见 [NOTICE](NOTICE)。
