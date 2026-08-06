# Solo Worker OS AMD GPU 录屏与恢复手册

更新日期：2026-08-06（北京时间）

## 已验证环境

- Radeon Cloud 实例：`u-14615-b0cebd0b`
- 模板：`Solo Worker OS Debug`
- GPU：AMD/ATI，ROCm `gfx1100`
- 推理服务：vLLM
- 模型：`Qwen/Qwen3-4B`
- 模型上下文：4096 tokens
- Solo Provider：`AGENT_PROVIDER=local`
- Demo Mode：开启
- 已验证能力：模型健康检查、普通对话、`create_project` 工具调用

## 录屏设置

- 分辨率：1920x1080
- 帧率：30 fps
- 录制方式：Windows `Win+G` 或 OBS
- 麦克风：关闭，后期配音
- 浏览器缩放：100% 或 110%，以文字完整显示为准
- 目标时长：3-4 分钟
- 导出：H.264 MP4，1080p

## 无配音录屏镜头表

### 0:00-0:15 产品首页

打开 `http://127.0.0.1:3000/dashboard`。

缓慢展示项目、待收回款、总收入、需要关注四项指标，以及最近项目。

### 0:15-0:35 Radeon Cloud 实例

打开 Radeon Cloud Profile，展示：

- Instance：`u-14615-b0cebd0b`
- Status：`Ready`
- Template：`Solo Worker OS Debug`
- Image：ROCm vLLM 镜像

不要展示 SSH 私钥、API key 或任何 token。

### 0:35-1:05 GPU 与模型证据

在 JupyterLab 终端依次执行：

```bash
date -Is
rocm-smi --showproductname --showmemuse --showuse
ps -ww -eo pid,stat,etime,rss,cmd | grep -E '[v]llm serve|EngineCore'
curl -sS http://127.0.0.1:8000/v1/models
grep 'POST /v1/chat/completions' /workspace/vllm.log | grep '200 OK' | tail -n 5
```

画面需要清楚显示：

- `Advanced Micro Devices, Inc. [AMD/ATI]`
- `gfx1100`
- VRAM 已分配
- `vllm serve Qwen/Qwen3-4B`
- `/v1/models` 返回 `Qwen/Qwen3-4B`
- 请求日志为 `POST /v1/chat/completions ... 200 OK`

### 1:05-1:20 端到端健康检查

打开：

`http://127.0.0.1:3000/api/local-llm/status`

展示以下字段：

- `provider: local`
- `isLocal: true`
- `reachable: true`
- `servedModels: ["Qwen/Qwen3-4B"]`

### 1:20-2:05 Agent 创建项目

打开 `http://127.0.0.1:3000/chat`，清空历史后输入：

```text
新客户陈曦，需要品牌官网设计，预算12000元，截止日期2026年8月28日，请直接创建项目。
```

等待页面显示：

- 简洁的创建成功回复
- `create_project` 工具标签
- 路由类型与置信度

### 2:05-2:35 多轮工具调用

在同一对话输入：

```text
为陈曦的项目生成一份合同。
```

等待 `generate_contract` 工具完成，缓慢滚动展示合同内容。

如果此步骤未在 30 秒内完成，剪掉等待段，不要在录制中连续重试。

### 2:35-2:55 可观测性

打开 `http://127.0.0.1:3000/trace`，展示最近一条记录中的：

- 路由决策
- LLM 调用
- 工具调用与结果
- 耗时

### 2:55-3:15 最终结果

回到 Dashboard 或 Projects，展示刚创建的项目。停留 3 秒后结束录制。

## 当天启动命令

在 Radeon Cloud 的 JupyterLab 终端执行：

```bash
nohup vllm serve Qwen/Qwen3-4B \
  --host 0.0.0.0 \
  --port 8000 \
  --trust-remote-code \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.5 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  > /workspace/vllm.log 2>&1 &
echo $! > /workspace/vllm.pid
```

等待：

```bash
tail -f /workspace/vllm.log
```

看到 `Application startup complete.` 后按 `Ctrl+C` 退出日志查看。

安装并创建临时隧道：

```bash
/var/run/secrets/frp-self-service/install
/root/.local/bin/rc-tunnel stop
/root/.local/bin/rc-tunnel expose --port 8000
```

记录新的随机 HTTPS 地址。实例或隧道重启后，旧地址可能失效。

本机 `solo/.env.local` 需要配置：

```env
AGENT_PROVIDER=local
LOCAL_LLM_BASE_URL=https://<NEW_TUNNEL_URL>/v1/chat/completions
LOCAL_LLM_API_KEY=EMPTY
LOCAL_LLM_MODEL=Qwen/Qwen3-4B
DEMO_MODE=true
NEXT_PUBLIC_DEMO_MODE=true
```

启动应用：

```powershell
cd E:\gitproject\hackathon\solo
npm run dev
```

验证：

```text
http://127.0.0.1:3000/api/local-llm/status
```

必须看到 `reachable: true`。

## 录完后的安全关闭

先关闭公网隧道：

```bash
/root/.local/bin/rc-tunnel stop
```

再停止模型进程：

```bash
kill $(cat /workspace/vllm.pid)
```

最后停止本机 Next.js：在启动它的终端按 `Ctrl+C`。

Radeon Cloud 当前页面只提供 `Destroy Instance`，没有可确认的 Pause/Stop 按钮。关闭隧道和 vLLM 不会停止 GPU 实例计费。若选择“不销毁实例”，它会继续消耗 credits，并可能在 credits 耗尽后被平台自动删除。

## 明天恢复

1. 登录 Radeon Cloud Profile。
2. 如果实例仍存在，打开 Jupyter；如果不存在，从 `Solo Worker OS Debug` 模板重新 Launch。
3. 检查 `rocm-smi`，确认没有残留显存占用。
4. 按“当天启动命令”启动 vLLM。
5. 等待 `Application startup complete.`。
6. 停止旧隧道并重新 expose，获取新 URL。
7. 更新 `.env.local` 的 `LOCAL_LLM_BASE_URL`。
8. 启动 Next.js，访问健康检查并确认 `reachable: true`。

## 已知关键配置

`lib/agent/local.ts` 为 4096 上下文模型设置了：

- `getMaxTokens: 768`
- `enable_thinking: false`

这两项用于避免系统提示词、工具定义和模型输出共同超过上下文上限，并保持录屏回复简洁。
