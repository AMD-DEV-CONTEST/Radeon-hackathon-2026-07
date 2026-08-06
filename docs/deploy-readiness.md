# WebSerial 零安装主线 · 部署就绪清单（Deploy Readiness）

> **日期**：2026-08-06 ｜ **状态**：代码侧完成，等一次部署窗口
> **背景**：M28 第 6 节记录过「线上跑着 6 周前的 web 容器」；本清单让 WebSerial 主线的上线**一次到位**。
> **部署目标**：`botversex.feispace.me`（ECS `47.113.126.51`，rsync + docker compose 重建）。

---

## 1. 要上线的改动（S1–S3 + U1–U4，commit 范围）

| 里程碑 | 关键文件 | 说明 |
|--------|---------|------|
| M30 S1 | `apps/web/src/lib/webserial.ts` | Feetech 协议层（24 断言冒烟覆盖） |
| M32 S2 | `apps/web/src/components/so101/BrowserDirectPanel.tsx` | 直连面板接入通用层 |
| M33 U1 | 同上 + `scripts/webserial-protocol-smoke.mjs` | 第一动作仪式（挥手/🎉/首录 CTA） |
| M37 S3 | 同上 | 3D 孪生跟动 |
| M38 U3 | `apps/realtime/api/datasets.py`（新端点）+ 面板录制 | **后端有改动** |
| M39 U4 | `apps/web/src/components/so101/SerialDiagnostics.tsx` | 浏览器内诊断 |
| M40/M41 | docs（访谈门禁、复核） | 无需部署 |

**部署时需要重建的服务**：`web`（前端改动）+ `realtime`（datasets.py 新增端点）。`api` 无改动。

## 2. 部署步骤（M28 第 6 节命令，已核对）

```bash
# 1) 同步源码（排除清单沿用 M28，勿动 20GB venv）
rsync -az --delete \
  --exclude='node_modules/' --exclude='.git/' --exclude='*.venv/' \
  --exclude='__pycache__/' --exclude='apps/pi0_sidecar/' \
  --exclude='apps/realtime/.piper_voices/' \
  --exclude='apps/realtime/datasets/' \
  --exclude='apps/realtime/outputs/captured_images/' \
  --exclude='docs/presentations/' --exclude='.env' \
  --exclude='botversex_dev.db' --exclude='botversex_prod.db' \
  -e "ssh -i ~/.ssh/id_ed25519_ecs" \
  ./ root@47.113.126.51:/opt/botversex/

# 2) 重建 web + realtime（datasets.py 在 realtime 镜像里）
ssh -i ~/.ssh/id_ed25519_ecs root@47.113.126.51 \
  "cd /opt/botversex && docker compose -f infra/docker/docker-compose.prod.yml up -d --build web realtime"
```

## 3. 上线后验收清单（10 分钟，Chrome 无痕窗口）

1. 打开 `https://botversex.feispace.me/robots/so101?mode=browser` → 主 CTA 是「浏览器直连」样式的大按钮，步骤条（授权→扫描→挥手）可见
2. `curl https://botversex.feispace.me/api/datasets/record -X POST -d '{"frames":[]}'` → 返回 400（**端点已上线**且拒绝空数据）；有帧时返回 dataset 摘要
3. 页面无「已取消串口选择」以外的红色报错；扫不到舵机的卡片带「一键诊断」
4. 首页（/）hero 主 CTA = SO-101 浏览器直连（U2 已换位）
5. Navbar 分组名 = 「实验室」（U5）
6. 断开的串口重新插上 → 重新授权 → 正常扫描（真机项，有硬件时做）

## 4. 四个坑（M28 第 6 节，部署时必读）

1. **只 rsync 不重建 = 白干**：本地改完必须走第 2 步重建镜像，否则线上仍是旧容器。
2. **改了 `robots.json` 必须重启 realtime**：`load_robot_config()` 带 `@lru_cache`，刷新页面没用。本轮未改 robots.json，但 U2 涉及前端展示，仍按第 2 步重建 web 即可。
3. **改 URDF/mesh 要同步 `?v=` 版本号**：本轮未动 URDF（复用现有 `/api/urdf/so101.urdf`），无需处理；后续若换 SO-101 资产注意。
4. **本地重启**：`bash scripts/linux/botversex-restart-local.sh`（kill 旧进程再拉起 web/api/realtime）。

## 5. 回滚预案

- 前端：重新 rsync 旧代码 + 重建 web 容器。
- 后端（datasets.py）：旧 realtime 镜像 `docker compose ... up -d --no-build realtime` 用回旧镜像，或直接 `git checkout <旧commit> -- apps/realtime/api/datasets.py` 后重建。
- 新增端点无破坏性（只加 POST 路由），回滚风险低。

---

## 6. 2026-08-06 实测教训（部署方法修正）

**今天实测：rsync 全量同步在这台服务器上不可用。**

- 现象：`rsync -az --delete ./ root@47.113.126.51:/opt/botversex/` 跑了 90+ 分钟只传完 ~280M 源码，卡在文件清单阶段——`--delete` 要先全量扫描服务器 2.2G 旧树（含 659M pi0_sidecar 等遗留），而本机→ECS 的 SSH 链路只有 ~50–200KB/s。
- **结论：本部署链路不要用 rsync --delete；用 tar 管道**（无远程列举，纯流式）。已验证可行（13 分钟传完 web/api/packages/infra + realtime 增量）：

```bash
# 快路径（只传容器构建需要的目录 + realtime 增量文件）
tar cf - \
  --exclude='node_modules' --exclude='.venv' --exclude='__pycache__' \
  --exclude='apps/pi0_sidecar' --exclude='apps/realtime/.piper_voices' \
  --exclude='apps/realtime/datasets' --exclude='apps/realtime/outputs/captured_images' \
  --exclude='.env' --exclude='*.db' \
  apps/web apps/api packages infra \
  apps/realtime/api/datasets.py apps/realtime/data/reachy_mini_moves apps/realtime/config \
  | ssh -i ~/.ssh/id_ed25519_ecs root@47.113.126.51 "tar xf - -C /opt/botversex"
```

- **Dockerfile COPY 面**（决定最小同步集）：web 只 COPY `apps/web`+`infra/docker/nginx.conf`；realtime COPY `apps/realtime`+`packages/botclaw-spec`；api COPY `apps/api`+`packages/botclaw-spec`。`botversex-local-agent/`、`docs/`、`progress/`、`scripts/` 等**不需要同步**（除非要维护服务器上的副本）。
- **验证容器是哪个构建**（别信 ps，查时间）：
  ```bash
  docker ps --format '{{.Names}}\t{{.Status}}'          # Up X hours = 距上次重建
  docker inspect --format '{{.Created}}' <web容器ID>     # 镜像构建时间（UTC）
  curl -s https://botversex.feispace.me/ | grep -oE 'index-[A-Za-z0-9_-]+\.js'   # 线上资产 hash
  ```
- **已知遗留**：服务器上有一个 6月16日 挂着的陈旧监视器进程（`while pgrep -f "docker compose.*build realtime"` 循环）——无害，建议清理。
- **重建命令（唯一缺口）**：源码到位后，`docker compose -f infra/docker/docker-compose.prod.yml up -d --build web realtime`（容器内 npm ci + vite build，5–15 分钟；api 无改动可不重建）。
