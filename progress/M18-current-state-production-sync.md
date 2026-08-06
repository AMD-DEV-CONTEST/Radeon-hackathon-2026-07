# M18 — 当前状态审计与生产同步确认

日期: 2026-05-17

## 完成了什么

BotverseX 的当前定位已从偏窄的 “Robot Learning Platform” 校正为：

> BotverseX 是机器人技能的开发平台、本地运行时和未来技能市场。  
> 我们让机器人能力像 App 一样被开发、运行和分发。

网站标题已同步为：

```text
Botverse X - Develop, Run, and Distribute Robot Skills
```

当前产品不是“只做一个机械臂控制台”，而是在用 SO-101、Reachy Mini、Local Agent / Realtime、Workflow、Skill registry 和订阅系统验证机器人技能生态的最小闭环。

## 当前总体状态

### 本地与云端同步

已确认本地与 ECS 云端的关键源码 hash 一致，覆盖：

- `apps/web/src/components/layout/Navbar.tsx`
- `apps/web/src/pages/Skills.tsx`
- `apps/web/src/pages/Training.tsx`
- `apps/web/src/pages/Login.tsx`
- `apps/web/src/lib/urdf.ts`
- `apps/web/src/App.tsx`
- `apps/api/app/api/v1/endpoints/hub.py`
- `apps/api/app/core/config.py`
- `apps/realtime/api/main.py`
- `infra/docker/web.prod.Dockerfile`
- `infra/docker/nginx.conf`

云端生产栈状态：

- `botversex-web` 正常运行
- `botversex-api` 正常运行
- `botversex-realtime` 正常运行
- 线上 bundle: `index-JLvHS0yE.js`（M18 时点；**M19 后**已更新为 `index-D85pS6YT.js`，见 [M19](./M19-reachy-mini-ux-cloud-e2e.md)）

### 公共展示能力

未登录用户现在可以看到平台主要入口，而不是被迫先登录：

- `/`
- `/robots`
- `/setup`
- `/skills`
- `/training`
- `/ai-hub`
- `Build` 下拉入口（Datasets / Training / Models / Skills / Workflow）

匿名浏览的边界：

- 可以看 Skill registry 和 runtime 兼容信息。
- 可以看 Training 页面壳、能力介绍和登录引导。
- 私有数据仍保持登录保护，例如 `/api/v1/skills/installations` 和 `/api/v1/skills/runs` 未登录返回 `401` 是预期行为。

### 认证与订阅

- `test/test` 在本地和云端均可登录。
- `test` 用户在本地和云端均为 `creator` tier。
- `/api/v1/auth/me` 返回 `entitlements`。
- free / pro / creator 三档订阅与配额真源已落地。
- Pricing / UpgradeModal / Workflow tier gating 已接入。

### AI Hub

已修复 HuggingFace Hub 查询卡死导致页面长期 Loading 的问题：

- `GET /api/v1/hub/models` 使用 `asyncio.wait_for` + thread pool 包裹同步 HF 调用。
- HF 卡住时约 10 秒返回 fallback models。
- `/ai-hub` 页面不会无限 Loading。
- AI Hub、model detail、leaderboard 使用 `publicJson`，支持匿名浏览。

### Robots / URDF

已修复 URDF/STL 在生产环境中卡在 `Loading URDF...` 的问题：

- `apps/web/src/lib/urdf.ts` 改为 `fetch()` 获取 STL `arrayBuffer`，再用 `STLLoader.parse()` 解析。
- 生产 `/api/urdf/*` 与 STL 资源请求返回 `200`。
- SO-101 与 Reachy Mini 3D preview 可加载；Reachy Mini STL 较多时需要等待解析完成。

### Skills

Skills 页面已从“登录后才能看到”调整为“公共发现 + 登录后管理”：

- `GET /api/v1/skills` 公共可读。
- `GET /api/v1/skills/runtimes` 公共可读。
- 安装、配置、运行、运行历史仍要求登录。
- 未登录时 `My Installations` / `Recent Runs` 展示登录引导，不再整页显示 `authentication required`。

### Training / Workflow

- `/training` 未登录时不再调用私有训练任务列表，避免整页 `authentication required`。
- 未登录用户可浏览训练页面；提交训练任务仍需要登录。
- Workflow 编辑器已有节点和 Skill invoke 入口，但仍需继续从可视化/演示态推进到真实执行闭环。

### Deployment

ECS 生产部署路径已基本跑通：

- 源码同步到 `/opt/botversex`
- `docker compose -f infra/docker/docker-compose.prod.yml build web`
- 替换 `botversex-web` 容器
- API / Realtime / Web 三服务通过 Nginx 同源暴露

已发现的生产操作注意事项：

- 当前 ECS 上 `docker` 实际由 Podman 兼容层提供。
- `podman-compose up` 遇到同名容器时可能只 `start` 旧容器，因此更新 web 时需要显式 `stop/rm botversex-web` 后再 `up -d web`。
- 本地 `npm run build` 仍受既有 TypeScript 严格检查问题阻塞；生产 Docker 路径使用 `npx vite build`，当前可通过。

## 解决了什么问题

1. **生产和本地不同步**
   - 对关键文件做了 hash 对比。
   - 补齐遗漏的前端和 realtime 文件。
   - ECS 重建并确认新 bundle 生效。

2. **未登录用户看不到平台价值**
   - 顶栏对访客显示 `Setup` 与 `Build`。
   - Skills / Training 改为公共浏览 + 私有操作登录门禁。

3. **登录页拦截短密码测试账号**
   - 登录模式不再要求 `minLength=8`。
   - 注册模式仍保留 8 位密码要求。

4. **AI Hub 长时间 Loading**
   - HF 查询增加 10 秒 timeout 与 fallback。

5. **Robots URDF preview 卡住**
   - STL loader 改为 `fetch + parse`。
   - 生产资源加载路径已验证。

6. **平台叙事偏窄**
   - 网站 title 从 `Robot Learning Platform` 调整为机器人技能开发、运行与分发的口径。

## 关键命令 / 配置

### 本地与云端关键路由 smoke

```bash
python3 - <<'PY'
import urllib.request
for base in ["http://localhost:5173", "http://botversex.feispace.me"]:
    for path in ["/", "/robots", "/skills", "/training", "/setup", "/login", "/api/v1/skills", "/api/robots"]:
        r = urllib.request.urlopen(base + path, timeout=12)
        print(base, path, r.status)
PY
```

### 验证 test 高级账号

```bash
python3 - <<'PY'
import json, urllib.request
for base in ["http://localhost:5173", "http://botversex.feispace.me"]:
    req = urllib.request.Request(
        base + "/api/v1/auth/login",
        data=json.dumps({"email": "test", "password": "test"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    token = json.loads(urllib.request.urlopen(req, timeout=12).read().decode())["access_token"]
    req = urllib.request.Request(base + "/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    me = json.loads(urllib.request.urlopen(req, timeout=12).read().decode())
    print(base, me["username"], me["subscription_tier"], me["entitlements"]["tier"])
PY
```

### 匿名 Skills 页面检查

```bash
chromium --headless --disable-gpu --no-sandbox \
  --user-data-dir=/tmp/botversex-cloud-anon-check \
  --virtual-time-budget=15000 \
  --dump-dom 'http://botversex.feispace.me/skills?sync-check=1'
```

关键文本：

- `Build`
- `登录`
- `注册`
- `Skill Registry`
- `so101_generic_teleop`
- `Registered Runtimes`
- 不应出现 `authentication required`

## 最终结果

截至 2026-05-17：

- 本地和云端在基本功能上已同步。
- 核心公开页面可匿名浏览。
- 私有数据仍保持认证保护。
- `test/test` 高级创作者账号在本地和云端均可用。
- ECS 生产栈可构建、部署、运行。
- 网站叙事已对齐最高纲领：开发、运行、分发机器人技能。

## 诚实边界

当前仍不能对外声称：

- 已经是完整机器人 App Store。
- 已经支持所有机器人。
- 技能可以无脑跨硬件通用。
- 市场、支付、版本更新和商业分发闭环已经完成。

当前应该说：

- BotverseX 正在验证机器人应用生态的最小闭环。
- 已有 Runtime / Workflow / Skill 三个核心抽象。
- SO-101 和 Reachy Mini 是切入口。
- 本地运行时、技能注册表、训练/推理/部署入口已有骨架。
- 分发层和市场化是下一阶段。

## 下一阶段优先级

1. **Workflow 真执行**
   - 让 Workflow 节点从 UI 编排走向真实 API orchestration。
   - 训练、评估、部署、Skill invoke 需要形成可复现链路。

2. **Skill 打包与发布**
   - 把 Skill schema、安装、运行、兼容性和版本字段继续收敛成分发单元。
   - marketplace 先做可信目录，不急着做空市场。

3. **Local Agent 产品化**
   - 安装、启动、检测、故障提示需要更顺。
   - 用户必须能明确知道“网站”和“本地硬件代理”的关系。

4. **生产部署固化**
   - 把当前手工 ECS 部署经验沉淀进脚本。
   - 避免 Podman 同名容器导致旧镜像继续运行。

5. **稳定性与回归**
   - 固定 smoke test：匿名 browse、登录、AI Hub fallback、URDF 预览、Skills public/private、Training gating。
   - 逐步修复本地 TypeScript build 的既有报错，让 `npm run build` 与 Docker build 收敛。
