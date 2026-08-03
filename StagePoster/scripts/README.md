# StagePoster 脚本说明

## 一键部署

```bash
# 全新环境一键部署（推荐）
sudo -E bash scripts/install-all.sh
```

`install-all.sh` 会自动完成：
- 系统依赖安装
- uv、Go 1.25.0、cloudflared 安装
- ComfyUI + ROCm PyTorch 环境
- vLLM ROCm 环境
- 模型文件下载（带 SHA256 校验）
- Go Backend 编译
- .env 配置生成
- 所有服务启动
- 健康检查

详细文档：[docs/one-click-deployment.md](../docs/one-click-deployment.md)

---

## 脚本清单

| 脚本 | 用途 |
|---|---|
| `install-all.sh` | **一键部署**（推荐首次使用） |
| `bootstrap.sh` | 基础环境初始化 |
| `bootstrap-server.sh` | 服务器环境初始化（含模型下载） |
| `install-system-deps.sh` | 安装系统依赖 |
| `install-uv.sh` | 安装 uv 包管理器 |
| `install-go.sh` | 安装 Go 1.25.0 |
| `install-cloudflared.sh` | 安装 Cloudflare Tunnel |
| `install-comfyui.sh` | 安装 ComfyUI + ROCm PyTorch |
| `install-vllm.sh` | 安装 vLLM ROCm 环境 |
| `download-models.sh` | 下载 Qwen3.5-9B + Z-Image 模型 |
| `build-backend.sh` | 编译 Go Backend |
| `generate-env.sh` | 生成 .env 配置文件 |
| `start-all.sh` | 启动所有服务（ComfyUI + vLLM + Backend） |
| `stop-all.sh` | 停止所有服务 |
| `status.sh` | 查看服务状态 |
| `smoke-test.sh` | 执行冒烟测试 |
| `start-dev-tunnel.sh` | 启动开发公网隧道 |
| `export-runtime-locks.sh` | 导出环境版本锁 |
| `test-comfy-api.sh` | 测试 ComfyUI API |

## 服务管理

```bash
# 启动
./scripts/start-all.sh

# 状态
./scripts/status.sh

# 停止
./scripts/stop-all.sh

# 隧道
./scripts/start-dev-tunnel.sh
```

## 环境变量

```bash
STAGEPOSTER_ROOT=/workspace/poster-engine
COMFY_VENV=/workspace/venv              # ComfyUI Python 环境
VLLM_VENV=/workspace/poster-engine/.venv-vllm  # vLLM Python 环境
VLM_MODEL_PATH=/workspace/poster-engine/models/Qwen3.5-9B
GOPROXY=https://goproxy.cn,direct
```

