# Docker 交付说明 — Track 3 Physical AI（真踢球复现）

## Canonical 镜像

唯一的提交镜像定义是 `amd-physical-ai-soccer/Dockerfile`（旧版根目录
`Dockerfile` 已移除，避免混淆）。镜像内容：

- 基础镜像 `rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_release_2.3.0`
  （ROCm 6.2 + Ubuntu 22.04 + Python 3.10 + PyTorch 2.3.0，Docker Hub 已验证 tag）
- 依赖：Genesis、skrl、rsl-rl-lib（rsl_rl，SPEC §3 训练/评测所需）、tensorboard、
  imageio[ffmpeg]、tqdm（见 `amd-physical-ai-soccer/requirements.txt`）
- JupyterLab 监听 `0.0.0.0:8888`，**强制 token**：启动时设置 `JUPYTER_TOKEN`；
  未设置则生成强随机 token 并打印到容器日志（`?token=...`）
- **非 root** 运行（uid 1000 `runner`）

## Build

构建上下文是 `amd-physical-ai-soccer/`（该目录内的 `.dockerignore` 已排除日志、
视频、模型等）：请在 AMD ROCm Linux 主机上构建（ROCm 镜像在 NVIDIA/macOS 上
无法运行）。

```bash
docker build -t track3-soccer:amd -f amd-physical-ai-soccer/Dockerfile amd-physical-ai-soccer
```

如果从仓库根构建（等价形式，根目录 `.dockerignore` 会排除 track2 等无关目录）：

```bash
docker build -t track3-soccer:amd -f amd-physical-ai-soccer/Dockerfile .
```

> 参考运行实例是 ROCm 7.2.1 / torch 2.9.1+HIP（见
> `amd-physical-ai-soccer/requirements-lock.txt`，由实例 `pip freeze` 生成）。
> 在 ROCm 7.x 主机上构建时，把基础镜像 tag 换成对应的 `rocm/pytorch` 镜像即可。

## Run（AMD ROCm 主机）

```bash
docker run -it --rm --name track3-soccer \
  --device=/dev/kfd --device=/dev/dri --group-add video \
  --security-opt seccomp=unconfined --cap-add=SYS_PTRACE \
  -p 8888:8888 \
  -e JUPYTER_TOKEN='set-a-strong-token' \
  -v "$PWD":/workspace \
  track3-soccer:amd
```

- `--device=/dev/kfd --device=/dev/dri --group-add video` 是 ROCm 容器标准设备
  挂载；`--gpus all` 只对 NVIDIA 生效，ROCm 主机上请用上述参数。
- `-v "$PWD":/workspace` 把整个项目工作区（含 SPEC §3 三个复现脚本与
  `kick_params.json`）挂载进容器，路径与脚本内 `ROOT = "/workspace"` 一致。
- 若宿主用户 uid 不是 1000，可加 `--user "$(id -u):$(id -g)"` 以便向挂载目录写输出。
- 浏览器打开 `http://localhost:8888`，输入 `JUPYTER_TOKEN`。

## 容器内复现 SPEC.md §3 三个入口

新开一个终端执行：

```bash
docker exec -it track3-soccer bash
cd /workspace
mkdir -p demos/exp
```

然后（容器内 Python 是基础镜像的 `python3`，即 py3.10；`/opt/venv/bin/python3.12`
是云端实例专用路径，容器里没有）：

```bash
# 1) 真踢球渲染（读取 kick_params.json；输出 kick_final/kick_final.mp4 + result.json）
python render_kick_final.py
#    期望：contact@116 -> scored@144，球速 ~4.3 m/s，0 摔倒

# 2) P1 追球训练（无对手；训练产物在 runs/task9_p1/）
python run_task9_p1.py --max_iterations 240 --num_envs 2048 --phase A

# 3) 单场景策略评测（300 步；先训练出 ckpt，或指向已有模型）
python run_task9_eval.py --ckpt runs/task9_p1/model_latest.pt --steps 300
#    输出 demos/exp/task9_p1_eval.json
```

评测脚本（`run_task9_eval.py`）从 `run_task9_p1.py` 导入 `HieraSoccerEnv`，两个
脚本都在工作区根目录，与 SPEC §3 命令一致。

## 依赖锁文件（官方 6.3）

`amd-physical-ai-soccer/requirements-lock.txt` 是在参考 ROCm 实例上执行
`pip freeze` 生成的（390 包，Python 3.12）。其中 `file:///install/...` /
`file:///opt/rocm-7.2.1/...` 形式的条目（torch、torchvision、torchaudio、
amdsmi、apex、vllm、amd-aiter）指向实例本地构建产物，仅作版本参考，跨主机安装时
以对应 ROCm 基础镜像自带的 torch 为准，其余纯 PyPI 包可按锁文件 pin 版本。


## 推送镜像（官方提交闭环，在 AMD ROCm Linux 主机上执行）

```bash
# 一条命令完成 build + tag + push（先 docker login 自己的仓库）
./scripts/docker_build_push.sh ghcr.io/<你的GitHub账号>/track3-soccer:amd
# 或 Docker Hub：
./scripts/docker_build_push.sh <你的DockerHub账号>/track3-soccer:amd
```

- 前提：AMD ROCm Linux 主机（amd64）、约 40GB 空闲磁盘、已 `docker login`。
- 耗时参考：基础镜像 `rocm/pytorch:rocm6.2_...` 压缩后约 20GB、解压约 38GB；
  构建约 15–30 分钟，推送约 20–60 分钟（取决于上行带宽）。
- 推送成功后，把镜像 URL 填进 `PR_DESCRIPTION.md` 的 Docker TODO 小节。

## 匿名说明

公开文档与镜像定义不含个人姓名、用户名或实例地址；实例访问信息仅存于
`archive/_internal/`（gitignored，不随仓库分发）。
