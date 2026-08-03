# StagePoster 一键部署指南

> 目标：在 Ubuntu 24.04 + AMD Radeon PRO W7900 48 GB 上，通过一条命令完成 StagePoster 全栈部署。

---

## 1. 环境基线（已验证）

| 组件 | 版本/配置 |
|---|---|
| OS | Ubuntu 24.04.4 |
| GPU | AMD Radeon PRO W7900 48 GB |
| GPU 架构 | `gfx1100` |
| ROCm | 7.2.1 (HIP 7.2.53211) |
| ComfyUI Python | 3.10.20 |
| ComfyUI Torch | 2.13.0+rocm7.2 |
| vLLM | 0.20.0 |
| vLLM Torch | 2.10.0+git8514f05 |
| Go | 1.25.0 |

---

## 2. 前置条件

- **ROCm 已预装**：云平台镜像通常已包含 ROCm 驱动。运行 `rocm-smi --showproductname` 确认。
- **sudo 权限**：安装系统依赖和 Go 需要 root。
- **网络稳定**：模型文件约 21 GB，确保下载环境稳定。

---

## 3. 一键部署

```bash
cd /workspace/poster-engine

# 一键部署（含系统依赖、Python 环境、模型下载、后端编译、服务启动）
sudo -E bash scripts/install-all.sh
```

脚本会自动完成：
1. 检查/安装系统工具
2. 检查 ROCm 环境
3. 安装 uv、Go 1.25.0、cloudflared
4. 克隆 ComfyUI（如不存在）
5. 创建 ComfyUI Python 3.10.20 环境 + 安装 ROCm Torch
6. 创建 vLLM Python 3.12 环境 + 安装 ROCm vLLM Wheel
7. 下载 Qwen3.5-9B + Z-Image Turbo 模型（带 SHA256 校验）
8. 编译 Go Backend
9. 生成 `.env` 配置文件
10. 启动 ComfyUI、vLLM、Backend 三项服务
11. 执行健康检查

---

## 4. 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `STAGEPOSTER_ROOT` | `/workspace/poster-engine` | 项目根目录 |
| `COMFY_VENV` | `/workspace/venv` | ComfyUI Python 环境 |
| `VLLM_VENV` | `/workspace/poster-engine/.venv-vllm` | vLLM Python 环境 |
| `VLLM_MODEL_PATH` | `/workspace/poster-engine/models/Qwen3.5-9B` | Qwen 模型路径 |
| `SKIP_APT` | `0` | 设为 `1` 跳过 apt 安装 |
| `SKIP_COMFY_TORCH` | `0` | 设为 `1` 跳过 ComfyUI Torch 安装 |
| `DOWNLOAD_MODELS` | `1` | 设为 `0` 跳过模型下载 |
| `INSTALL_ROCM` | `0` | 设为 `1` 安装 ROCm 驱动（通常不需要） |

---

## 5. 脚本架构

```
scripts/
├── install-all.sh              # 一键部署主入口
├── install-system-deps.sh      # 系统依赖
├── install-uv.sh               # uv 包管理器
├── install-go.sh               # Go 1.25.0
├── install-cloudflared.sh      # Cloudflare Tunnel
├── install-comfyui.sh          # ComfyUI + ROCm Torch
├── install-vllm.sh             # vLLM ROCm 环境
├── download-models.sh          # Qwen + Z-Image 模型
├── build-backend.sh            # Go 后端编译
├── generate-env.sh             # 生成 .env 配置
├── start-all.sh                # 启动所有服务
├── stop-all.sh                 # 停止所有服务
├── status.sh                   # 查看服务状态
├── smoke-test.sh               # 冒烟测试
└── start-dev-tunnel.sh         # 开发隧道
```

---

## 6. 服务管理

```bash
# 启动所有服务
./scripts/start-all.sh

# 查看状态
./scripts/status.sh

# 停止所有服务
./scripts/stop-all.sh

# 冒烟测试
./scripts/smoke-test.sh

# 开发隧道
./scripts/start-dev-tunnel.sh
```

---

## 7. 验证清单

- [ ] `rocm-smi --showproductname` 显示 W7900
- [ ] `rocminfo | grep gfx` 显示 gfx1100
- [ ] ComfyUI: `curl http://127.0.0.1:8188/system_stats` 返回 200
- [ ] vLLM: `curl http://127.0.0.1:8001/v1/models` 返回 200
- [ ] Backend: `curl http://127.0.0.1:8080/health` 返回 `{"status":"ok"}`
- [ ] 模型文件 SHA256 校验通过
- [ ] `./scripts/smoke-test.sh` 全部通过
- [ ] 完整 E2E: 3 candidates → select → compose → review → final 通过

### E2E 冒烟测试

```bash
cd /workspace/poster-engine/backend

# 1. 启动所有服务
./scripts/start-all.sh

# 2. 检查状态
./scripts/status.sh

# 3. 执行冒烟测试（检查各服务 HTTP 可达性）
./scripts/smoke-test.sh

# 4. 完整 E2E 海报闭环测试
set -Eeuo pipefail
BASE_URL="http://127.0.0.1:8080"
SMOKE_DIR=$(mktemp -d /tmp/stageposter-e2e-XXXXXXXX)

# 创建 Session
SESSION_ID=$(curl -fsS -X POST "$BASE_URL/api/ai/sessions" \
  -H 'Content-Type: application/json' \
  -d '{"brief":{"event":{"title":"Test Event","artist":"Test","date":"2026-08-21","time":"20:00","venue":"Venue","presalePrice":"$45","doorPrice":"$60"},"branding":{},"visual":{"style":"dark fantasy editorial","theme":"test","musicGenre":"metal","mood":["epic"],"preferredColors":["black","red"]}}}' \
  | jq -r '.sessionId')

# 生成设计方案
PLAN_ID=$(curl -fsS -X POST "$BASE_URL/api/ai/sessions/$SESSION_ID/messages" \
  -H 'Content-Type: application/json' \
  -d '{"content":"确认开始设计"}' \
  | jq -r '.session.plans[0].planId')

# 确认方案
POSTER_ID=$(curl -fsS -X POST "$BASE_URL/api/ai/sessions/$SESSION_ID/plans/$PLAN_ID/confirm" \
  -H 'Content-Type: application/json' -d '{}' \
  | jq -r '.posterId')

# 等待候选图（轮询）
while true; do
  STATUS=$(curl -fsS "$BASE_URL/api/ai/sessions/$SESSION_ID" | jq -r '.status')
  [[ "$STATUS" == "awaiting_candidate_selection" ]] && break
  [[ "$STATUS" =~ ^(failed|cancelled)$ ]] && { echo "FAILED: $STATUS"; exit 1; }
  sleep 10
done

# 选择候选图
CANDIDATE_ID=$(curl -fsS "$BASE_URL/api/ai/sessions/$SESSION_ID" \
  | jq -r '.poster.candidates[] | select(.status=="ready") | .candidateId' | head -1)

curl -fsS -X POST "$BASE_URL/api/ai/sessions/$SESSION_ID/candidates/$CANDIDATE_ID/select" \
  -H 'Content-Type: application/json' -d '{}'

# Finalize
FINAL_STATUS=$(curl -fsS -X POST "$BASE_URL/api/ai/sessions/$SESSION_ID/finalize" \
  -H 'Content-Type: application/json' -d '{}' \
  | jq -r '.status')

[[ "$FINAL_STATUS" =~ ^(succeeded|completed_with_warnings)$ ]] || { echo "FAILED: $FINAL_STATUS"; exit 1; }

# 下载最终海报
RESULT_URL=$(curl -fsS "$BASE_URL/api/ai/sessions/$SESSION_ID" | jq -r '.poster.resultUrl')
curl -fsSL "$BASE_URL$RESULT_URL" -o "$SMOKE_DIR/final-poster.png"

echo "E2E PASSED: $SMOKE_DIR"
```

---

## 8. 故障排查

| 问题 | 解决 |
|---|---|
| ROCm 未安装 | 使用 AMD ROCm 镜像，或 `INSTALL_ROCM=1` 重新运行 |
| vLLM import 失败 | 删除 `.venv-vllm`，重新运行脚本 |
| 模型下载失败 | 检查网络，或手动放置模型到对应目录 |
| Go 版本不符 | 脚本会自动安装 Go 1.25.0 |
| 端口被占用 | `./scripts/stop-all.sh` 后重试 |
