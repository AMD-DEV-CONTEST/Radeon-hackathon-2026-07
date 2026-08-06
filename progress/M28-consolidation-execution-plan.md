# M28 · 平台收敛执行计划

**日期**：2026-07-31  
**状态**：止血执行基本完成（P0/P1 代码侧已落地；T2-2 仅搭了 workbench 框架；T2-1 WebSerial **未做**；线上部署可能因 ECS SSH 阻塞未推）  
**定位**：**止血清单，不是造血战略。** 做完后平台「不骗人」，但不回答「谁付钱」。下一步战略见 [`docs/strategy/2026-07-31-product-truth-and-next.md`](../docs/strategy/2026-07-31-product-truth-and-next.md)。  
**执行方式**：按 P0 → P1 → P2 顺序推进。每个任务独立可交付，改完就能验收。

---

## 0. 给执行者的背景（不需要读别的文档）

2026-07-31 对平台做了三份独立审计：新用户上手路径、每加一台机器人的维护成本、真实能力 vs 演示外壳。三份审计指向同一个根因。

### 关键数字

| 维度 | 现状 |
|------|------|
| 新用户到"机械臂动一下" | **10–13 步**不可省略，卡点是手动信任自签 HTTPS 证书 |
| Local Agent 安装体积 | realtime 镜像 **2.93 GB**（`lerobot[feetech]` 拉 torch 全家桶） |
| Workflow 节点 | 39 个模板，**4 个没有 executor**（拖进图一点运行就抛异常） |
| Skills | 8 个 seed skill，只有 **2 个 verb** 真派发到 realtime，其余 1.5s 后假成功 |
| 单机型专属代码 | `components/reachy/` **5144 行** / `components/b601/` **5023 行**；全机型共享的 `components/features/` 只有 **1216 行** |
| manifest 有效性 | `robots.json` 约 **40%** 字段是死字段、重复定义或纯展示 |
| 近 30 天最常改动文件 | 前 15 名中 8 个 B601 专属、4 个 Reachy 专属、**0 个共享抽象** |
| 团队实际速度 | 近 90 天 **21 个 commit**，全仓库共 59 个 commit |
| 把"半通 + 纯壳"补成可承诺状态 | 需 **12–20 人周（3–5 人月）** |

### 根因

**每一层都选了宽度优先，没有一层做深度优先。** 入口宽（云端 + 本机 + 6 机型 + 3 种安装方式）、功能宽（23 页 / 39 节点 / 28 路由）、机型宽（6 型号），但每层真正跑通的路径只有一两条。

"没人用"和"维护不动"是同一个病的两面。按 12–20 人周 vs 21 commits/90 天的对比，**补不完**。因此本计划的主线是**删除与收敛，不是补全**。

### 定位收窄（执行取舍的依据）

对内执行口径（M28 当时写法，**2026-07-31 已部分修正**）：

> ~~BotverseX 是机器人教学实验室的多人数据采集与训练控制台。一个人装好，一屋子人用浏览器进来。~~

**修正：**「摊薄安装成本」方向对；**买家写成教学实验室招标是错的**（他们买开课方案，不买 MLOps SaaS；且痛点正是装环境，而本平台也要求装 2.9 GB）。  
当前真相：目标用户在「必装 lerobot」架构下接近空集；下一步先做用户访谈，再决定 WebSerial。见 [`docs/strategy/2026-07-31-product-truth-and-next.md`](../docs/strategy/2026-07-31-product-truth-and-next.md)。

凡是不降低「有硬件 → 第一次能动」门槛、又没有外部用户信号的功能，一律不加代码。

---

## 1. 非目标（明确不做，避免执行者好心加戏）

以下内容留在 `docs/strategy/` 作为融资叙事，**本阶段不得新增任何实现代码**：

- 跨本体 Skill 迁移 / Skill Marketplace 上架流程
- Isaac Sim 仿真预训练链路
- Qualia Studio 的 6 个生成类节点（world_model_generator 等）
- 新机型接入（第 7 台机器人）
- 支付/订阅计费系统的真实接入

依据：`docs/strategy/investor-red-team-memo.md` 已明确 "Marketplace 是产品期权"、"Seed 轮买的是 LeRobot 真机 MLOps"。产品侧照此纪律执行即可。

**另有两条硬约束：**

- **不要重构 `components/b601/` 和 `components/reachy/`。** 这一万行虽然是债务，但它们能跑，改动风险高、收益低。新架构只在新机型上验证。
- **不要动 `apps/realtime/api/b601.py`（4862 行）的内部逻辑。** 同上。

---

## 2. P0 · 防演示翻车（目标：1 个工作日内全部完成）

这一组全是删除和禁用，无新功能，风险极低。做完之后平台在投资人/客户面前不会因为假数据或假成功而失信。

### T0-1 · 修复一键安装脚本的仓库地址 ✅ 已完成（2026-07-31）

**问题**：`scripts/install-botversex-agent.sh:14` 的 `AGENT_REPO` 拼写为 `metahubifeel`（缺一个 a），实际仓库是 `metahubaifeel`。

验证结果：

```
https://github.com/metahubaifeel/botversex-local-agent  → 200
https://github.com/metahubifeel/botversex-local-agent   → 404
```

**影响**：`curl .../agents/install.sh?token=JWT | bash` 这条带 token 的一键安装路径，任何人执行都会 clone 失败。B601 客户走的正是这条路。

**已改**：`scripts/install-botversex-agent.sh:14` 改为 `metahubaifeel`。全仓库已无 `metahubifeel` 残留。

---

### T0-2 · 删除 Dashboard 的硬编码假数据集

**目标**：首页不再出现平台里根本不存在的数据集。

**问题位置**：

```48:50:apps/web/src/pages/Dashboard.tsx
  const [mockDatasets] = useState<Dataset[]>([
    { id: '1', name: 'pick_place_v1', episodes: 50, frames: 12500, size: '2.3 GB', createdAt: '2026-03-20', robotType: 'SO-100' },
  ])
```

被消费于 `Dashboard.tsx:241`（RecordingModal）和 `Dashboard.tsx:246`（TrainingModal）。

**为什么严重**：机型写的是 `SO-100`，平台目录里根本没有这个型号。客户或投资人看到这条假数据，会连带怀疑上方四张 StatCard 的真实统计（那部分是真的，走 `/api/v1/stats` → `apps/api/app/api/v1/endpoints/stats.py:23-71`）。

**怎么改**：

1. 删除 `mockDatasets` 的 useState 声明。
2. 改为调用真实数据集列表。参考 `apps/web/src/pages/Datasets.tsx:54-62` 的加载方式（合并 realtime 磁盘扫描 + API DB）。
3. 若加载失败或为空，弹窗内显示空状态文案（例如"还没有数据集，先去录一段"+ 跳 `/robots`），**不要**回退到任何硬编码样例。

**验收标准**：

- 全库搜索 `mockDatasets` 无结果。
- 未录制过任何数据的全新账号，打开 Dashboard 的 Record/Train 弹窗，看到的是空状态而不是 `pick_place_v1`。

**工作量**：1–2 小时。

---

### T0-3 · Workflow finetune 的 demo fallback 改为硬失败

**目标**：训练提交失败时，节点不能显示为成功。

**问题位置**：`apps/web/src/lib/workflowEngine.ts:316-350`

当 Qualia API 调用抛异常时，catch 分支会：模拟 20→100 的进度、生成 `demo_xxxxxxxx` 假 jobId、设置 `result.simulated = true`、然后**正常返回**。因为没有再抛出，节点最终被标记为 **success（绿色）**。

日志里确实写了 `⚠ Finetune API unavailable — entering DEMO FALLBACK` 和 `this is NOT a real training job`，但演示时没人展开看日志，只看到节点变绿。

**为什么严重**：这比崩溃更伤信誉。崩溃是"产品不成熟"，显示成功是"产品在骗人"。

**怎么改**（二选一，推荐 A）：

- **方案 A（推荐）**：删除整个 fallback，catch 里直接 `throw`，让节点进入 error 状态，错误文案写清"云端训练后端未配置（缺 QUALIA_API_TOKEN）"。
- **方案 B**：保留 fallback 但引入独立的节点视觉状态 `simulated`（黄色/条纹），绝不复用 success 的绿色，且节点标题上直接打"模拟"角标。

同时检查 `workflowEngine.ts:355` 起的 `job_monitor`，它已经会读 `job?.simulated`，改完后需保持一致。

**验收标准**：在未配置 `QUALIA_API_TOKEN` 的环境跑一次 finetune 工作流，节点**不是**绿色 success。

**工作量**：1–2 小时（方案 A）/ 半天（方案 B）。

---

### T0-4 · 隐藏 4 个没有执行器的 Workflow 节点

**目标**：palette 里能拖出来的节点，运行时不能抛 `Unknown node type`。

**问题**：`workflowEngine.ts:1094-1095` 的 default 分支直接 throw。以下 4 个节点有模板、有类型定义、在 palette 里可见，但 engine 里没有 case：

| 节点 | 模板位置 | 类型定义 | palette 位置 |
|------|----------|----------|--------------|
| `camera_denoise` | `store/workflowStore.ts:638` | `types/workflow.ts:50` | `NodePalette.tsx:195` |
| `trajectory_optimize` | `store/workflowStore.ts:650` | `types/workflow.ts:51` | `NodePalette.tsx:195` |
| `isaac_sim_pretrain` | `store/workflowStore.ts:724` | `types/workflow.ts:41` | `NodePalette.tsx:181` |
| `lekiwi_handshake_collect` | `store/workflowStore.ts:748` | `types/workflow.ts:42` | `NodePalette.tsx:188` |

> 注：`isaac_sim_pretrain` 和 `lekiwi_handshake_collect` 是 2026-07 新加的模板，加了模板没加执行器。

**怎么改**：从 `NodePalette.tsx` 的分类列表里移除这 4 个 type（保留 store 模板和类型定义，便于日后接执行器）。若 `SIMULATION` / `SCENARIO` 分类移除后为空，整个分类一起隐藏。

**注意**：LeKiwi 握手闭环在**专页**（`apps/web/src/pages/RobotLeKiwi.tsx:348` + `apps/realtime/api/lekiwi.py:621-876`）是真能跑的，只有 Workflow 节点形态不能跑。隐藏节点不影响专页功能。

**验收标准**：遍历 palette 里所有可拖节点，逐个拖进画布点运行，无一抛 `Unknown node type`。

**工作量**：1 小时。

---

### T0-5 · 禁用 AI Hub 的 Download 按钮

**目标**：不要暴露会 404 的按钮。

**问题**：`apps/web/src/pages/AIHubDetail.tsx:74` 调 `downloadFromHub`，指向的后端路由 `POST /api/v1/hub/download` **不存在**。

同页另有硬编码内容需处理：
- `AIHubDetail.tsx:50-64`：API 失败时塞占位元数据
- `AIHubDetail.tsx:212-234`：README 是模板文案，不是真实 README
- `AIHubDetail.tsx:316-330`：Similar Models 是硬编码列表

**怎么改**（最小成本）：

1. Download 按钮改为 disabled + tooltip"暂未开放"，或直接改成跳转 HuggingFace 原页的外链。
2. Similar Models 区块整块隐藏。
3. README 区块：拉不到真实 README 时显示"前往 HuggingFace 查看"外链，不要显示模板文案。

**验收标准**：AIHubDetail 页面上不存在任何点了会 404 或显示假内容的元素。

**工作量**：2 小时。

---

### T0-6 · Pricing 页瘦身

**目标**：不展示无法完成的支付动作。

**问题**：`apps/web/src/pages/Pricing.tsx` 共 385 行。套餐 catalog 和限额 gating 是真的（`entitlement_service.py:18` 生效），但"升级到 xxx"按钮只 `navigate('/')`，页面自己写着"支付接入开发中，内测请联系管理员开通"（`Pricing.tsx:311`）。Stripe 是 stub（`billing.py:27-42`）。

**怎么改**：三档套餐的能力对比表保留（有信息价值），把"升级"按钮统一换成"申请内测 / 联系我们"，指向 `CONTACT` 配置里的联系方式（`apps/web/src/config/contact.ts`）。目标把 385 行压到 150 行以内。

**注意**：不要动 `entitlement_service.py` 的限额逻辑，那部分是真生效的。

**验收标准**：页面上没有任何暗示"点了就能付款升级"的元素。

**工作量**：2 小时。

---

## 3. P1 · 救活已存在的零安装入口（目标：一周内）

### 背景（执行者必读）

审计发现一件很重要的事：**零安装的云端虚拟 demo 已经存在了，但被架构自己废掉了。**

Reachy Mini 的 `?guide=virtual` 路径走的是云端 realtime（`infra/docker/nginx.conf:51-57` 把 `/api/*` 代理到服务端 realtime 容器），服务端有内存虚拟状态机（`apps/realtime/api/reachy_proxy.py:86-711`），manifest 里也声明了 `"virtual": true`（`apps/realtime/config/robots.json:107`）。用户**完全不需要装 Local Agent** 就能看到机器人动、播放预设动作、看 3D 孪生。

但它现在有两个致命问题，P1 就是修这两个。

---

### T1-1 · 修复 localStorage 对云端虚拟路径的劫持

**目标**：做过 Setup 的用户，云端虚拟 demo 不能突然要求本机 Agent。

**问题位置**：

```15:15:apps/web/src/lib/localAgent.ts
const CATALOG_PATH_PREFIXES = ['/api/robots', '/api/runtimes', '/api/urdf'] as const
```

`shouldRouteToLocalAgent()`（`localAgent.ts:165-168`）的规则是：**只要不在 catalog 白名单里，且 localStorage 存了 Agent URL，就发到本机 Agent**。

而 Reachy 虚拟模式用的是 `/api/reachy/virtual/status`、`/api/reachy/virtual/start`、`/api/reachy/virtual/stop`（`apps/web/src/lib/reachyApi.ts:420-430`）以及 `/api/reachy/move/*`、`/api/reachy/state/full` 等——**全都不在白名单里**。

结果：用户装过一次 Local Agent 之后（哪怕是为了别的机型、哪怕 Agent 现在没开），云端虚拟 demo 就开始往 `https://localhost:8002` 发请求并失败。

**怎么改**（推荐方案 B）：

- **方案 A**：把 `/api/reachy/virtual` 加进 `CATALOG_PATH_PREFIXES`。缺点是治标，`/api/reachy/move/*` 等虚拟模式也要用的路径还是会被劫持。
- **方案 B（推荐）**：引入显式的"强制同源"开关。在 `agentFetch` 的 init 上加一个 `forceSameOrigin?: boolean`，虚拟模式下的所有调用传 true；或在 reachyApi 层判断当前是虚拟模式时统一走原生 `fetch` 而非 `agentFetch`。

**验收标准**：
1. 在浏览器 localStorage 手动写入 `botversex_local_agent_url = https://localhost:8002`；
2. **不启动**任何本地 Agent；
3. 打开线上 `/robots/reachy_mini?guide=virtual`，点虚拟模式，动作能正常播放。

**工作量**：半天。

---

### T1-2 · 把零安装虚拟 demo 提到首屏第一 CTA

**目标**：新访客落地后第一个能点的东西，是 30 秒就能看到机器人动的路径，而不是 2.9 GB 安装。

**现状问题**：

- `/` 和 `/robots` 都渲染机器人目录页（`apps/web/src/App.tsx:92-94`），未登录可看，这点是对的。
- 但 `apps/web/src/lib/robotCatalog.ts:25` 给 SO-101 设了 `previewPriority: 0`，它排第一张卡，CTA 是"进入向导"——直通真机安装死路。
- Reachy 虚拟在第二张卡，且需要点进详情页才能发现虚拟模式（`Robots.tsx:258` 的 `?guide=virtual`）。
- 只有走"新手引导"的无硬件分支（`components/onboarding/tours.ts:109-117`）才会明确告知"无需安装 Agent"。

**怎么改**：

1. 在 `apps/web/src/pages/Robots.tsx` 顶部 hero 区（现在是 `Robots.tsx:115-130` 的 Fleet 横幅）加一个主 CTA：**"没有机器人？先在浏览器里试一台"**，直达 `/robots/reachy_mini?guide=virtual`。
2. 该 CTA 视觉权重高于任何机型卡片的按钮。
3. 机型卡片上，凡 manifest 里 `capabilities.virtual === true` 的，额外加一个次级按钮"浏览器试用（无需安装）"。目前只有 Reachy Mini 满足。

**验收标准**：全新无痕窗口打开线上首页，**首屏不滚动**即可看到并点击到无需安装的体验入口，且点进去 30 秒内能看到机器人动。

**工作量**：半天到一天。

---

### T1-3 · 上手文档与 Setup 页对齐真实路径

**目标**：文档不再把"装 Agent"写成第一步。

**现状**：`docs/customer-quickstart.md:17-23` 的"四步连接"直接从安装开始，`Setup.tsx:84-88` 的进度条也是 Install → Run → Trust cert → Connected。

**怎么改**：在两处前面都加一层前置分流：

- **只是想看看** → 浏览器虚拟体验，零安装（给链接）
- **有 SO-101 / Reachy / B601 真机** → 才进入 Local Agent 四步

同时把"信任自签证书"这一步的说明前置到安装说明里，不要等用户装完才发现还有这一关。

**验收标准**：`docs/customer-quickstart.md` 第一屏就能看到零安装路径。

**工作量**：2 小时。

---

## 4. P2 · 决定三个月后还改不改得动（目标：一个月内）

### T2-1 · WebSerial 零安装接 SO-101

**目标**：把"连接 → 识别 → 点动 → 主从遥操作"从 Local Agent 里解放出来，搬进浏览器。

**依据**：`apps/realtime/dora-bambot/` 是 bambot.org 的站点快照，就在本仓库里。它的 `_next/static/chunks/881-47c588f365fe1541.js` 里用了 `navigator.serial` —— **同样的 Feetech STS3215 舵机，人家零安装就能在浏览器里驱动**。而当前 BotverseX 前端一行 WebSerial 都没有（全库搜 `navigator.serial` 零命中）。

**能搬进浏览器的**：

| 能力 | 浏览器 API |
|------|-----------|
| 串口连接 / 舵机扫描 / 读写位置 | WebSerial (`navigator.serial`) |
| 摄像头预览 | `getUserMedia` |
| 主从遥操作 | WebSerial 双端口 |
| episode 存盘 | File System Access API 或直传云端 |

**必须保留 Local Agent 的**：CAN 总线机型（B601 达妙 / RobStride）、LeKiwi 的 ZMQ host、ROS2、高频控制环、大数据集本地存储。

**怎么做**：

1. 新建 `apps/web/src/lib/webserial/`，实现 STS3215 半双工协议（1 Mbps）：ping、读位置、写位置、扭矩开关。
2. SO-101 页面新增"浏览器直连"模式，与现有"Local Agent"模式并列，浏览器不支持 WebSerial（Firefox/Safari）时自动隐藏并提示用 Chrome/Edge。
3. Local Agent 在文案上降级为"进阶：接 CAN 臂 / 跑高频控制 / 本地存大数据集时再装"。

**验收标准**：Chrome 里全新无痕窗口，不装任何本地软件，插上 SO-101，能完成：授权串口 → 扫到 6 个舵机 → 拖滑条让某个关节动。

**风险**：WebSerial 仅 Chromium 系支持。对教育场景可接受，需在 UI 明示。

**工作量**：2–3 周。

---

### T2-2 · 用 LeKiwi 当试验田，立起 manifest 驱动的通用工作台

**目标**：让"新增一台机器人"的边际成本从 ~6000 行降到 ~200 行。

**现状成本**（来自维护成本审计）：

| 成熟度 | 需改文件数 | 需写代码行数 |
|--------|-----------|-------------|
| Preview（只有 3D 卡片） | 8–10 | 250–450 |
| LeKiwi 级 | 15–22 | 1800–2800 |
| B601 级（全功能工作台） | **35–45** | **4500–8000+** |

**目标形态**：`/robots/:runtimeId` 只有**一个**通用工作台页面，读 manifest 的 `capability_tags`，从面板注册表渲染：

```
capability_tags: ["teleop", "record", "calibrate", "camera", "joints_live"]
        ↓
通用工作台 → ConnectPanel / TeleopPanel / RecordPanel / CameraPanel / JointsPanel
```

达标线：**新增一台机器 = 1 条 manifest 条目 + 1 个约 200 行的 runtime adapter + 0 个新页面 + 0 个新 API 路由。**

**为什么选 LeKiwi 当试验田**：`apps/web/src/pages/RobotLeKiwi.tsx` 只有 382 行，没有专属组件目录，改造成本最低，且它本来就缺 inference 闭环 UI，正好一起补。

**执行顺序（严格遵守）**：

1. 先在 LeKiwi 上把通用工作台立起来并验证；
2. 成熟后把 Reachy 迁过去；
3. **B601 最后迁，或永不迁**（4862 行的 `b601.py` + 5023 行组件，风险高收益低）。

**工作量**：3–4 周。

---

### T2-3 · 清理死抽象与重复定义

**目标**：让 manifest 说的话算数，减少"改一处要同步三处"的心智负担。

**死字段（要么接线要么删）**：

| 字段 | 位置 | 现状 |
|------|------|------|
| `state_endpoint` | `robots.json:187,265,350,442,509,577` | 代码零引用，实际统一走 `GET /api/robots/{id}/state`（`robots.py:379-409`） |
| `ui.onboarding_steps` | `robots.json` + `fallbackRobots.ts:14,24,35` + `robotApi.ts:43` | SetupProvider 不读，步骤硬编码在 `setup-types.ts:116-118` |
| `RUNTIME_CAPABILITIES` / `capability_tags()` | `runtimes/_capabilities.py:51-59` | **从未被 import** |
| `catalog_family` / `catalog_variants` / `catalog_parent` | `robotApi.ts:13-17` | 只有类型定义，前端零消费 |

**三份重复的 catalog 元数据**（同一台机器人的标题/描述写三遍）：

1. `apps/realtime/config/robots.json`
2. `apps/web/src/lib/robotCatalog.ts:19-92`
3. `apps/web/src/lib/fallbackRobots.ts:4-37`

外加 `RobotPreview.tsx:29-82` 的 `PREVIEWS` 字典是第四份。

**改法**：以 `robots.json` 为唯一真相源，`robotCatalog.ts` 只保留前端专属的视觉参数（相机位置、图标、加载优先级），描述文案从 manifest 取。`fallbackRobots.ts` 缩减为仅在 API 完全不可达时提供最小骨架。

**手写路由去重**：`App.tsx:96-185` 有 9 条手写机型路由，`routePrefetch.ts:5-17` 又写一遍。改为按 manifest 的 `ui.route` 生成一条动态路由。

**后端去分支**：`robots.py:382-499` 有 `so101` / `reachy_mini` / `b601_rs` 三段硬编码分支 + 一个 generic 分支。目标是全部走 `_generic_runtime_state` + runtime reader，把 `stream_b601_state` 下沉到 runtime 包。

**工作量**：1–2 周（可与 T2-2 合并推进）。

---

## 5. 优先级速查表

| ID | 任务 | 优先级 | 工作量 | 风险 |
|----|------|--------|--------|------|
| T0-1 | 修安装脚本仓库地址 | P0 | ✅ 已完成 | 无 |
| T0-2 | 删 Dashboard 假数据集 | P0 | 1–2h | 低 |
| T0-3 | finetune demo fallback 改硬失败 | P0 | 1–2h | 低 |
| T0-4 | 隐藏 4 个无执行器节点 | P0 | 1h | 低 |
| T0-5 | 禁用 AI Hub Download + 假 README | P0 | 2h | 低 |
| T0-6 | Pricing 页瘦身 | P0 | 2h | 低 |
| T1-1 | 修 localStorage 劫持云端虚拟路径 | P1 | 0.5d | 中 |
| T1-2 | 零安装 demo 提到首屏第一 CTA | P1 | 0.5–1d | 低 |
| T1-3 | 文档与 Setup 页加零安装分流 | P1 | 2h | 低 |
| T2-1 | WebSerial 零安装接 SO-101 | P2 | 2–3w | 中 |
| T2-2 | LeKiwi 试验田：manifest 驱动通用工作台 | P2 | 3–4w | 中 |
| T2-3 | 清理死抽象与重复定义 | P2 | 1–2w | 中 |

---

## 6. 部署提醒（执行者容易踩的坑）

线上 `botversex.feispace.me` 的部署链路：

- 服务器：阿里云 ECS `47.113.126.51`（hostname `iZwz9fycu1g7v5pujy4l2cZ`），SSH key `~/.ssh/id_ed25519_ecs`
- 代码目录：`/opt/botversex`（**不是 git 仓库**，靠 rsync 同步）
- 容器：`botversex-web`（:18080）、`botversex-api`、`botversex-realtime`（:8002）
- 系统 nginx 反代 `botversex.achao.xin` 和 `botversex.feispace.me` 到 127.0.0.1:18080

**坑 1**：本地改完必须 rsync + 重建镜像，否则线上一直是旧版本。2026-07-31 就发现线上跑着 6 周前的 web 容器。

同步命令（注意排除清单，仓库里有 20 GB 的 venv 和 8.3 GB 的 pi0_sidecar）：

```bash
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

ssh -i ~/.ssh/id_ed25519_ecs root@47.113.126.51 \
  "cd /opt/botversex && docker compose -f infra/docker/docker-compose.prod.yml up -d --build web realtime"
```

**坑 2**：`apps/realtime/api/robot_config.py:20` 的 `load_robot_config()` 带 `@lru_cache`，改了 `robots.json` 必须**重启 realtime 进程**才生效，重新加载页面没用。

**坑 3**：改 URDF 或 mesh 后，必须同步更新 `urdf_url` 的 `?v=` 版本号（`robots.json` 和前端引用处都要改），否则浏览器一直用旧缓存。2026-07-31 的 AmazingHand / Unitree G1 就是因为漏了这个参数，官方 CAD 资产明明已经在磁盘上，用户看到的还是旧的占位圆柱体。

**坑 4**：本地重启用 `scripts/linux/botversex-restart-local.sh`（会 kill 掉旧进程再拉起 web/api/realtime）。

---

## 7. 参考：三份审计的完整结论

本计划基于 2026-07-31 的三份审计。若需要更细的文件级证据，可查阅当时的 agent transcript；核心数字与结论已全部提炼进本文档第 0 节。

审计范围：
1. **新用户上手路径** — 未登录首页、Setup 四步、Local Agent 分发、10–13 步真机路径、外部依赖清单、12 项摩擦点排行
2. **每加一台机器人的维护成本** — manifest 字段有效性、runtime_id 散落统计、三条机型路径对比、专属代码行数、过度抽象 vs 抽象不足
3. **真实能力 vs 演示外壳** — 逐页 A/B/C 三组分类、39 个 Workflow 节点执行能力统计、补全工作量估算
