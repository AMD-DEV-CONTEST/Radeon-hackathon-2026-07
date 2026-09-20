# Simple Client

一个最小客户端：向推理服务发送观测、回显推理速率，用于对 `inference_server.py` 做吞吐烟测。

> 这是通用的 msgpack 客户端示例。**BiGym 带 3DGS 房间壳的闭环评测客户端**在另一个仓库的评测 lane 里（两进程架构），完整步骤见 [`docs/amd_rocm_bigym_eval.md`](../../docs/amd_rocm_bigym_eval.md)。

用 `--env` 指定服务端配置（可选值见 `--help`）。先在仓库根目录 `source .venv/bin/activate` 激活环境，然后：

```bash
python examples/simple_client/main.py --help
```

## 不用 Docker

终端 1（起推理服务）：

```bash
python scripts/serve_policy.py --env <env_name>
```

终端 2（跑客户端）：

```bash
python examples/simple_client/main.py --env <env_name>
```

## 用 Docker（可选）

```bash
export SERVER_ARGS="--env <env_name>"
docker compose -f examples/simple_client/compose.yml up --build
```
