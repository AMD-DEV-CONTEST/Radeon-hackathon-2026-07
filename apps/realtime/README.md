# apps/realtime

BotverseX 实时内核. 源自 V2 `botverseX MVP` 的 `botverseX/` 包, 迁到 monorepo 后作为独立子应用.

## 能力

- `/ws/teleop` — sender 推送关节/舵机数据
- `/ws/ui` — 浏览器订阅实时关节流
- `/api/record` — 开始/停止录制 (产出 json + parquet)
- `/api/teleop`, `/api/b601` — LeRobot CLI 薄包装（SO-101 / B601-RS）
- `/api/urdf/{so101.urdf}` + `/api/urdf/b601_rs/b601_rs.urdf` — 静态 URDF 资源
- `/api/status` — 连接与录制状态快照

## 启动

```bash
cd apps/realtime
python -m venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_api.py          # HTTPS (default; auto-generates certs/ on first run)
python run_api.py --http   # plain HTTP — **required** when using `apps/web` Vite dev (`npm run dev`)
```

API 在 `https://localhost:8002`（首次需在浏览器信任自签证书）.

本地开发 `npm run dev` 时，Vite 代理默认指向 `http://127.0.0.1:8002`。请用 `run_api.py --http` 启动 realtime，否则 `/api/reachy/*`、`/api/urdf/b601_rs/*` 会返回 502。

**B601 URDF**：mesh 在 `static/urdf/b601_rs/assets/`（约 30 个 STL）。修改后端后重启 Agent：`pkill -f run_api.py; python run_api.py --http`。验收：`bash scripts/b601-smoke.sh`。

## sender (物理臂推流)

```bash
# 可选环境变量:
#   BOTVERSEX_LEROBOT_PATH  — LeRobot MakerMods 源目录 (默认指向 V2 原仓)
#   BOTVERSEX_CALIB_FILE    — 校准 json (默认指向 V2 原仓)
python sender.py --com_port COM3
```

## 目录

```
apps/realtime/
├── api/
│   ├── main.py           # FastAPI app + 路由
│   └── websocket.py      # ConnectionManager (teleop/ui 双池)
├── sender.py             # 物理臂 -> /ws/teleop 推流
├── convert_to_lerobot.py # 录制 json -> parquet
├── static/               # V2 旧 UI (html/js), M1 结束后由 apps/web 替代
├── dora-bambot/URDF/     # so101.urdf + STL
├── demos/                # 录制产出 (gitignore)
├── requirements.txt
└── run_api.py
```

## 注意

- M0 阶段 `static/` 旧 UI 仍然保留, 可通过 `http://localhost:8002/` 直接访问 (回退验证)
- M1 完成后 `apps/web` 会接管 UI, 到时再移除 `static/`
