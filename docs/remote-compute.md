# 算力节点（Remote Compute Node）

BotverseX **不假设你拥有任何特定型号的 GPU 机器**。你可以在以下任意一种环境下使用：

| 你的环境 | 训练 | 推理（部署） |
|---------|------|------------|
| 只有笔电（无 GPU） | 云端 Qualia | 云端推理 / 小模型 CPU 推理（ACT 等） |
| 笔电 + 本地 NVIDIA GPU | 本机 / 云端 Qualia | 本机 sidecar（`local` 节点） |
| 笔电 + 远端 GPU 机器（朋友的 GB10、家里的服务器、云 VM） | 远端 / 云端 Qualia | 远端 sidecar（`remote_ssh` 节点） |

「算力节点」就是这两件事的抽象：

1. 一个 **HTTP sidecar URL**（推理服务）
2. 一个可选的 **SSH 目标**（用来 rsync 训练好的模型过去）

## 节点类型

| kind | 说明 | SSH | rsync | 例子 |
|------|------|-----|-------|------|
| `local` | sidecar 在本机 | 否 | 否（直接落本地目录） | 笔电 + 本地 GPU |
| `remote_ssh` | sidecar 在远端，BotverseX 通过 SSH rsync 模型过去 | 是 | 是 | 朋友的 GB10 / 家里的服务器 |
| `remote_http` | sidecar 在远端，但只能 HTTP 访问（无法 SSH） | 否 | 否（模型必须能被 sidecar 自己拉，如 HF id） | 云推理服务 |

## 配置

配置存在 Local Agent 这边的 `~/.cache/botversex/remote_compute.json`。三种方式编辑：

### 1. 网页 UI（推荐）

打开 `https://<your-botversex>/settings/remote-compute`，可视化增删改查 + 探测。

### 2. HTTP API

```bash
# 列出
curl http://127.0.0.1:8002/api/remote_compute/nodes

# 新增
curl -X POST http://127.0.0.1:8002/api/remote_compute/nodes \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "my_home_gpu",
    "name": "家里的 RTX 4090",
    "kind": "remote_ssh",
    "sidecar_url": "http://192.168.1.10:8010",
    "ssh_host": "192.168.1.10",
    "ssh_user": "user",
    "ssh_port": 22,
    "model_root": "/home/user/outputs",
    "default_model_path": "/home/user/outputs/pi05_smoke_patched",
    "policy_types": ["pi05"],
    "enabled": true
  }'

# 设为默认
curl -X POST http://127.0.0.1:8002/api/remote_compute/default \
  -H 'Content-Type: application/json' \
  -d '{"node_id": "my_home_gpu"}'

# 探测
curl http://127.0.0.1:8002/api/remote_compute/nodes/my_home_gpu/probe
```

### 3. 直接编辑 JSON

```json
{
  "nodes": [
    {
      "id": "local",
      "name": "本机（CPU/本地 GPU）",
      "kind": "local",
      "sidecar_url": "http://127.0.0.1:8010",
      "model_root": "/home/user/.cache/botversex/models",
      "enabled": true
    },
    {
      "id": "my_home_gpu",
      "name": "家里的 RTX 4090",
      "kind": "remote_ssh",
      "sidecar_url": "http://192.168.1.10:8010",
      "ssh_host": "192.168.1.10",
      "ssh_user": "user",
      "ssh_port": 22,
      "model_root": "/home/user/outputs",
      "default_model_path": "/home/user/outputs/pi05_smoke_patched",
      "policy_types": ["pi05"],
      "enabled": true
    }
  ],
  "default_node_id": "local"
}
```

`local` 节点永远存在、永远启用、不可删除。

## 在远端机器上跑 sidecar

`scripts/gb10_pi05_sidecar.py` 是一个 FastAPI 推理服务，名字虽然带 "gb10"，但能在任何有 NVIDIA GPU + CUDA 的 Linux 上跑（不限 GB10 / DGX Spark）：

```bash
# 在远端机器上
git clone <botversex> && cd botversex
pip install -r requirements-sidecar.txt  # 或按需
BOTVERSEX_PI0_SIDECAR_BIND=0.0.0.0:8010 \
  python scripts/gb10_pi05_sidecar.py
```

启动后：
- `GET /healthz` 返回当前加载的模型
- `POST /load` 热加载一个新模型（远端路径或 HF id）
- `POST /predict` 推理一次

## SSH ProxyJump（可选）

如果你的远端机器在内网，需要通过一台公网跳板机访问，在节点配置里填 `ssh_jump`：

```
ssh_jump: "root@43.156.102.67"
```

rsync 时会自动 `ssh -J root@43.156.102.67`。

## 模型同步流程

`scripts/sync_model_to_remote.py` 把训练好的模型从 HF/Qualia 拉下来，rsync 到远端节点的 `model_root`，然后调用 sidecar `/load` 热加载：

```bash
# 按节点同步
python scripts/sync_model_to_remote.py \
  --node-id my_home_gpu \
  --model-id user/pi05-xxx \
  --load

# 老式显式参数（仍然支持）
python scripts/sync_model_to_remote.py \
  --host user@192.168.1.10 \
  --remote-dir /home/user/outputs/pi05_v1 \
  --sidecar-url http://192.168.1.10:8010 \
  --model-id user/pi05-xxx \
  --load
```

`scripts/sync_pi05_to_gb10.py` 是 deprecated 别名，行为完全一致。

## 在 B601 部署面板选节点

打开 `/robots/b601_rs`（或 `/robots/b601_dm`），「运动」Tab 顶部有一个「算力节点」下拉：

- 默认 `local`
- 列出所有 enabled 节点
- 切换节点会自动把该节点设为默认（方便下次）
- 「同步到算力节点」按钮把当前模型 rsync 到所选节点
- 「部署到机械臂」按钮调所选节点的 sidecar 推理

## 老用户迁移

如果你之前依赖环境变量：

| 老环境变量 | 新位置 |
|----------|--------|
| `BOTVERSEX_PI0_SIDECAR_URL` | 节点的 `sidecar_url` |
| `B601_GB10_SSH` | 节点的 `ssh_host`（含 user） |
| `B601_GB10_REMOTE_DIR` | 节点的 `model_root` + `default_model_path` |
| `B601_PI05_MODEL` | 节点的 `default_model_path` |

第一次启动新版 Local Agent 时，会自动种入一个 `gb10_friend_example` 模板节点（默认 disabled），把老环境变量折叠进去。你可以编辑它、改成你自己的机器，然后启用。
