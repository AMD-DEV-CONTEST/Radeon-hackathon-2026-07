# M52 · 生产重建上线（M38–M51 全量部署）+ 设备探测 asyncio 修复

- **日期**：2026-08-06
- **背景**：用户批准生产重建（「好 重建吧」）。第一次 `--build` 输出全 CACHED —— 排查发现早上的 tar-pipe 同步只覆盖到 08:20 前的代码，M48–M51（14:06–15:07 写入）不在服务器磁盘上，Docker 认为无变化直接用旧镜像。
- **完成了什么**：
  - 全量重同步：`apps/web`（M43–M51 全部前端）+ `apps/api` + `packages` + `infra` + `apps/realtime/api/datasets.py` + **`apps/realtime/api/remote_compute.py`（M48，旧命令漏了这个文件）**，tar-pipe 复用 deploy-readiness.md §6 命令。
  - 重建 `web` + `realtime`（api 无改动不重建），真实执行：vite build 3.49s，新资产 `index-ZysAcaGU.js`（旧 `index-BV9a7gY5.js` 下线）。
- **验证结果**：
  - 容器：web/realtime Created=2026-08-06T08:13:11Z（新镜像），api 未动。
  - 线上 hash：`index-ZysAcaGU.js` ✅
  - `POST /api/datasets/record` 空 frames → `HTTP 400 {"detail":"frames 为空，没有可入库的轨迹"}` ✅（M38 生效）
  - `GET /api/remote_compute/device` → 初次失败：**`probe failed: name 'asyncio' is not defined`**（M48 的 `probe_local_device` 用了 `asyncio.to_thread` 但函数内只 import 了 subprocess/sys，与 `probe_node` 不同）→ 加 `import asyncio` 修复，单文件重同步 + 重建 realtime。
- **教训**：① 同步/部署验证必须查**内容标记**（grep 新代码特征串），不能只看 mtime 或「同步过」；② M48 只过了 tsc/语法检查，没实际起 realtime 打端点 —— 这次线上探测端点才暴露 asyncio 缺 import。Python 端点改动应本地起服务 curl 一次再提交。
- **关键命令**：
  ```bash
  # 重同步（含 remote_compute.py）
  tar cf - --exclude='node_modules' --exclude='.venv' --exclude='__pycache__' \
    --exclude='apps/pi0_sidecar' --exclude='apps/realtime/.piper_voices' \
    --exclude='apps/realtime/datasets' --exclude='apps/realtime/outputs/captured_images' \
    --exclude='.env' --exclude='*.db' \
    apps/web apps/api packages infra \
    apps/realtime/api/datasets.py apps/realtime/api/remote_compute.py \
    apps/realtime/data/reachy_mini_moves apps/realtime/config \
    | ssh root@47.113.126.51 "tar xf - -C /opt/botversex"
  # 重建
  docker compose -f infra/docker/docker-compose.prod.yml up -d --build web realtime
  ```
- **最终结果**：M38–M51 全部上线；设备探测修复随 realtime 重建生效。已提交。
- **下一步**：v2 主线继续（runtime 内容丰富轮）；M52 上线后让用户在线上复验 M50/M51 两个 bug 修复。
