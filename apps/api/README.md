# apps/api

BotverseX 业务 API 薄壳. 源自 V1 `backend/`, M0 阶段裁剪到最小可运行形态.

## M0 范围

- `auth`: 注册 / 登录 / 当前用户 (sqlite 持久化)
- `teleoperation`: 会话 REST 端点 (启停遥操作元数据, 不碰硬件)
- `/api/v1/docs` Swagger UI

## 未启用 (M2+ 恢复)

- Postgres / TimescaleDB (当前 sqlite)
- Redis / Celery / Flower
- MinIO
- datasets / training / users / files 路由
- WebSocket 帧级录制 (由 apps/realtime 承担)

## 启动

```bash
cd apps/api
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

服务监听 `http://localhost:8000`. Swagger 在 `http://localhost:8000/api/v1/docs`.

## 配置

`.env` (已提供开发默认值) 用于 sqlite / 开发 JWT / 开发 Fernet. 生产部署务必替换 `ENCRYPTION_KEY` 和 `JWT_SECRET`.

## 目录 (M0 精简后)

```
apps/api/
├── app/
│   ├── api/
│   │   ├── deps.py
│   │   └── v1/
│   │       ├── __init__.py       # 只注册 auth + teleoperation
│   │       └── endpoints/
│   │           ├── auth.py
│   │           └── teleoperation.py
│   ├── core/
│   │   ├── config.py             # M0 默认 sqlite, CORS 允许 :5173
│   │   └── security.py
│   ├── models/
│   │   ├── database.py           # UUIDType (跨方言), sqlite engine
│   │   ├── user.py
│   │   └── audit.py
│   └── main.py                   # startup: init_db() 建表
├── .env                          # 开发默认
├── .env.example
└── requirements.txt
```

## 和 apps/realtime 的分工

- apps/api: HTTP REST 业务 (用户, 会话元数据, M1.6 之后的录制 proxy)
- apps/realtime: WebSocket 实时流 + URDF + 录制落盘

M1.6 会在 `teleoperation.py` 添加 `/record/start|stop` 透传到 `REALTIME_SERVICE_URL` (配置在 `.env`).
