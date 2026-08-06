# infra/docker — 开发联调栈

## 一条命令启动

```bash
docker compose -f infra/docker/docker-compose.dev.yml up --build
```

启动后:

- `realtime` — http://localhost:8002 (BotClaw JointUpdate `/ws/ui`, `/api/record`, `/api/urdf`)
- `api` — http://localhost:8000 (FastAPI, `/docs` 可查, `/api/v1/record/*` 透传到 realtime)
- `web` — http://localhost:5173 (Vite dev server, 代理上面两个)

## 物理臂 sender

容器内无法访问宿主机串口, **物理臂推流依然跑在宿主机**:

```bash
cd apps/realtime
python sender.py --dry-run            # 不读真臂, 发正弦波
python sender.py                      # 读真臂 (需要配好 BOTVERSEX_LEROBOT_PATH)
```

sender 连的是宿主机的 `ws://localhost:8002/ws/teleop`, 即 docker-compose 暴露出来的 realtime.

## 生产镜像

当前文件只服务于开发联调 (代码挂载, hot reload). 生产镜像会在 M3 阶段另做 (multi-stage build, 固定 tag, 不挂代码).
