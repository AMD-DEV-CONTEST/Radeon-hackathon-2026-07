# BotverseX Roadmap

长期待办与优先级。Agent 会话里的 Todo 可能换对话后找不到，**以本文件为准**。

最后更新：2026-08-06（WebSerial S1–S3 + U1–U4 完成、M28 全部落地、部署就绪清单与访谈门禁见 strategy/）

---

## 当前总叙事：具身智能的数据闭环入口

BotverseX 的主线不是“很多机器人页面”，也不是“只做机械臂控制台”。

> **BotverseX 要做具身智能的数据闭环入口。**  
> 让更多人用更低门槛接入真实机器人、采集真实场景数据、训练技能、部署回真实世界。

核心因果链：

```text
真实场景
  → 低门槛接入机器人
  → 采集带图像 / 关节 / 时间戳 / 结果反馈的数据
  → 训练 / 微调 / 评估
  → 部署回真实机器人
  → 封装成 Skill 复用和分发
```

具身智能真正缺的，不只是模型，也不只是机器人硬件，而是高质量真实世界数据。这些数据不在网页上，它在工厂、实验室、学校、仓库、厨房、桌面任务和各种具体场景里。很多场景拥有者还不知道：他们手里的动作、任务、失败案例和环境变化，本身就是未来机器人模型最有价值的训练数据。

BotverseX 要做的是把「场景」变成「数据」，再把「数据」变成「技能」。

### SpaceX 类比（融资叙事备用）

SpaceX 的意义不只是造火箭，而是降低了进入轨道的成本，让更多东西能被送上去。

BotverseX 的意义不是造更多机器人，而是降低进入具身智能数据闭环的成本，让更多人、更多场景、更多硬件能快速产生真实机器人数据，并把它变成可运行、可复用的技能。

> SpaceX 降低了进入轨道的成本；BotverseX 想降低真实世界机器人数据闭环的成本。

### Reddit 类比（数据价值备用）

Reddit 的数据价值来自人类表达：讨论、偏好、经验和文本内容成为模型训练来源。

BotverseX 的数据价值来自真实世界交互：机器人操作、任务、失败、修正、环境变化，以及带时间戳、图像、动作、关节和结果反馈的物理世界数据。

### 当前模块如何落在这条主线上

| 模块 | 在大故事里的位置 |
|------|------------------|
| SO-101 / Reachy / 更多 Runtime | 低门槛真实数据采集端 |
| Local Agent / Realtime / Runtime | 让真实硬件接入平台并在本机运行 |
| Record / Dataset | 把场景变成可训练数据 |
| Training / Workflow | 把数据变成模型和技能 |
| Skills | 把能力封装、复用、分发 |
| AI Hub / HF | 接入开源模型和数据生态 |

### 对外主句

> 未来机器人智能的瓶颈，是高质量真实世界数据；BotverseX 要成为让更多人产生这些数据、训练这些技能、部署回真实机器人的入口。

---

## 生态定位：我们、Hugging Face、LeRobot

### 我们究竟是不是「硬件版 Hugging Face」？

**不完全是——对外建议少说这个比喻，多说下面这句（团队共识）：**

> **BotverseX 是降低机器人「采集 → 训练 → 部署 → 复用」闭环成本的平台，不是卖铁。**

| | **Hugging Face** | **BotverseX** |
|--|------------------|---------------|
| 核心资产 | 模型、数据集、Spaces、社区托管 | **真机上的技能开发、运行、分发** |
| 硬件 | 一般不造机；现推动 LeRobot Humanoid 等 **生态项目** | **不造机**；接 Runtime 适配器 |
| 用户典型动作 | 下载权重、推 dataset、跑 Space | 插电、Wiggle、录数据、训练、部署、装 Skill |
| 和 LeRobot 关系 | 托管与传播 | **消费 LeRobot 数据格式，在其上建平台层** |

更准确的一句话定位（见 `docs/strategy/platform-manifesto.md`）：

> **机器人技能的开发平台、本地运行时，和未来技能市场。**

若投资人非要类比：

- **HF** ≈ 模型与数据的 **Hub**（仓库）  
- **LeRobot** ≈ 机器人学习的 **工具链 + 数据格式 + 开源硬件生态**  
- **BotverseX** ≈ 让能力在真机上 **跑起来并被打包分发** 的 **平台 / Skill OS 入口**（不是第三个 HF）

### 我们有没有像 Hugging Face 一样「铺开源硬件 + 数据格式」？

| 层 | Hugging Face / LeRobot 社区 | BotverseX 今天 |
|----|----------------------------|----------------|
| **开源硬件** | LeRobot Humanoid、SO-100/101 等 **由社区/HF 发布** | **不铺硬件**；选用开放硬件，做 **Runtime + 网页闭环** |
| **数据格式** | **LeRobotDataset**（Parquet + 视频/图）为事实标准 | **兼容**该格式录制与训练；另定 **BotClaw Skill** schema（`packages/botclaw-spec`） |
| **模型权重** | HF Hub 托管 | **AI Hub 发现** HF 模型；本地 **Models** 存 checkpoint |
| **技能商品** | 无统一「机器人 Skill 商店」 | **Skills 注册表** + 未来 **Marketplace**（在建） |

**结论：** 我们和 HF **协作大于竞争**——他们把 **硬件种类和数据生态** 做大；我们把 **真机闭环与 Skill 封装** 做省。不要对外声称「我们在铺开源硬件」；应声称 **「站在 LeRobot / HF 开源生态之上，做开发与分发层」**。

### LeRobot 生态里有什么（和我们会用到的部分）

```text
huggingface/lerobot          # 主库：策略、训练、数据集工具、多机 teleop 脚本
  ├── LeRobotDataset 格式    # 我们 Record / Dataset / Training 对齐
  ├── 支持/文档中的硬件      # SO-100/101, Koch, HopeJR, Reachy2, OpenARM, Unitree G1…
  └── 策略与 VLA             # ACT, Diffusion, SmolVLA 等；我们 Training / Inference 可接

HF Hub                       # 数据集与模型托管；我们 AI Hub 代理发现 + publish 数据集

BotverseX（我们）            # 浏览器 + API + Realtime + Runtime + Skill，不替代 lerobot 训练库
```

**我们依赖 LeRobot 的方式：** 数据与训练管线兼容、依赖声明在 `robots.json`（如 `lerobot`、`lerobot-teleoperate`），**不 fork 整个 lerobot 作为产品**。

---

## Runtime 路线图

真源：`apps/realtime/config/robots.json` + `apps/realtime/runtimes/*`。  
原则：**同一套网站流程，底下换 Runtime；技能带 `compatible_types`，不吹跨机型万能。**

| 阶段 | runtime_id | 形态 | 能力（摘要） | 状态 |
|------|------------|------|--------------|------|
| **NOW · 楔子** | `so101` | Leader/Follower 臂 | 一条龙：遥操作、录制、训练、推理、相机 | **已跑通** |
| **NOW · 多机型证明** | `reachy_mini` | 人形台座 + daemon | 状态流、预设/自定义动作、电机模式、virtual；示教→Dataset→Skill **进行中** | **已接入，能力递进中** |
| **NOW · CAN 臂** | `b601_rs` | CAN 从臂 + Star Arm 主臂 | LeRobot teleop/record/calibrate、3D 跟动、通用 state WS、**Pinocchio FK/IK、重力补偿、ROS2 bridge** | **已跑通** |
| **SOON · 产业伙伴** | `unitree_*`（待定） | 四足 / 商用狗 | 依赖伙伴 SDK + 样机；**优先于 DIY 人形** 若商务谈拢 | **预研 / 洽谈** |
| **WATCH · 生态** | `lerobot_humanoid`（待定） | HF $2.5k DIY 双足 | 跟 `lerobot-humanoid` 栈稳定度；见下节 | **观察项，不承诺日期** |
| **LATER** | `more…` | 工业臂、教育臂等 | 每增加一类 = 新 Runtime + manifest，非新网站 | 路线图 |

**每个 Runtime 交付标准（验收）：**

1. `GET /api/runtimes` 可见，`robots.json` 条目完整  
2. 网页 **Robots** 路由可 demo（至少：连接 / 状态 / 一项能力）  
3. 若支持录制：产出 **LeRobot 兼容** episode 或明确标注仅轨迹原料  
4. **Skills** 可声明 `compatible_types` 匹配该 `robot_type`  

**口播：** 「臂是楔子，狗是扩张，人形跟 LeRobot 开源节奏走 Runtime，不抢 SO-101 主线。」

---

## WebSerial 零安装接入（P0 · 当前执行主线）

> 对应执行权威 `docs/strategy/2026-07-31-product-truth-and-next.md`：证明不装 2.9GB Agent 让人第一次让机械臂动起来。
> 设计全文：`docs/webserial-design.md` ｜ 研究依据：`docs/research-log.md`（2026-08-06）

| 步 | 交付 | 状态 |
|----|------|------|
| 设计 | 选型 + 架构 + 分步计划（浏览器直连 Feetech 总线，绕过 realtime 服务器） | **已完成（2026-08-06）** |
| S1 | `apps/web/src/lib/webserial.ts` 协议层移植（参考 dora-bambot 快照，类型化） | **已完成（2026-08-06）** |
| S2 | Robots 页「浏览器直连」按钮 + ping 电机 1..N | **代码侧完成（2026-08-06）**：两套实现合并（`StsSerialBus` 收敛进 `lib/webserial.ts`，删 `sts3215.ts`），面板接入通用层；真机验收待硬件 |
| S3 | 第一个动作：writeGoal + 3D twin 本地跟随 | **代码完成（2026-08-06）**：3D 孪生跟动接入仪式（SO-101 URDF 关节名 = 电机 ID，count→rad 实时驱动）；真机验收待硬件 |
| S4 | 状态轮询 + 连接生命周期（disconnect/tab 竞争） | 待做 |
| S5 | WebSerial 录制 → 现有 Record/Dataset 管线（LeRobot 对齐） | 验证后 |
| U1 | 第一动作仪式：90 秒三步（授权→扫描点亮→挥手🎉+首录 CTA），滑条降级高级层，故障给排查指引 | **代码完成（2026-08-06）**；真机验收待硬件 |
| U2 | 首页二元入口：主 CTA 换为 SO-101 浏览器直连（真机零安装优先），虚拟降为次级入口 | **已完成（2026-08-06）** |
| U3 | 3 秒首录闭环（S5 最小版：WebSerial 录制 → 第一条 dataset） | **代码完成（2026-08-06）**：`POST /api/datasets/record`（parquet + botclaw.json，列表可识别，后端已功能验证）；面板 3 秒采样入库；真机录制验收待硬件 |
| U4 | 串口诊断（端口枚举/波特率探测/ID 扫描/日志导出） | **代码完成（2026-08-06）**：`SerialDiagnostics` 组件（浏览器内诊断，1M/115200/9600 三档探测 + getPorts 枚举 + 日志下载）；接入扫不到舵机卡片与断开态入口；真机验证待硬件 |
| G1 | 访谈门禁（H1 装环境卡点 / H2 零安装消除卡点 / H3 买家画像 → 决定 U3 优先级） | **材料完成（2026-08-06）**：`docs/strategy/2026-08-06-interview-gate.md`（脚本/记录模板/决策规则）；5 场执行待安排 |
| U5 | 导航收敛第一刀：Build 组降级为「实验室」（zh/实验室 · en/Lab · ja/ラボ），路由不动 | **已完成（2026-08-06）**；深水区（Setup/Settings 合并、空转入口下线、AI Hub 入口去留）待访谈/用户信号 |

适用边界：**仅 Feetech 总线（SO-101 主线）**；Reachy（Dynamixel）与 B601（Robstride CAN）不属本路径。

---

## LeRobot Humanoid（观察项）

**来源：** [HF 博客](https://huggingface.co/blog/VirgileBatto/lerobot-humanoid) · 仓库 [Virgileboat/lerobot-humanoid](https://github.com/Virgileboat/lerobot-humanoid)（约 $2,500 DIY 双足，全栈开源：硬件文档、runtime、标定、训练环境）。  
**与主库关系：** 可能与 `huggingface/lerobot` 逐步收敛；**以主库 release 与 supported hardware 列表为准**，不单押独立 repo。

### 对我们有什么用

| 类型 | 说明 |
|------|------|
| **叙事 / 融资** | 印证「硬件趋廉价、价值向软件与数据迁移」；HF 把开发者基数做大，我们做 **闭环与 Skill 层** |
| **产品（中期）** | 若栈稳定，新增 Runtime `lerobot_humanoid`；Dataset/Train/Workflow **大概率复用 LeRobot 格式** |
| **AI Hub** | 相关模型/数据集发现与标签，**不承诺「已支持」** |
| **不是** | 当前融资主线、主 demo、第一批采购清单 |

### 这个仓库对我们有用吗？

| 有用 | 暂时不做 |
|------|----------|
| 读 **runtime / 标定 / 仿真** 接口设计，预研 BotverseX Runtime 边界 | 全员转人形或 3D 打印支持 |
| 跟踪是否进入 **lerobot 官方 supported hardware** | 对外写「已全面支持 LeRobot Humanoid」 |
| 基金/社区沟通时作 **「下一类 Runtime」** 由头 | 用融资款批量买套件（除非赞助或共创） |

### 触发条件（满足 ≥3 条再立项 P1）

- [ ] `huggingface/lerobot` 或 humanoid 子项目有 **稳定 release**，社区有人跑通 teleop + record  
- [ ] SO-101 一条龙与 Workflow Finetune 链 **已稳**，不抢主线人力  
- [ ] 有 **明确用户或伙伴**（实验室/HF/赞助样机）共建  
- [ ] 能说清第一个 **Skill 动词**（如站立/缓步/挥手），而非「先接上再说」  
- [ ] 安全与标定流程可写入 **Setup 向导**，不全靠用户自助装机  

### 待办（观察期内仅 P2）

| 优先级 | 项 | 说明 |
|--------|-----|------|
| **P2** | 生态跟踪纪要 | 每两周看 repo release / lerobot 主库是否收录 |
| **P2** | 技术 spike（≤3 人日） | 仿真或单机跑通官方 quickstart，输出 Runtime 接口草图 |
| **P2** | 对外话术统一 | 与 `Robots.tsx`「Humanoid on roadmap」一致；演示稿用本文「观察项」表述 |

### 产品叙事（对外怎么说）

- **今天能说：** 「我们跟 **LeRobot / Hugging Face 开源生态** 对齐；SO-101 已跑通真机闭环；人形开源把市场做大，我们做的是 **降低采集与闭环成本的平台**。」  
- **还不能说：** 「已支持 LeRobot Humanoid」「人形是主 wedge」。  
- **/twitter 观点可接：** 「硬件占比较小，数据与技能闭环是护城河」——对应我们 **原料 → Workflow 工厂 → Skill 商品 → 商店** 模型（见上一节）。

---

## 核心抽象：原料、工厂、商品、商店

BotverseX 里不要把一段关节角时间序列直接叫做 Skill。机械臂动作序列是训练和演示的**原料**；Skill 是可安装、可运行、可更新、可分发的**能力包**。

| 概念 | 是什么 | 不是什么 |
|------|--------|----------|
| **Trajectory / Move** | 单段时间序列，可本地回放，例如 Reachy `custom/*.json` | 不是上架商品，不直接作为 Skill |
| **Episode / Dataset** | 多段轨迹 + 图像 + 元数据，是训练原料 | 不是用户最终安装的能力 |
| **Model Artifact** | checkpoint、metrics、训练配置、评估结果 | 单独存在时还不是 Skill |
| **Skill** | `skill_id` + `verb` + `params_schema` + runtime/camera/model 绑定 + artifact 引用 + `version` | 不是裸 `.npy` / `.json` 轨迹 |
| **SkillListing** | 上架到 Marketplace / AI Hub 的商品条目，绑定某个 Skill 版本 | 不是普通 HF 模型搜索结果 |

产品口播：

> 时间序列是原料；Skill 是上架的包。用户装的是「会抓杯子 v1.2」，不是 500 行关节角。

对阶段路线的影响：

```text
录数据 / 动作序列（原料）
  → Workflow（工厂：训练、评估、部署、打包）
  → Skill（商品：带接口、版本、runtime 绑定）
  → AI Hub / Marketplace（商店：发现、安装、更新）
```

---

## Workflow 编辑器（`/workflow`）

### 现状（能讲故事的版本）

**已经真的通的：**

| 能力 | 说明 |
|------|------|
| 画布与执行引擎 | React Flow 拖节点、连线、拓扑排序执行、控制台日志、中止运行 |
| **Finetune 链（核心）** | `dataset_load` → `camera_map` → `finetune_job` → `job_monitor` |
| `dataset_load` | `GET /api/v1/trainings/qualia/dataset_probe`（失败时用默认 image keys） |
| `camera_map` | 纯前端校验与映射（不调 API，但逻辑真实） |
| `finetune_job` | `POST /api/v1/trainings`（Qualia）；失败会 **fallback 模拟** |
| `job_monitor` | `GET /api/v1/trainings/{id}` 轮询至终态 |
| `skill_invoke` | `POST /api/v1/skills/{id}/run` + 轮询 run 状态 |
| 持久化 | 仅 **localStorage** 存图；可导出 JSON，无服务端 workflow 库 |

**演示壳子（名字像真的，执行是 sleep + 假数据）：**

| 节点 | 现状 |
|------|------|
| `robot_connect` / `record` / `train` / `deploy` / `visualize` | M9 遗留 demo，**不调** 录制/训练/部署 API |

**未接完（面板里有，跑不起来）：**

| 节点 | 现状 |
|------|------|
| `camera_denoise` / `trajectory_optimize` | 在 `nodeTemplates` 里，**无** `nodeTypes`、**无** `workflowEngine` case、**无** 属性面板 |

**相关代码：** `apps/web/src/components/workflow/`、`lib/workflowEngine.ts`、`store/workflowStore.ts`

### 待办

| 优先级 | 项 | 工作量（估） | 说明 |
|--------|-----|--------------|------|
| **P0** | 文档与 UI 标注 demo 节点 | 小 | 面板/节点上标「演示」；避免用户以为 record/train 已接真机 |
| **P0** | `finetune_job` 失败时明确提示 | 小 | 区分「真实提交」vs「模拟 fallback」，控制台写清原因 |
| **P1** | `record` 接真录制 API | 中 | `POST /api/record/start|stop`（与 Setup Step4 / Teleop 同源） |
| **P1** | `robot_connect` 接 runtime/串口探测 | 中 | 复用 `/api/setup/health`、`/api/runtimes` 或 manifest |
| **P1** | `train` 废弃或合并进 `finetune_job` | 小 | 去掉重复概念，只保留一条训练路径 |
| **P1** | Workflow 服务端存储 | 中 | `workflows` 表 + CRUD；支持命名、版本、分享链接 |
| **P1** | `evaluate` 节点 | 中 | 输入训练产物 + 测试集 / 指标，输出是否允许发布 |
| **P1** | `publish_skill` 节点 | 中 | 从 `training_job_id` / `model_key` 生成 Skill manifest 或升级版本 |
| **P2** | `deploy` 接推理/侧车部署 | 大 | 对齐 Inference / pi0_sidecar / Skills deploy 动词 |
| **P2** | `camera_denoise` / `trajectory_optimize` | 大 | 需后端算法或 Qualia 扩展；Pro 档 gating 已有 |
| **P2** | 长任务队列 | 大 | 训练数小时场景：后端 job 队列 + WS 推送，减少前端轮询 |

### 产品叙事（对外怎么说）

- **今天能用：** 在网页上把「HF 数据集 → 相机映射 → 提交 Qualia 训练 → 看任务状态」串成一条 pipeline，适合演示 **技能开发平台** 的训练闭环。
- **还不能说：** 「拖一条线就从连机器人录数据到部署上线」——中间录/连/部署节点仍是 demo。
- **对齐纲领：** 见 `docs/strategy/roadmap-principles.md` 阶段二「技能闭环」；Workflow 是 **Skill 工厂**，先把 Finetune 链做稳，再补齐 `evaluate` / `publish_skill`。

---

## AI Hub（`/ai-hub`）

### 现状（能讲故事的版本）

**已经真的通的：**

| 能力 | 说明 |
|------|------|
| 模型列表 | `GET /api/v1/hub/models` → 后端调 HuggingFace（robotics 标签）；10s 超时则用 **FALLBACK_MODELS** |
| 模型详情 | `GET /api/v1/hub/models/{repo_id}` → HF `model_info`；可含 **readme** 字段 |
| 排行榜页 | 同一列表接口换排序；**不是**独立排行算法 |
| 数据集发布到 HF | `POST /api/v1/hub/datasets/publish`（绑定本地 `Dataset` 行） |

**壳子 / 断链：**

| 能力 | 现状 |
|------|------|
| Model Card 区域 | 详情页 **硬编码** 文案；未渲染后端返回的 `readme` |
| Like / Share | 按钮无 handler |
| Download | 前端 `POST /api/v1/hub/download` — **后端无此路由** |
| 相似模型 | 硬编码 repo id |
| Marketplace | `GET/POST /api/v1/marketplace/listings` **有 DB**，**AI Hub 页面未接** |
| 批量 batch | marketplace batch 接口为 **stub**（queued 文案） |
| 匿名访问 | 路由公开，但 hub API **要求 JWT** — 未登录可能空白/403 |

**相关代码：** `apps/web/src/pages/AIHub*.tsx`、`apps/api/.../hub.py`、`marketplace.py`、`services/hf_hub_service.py`

### 待办

| 优先级 | 项 | 工作量（估） | 说明 |
|--------|-----|--------------|------|
| **P0** | 详情页渲染 HF `readme` | 小 | Markdown 安全渲染；去掉假 Model Card |
| **P0** | Hub 鉴权策略二选一 | 小 | 要么 hub 列表匿名可读，要么 AI Hub 加 `RequireAuth` + 引导登录 |
| **P0** | 去掉或禁用 Download 直到有实现 | 小 | 或实现 `POST /hub/download`（下载 Skill 包 / checkpoint，不是裸轨迹） |
| **P1** | Like 落库 | 中 | `hub_model_likes` 表 + API；详情页接真实计数 |
| **P1** | AI Hub ↔ Marketplace 入口 | 中 | Tab 或「平台技能」区块拉 `GET /marketplace/listings`，列表项绑定 Skill 版本 |
| **P1** | 相似模型 | 中 | HF tags / 同作者 / 本地共现；替换硬编码 |
| **P2** | 技能安装一键跑 | 大 | 从 listing → Skills `run` → Local Agent / Runtime |
| **P2** | 作者页、评论、版本 | 大 | 真社区层；支付与分成（对齐 M17 订阅档位） |
| **P2** | 上传模型到 Hub | 大 | 实现 `client.uploadToHub` 对应后端（训练产物 → HF model repo → Skill manifest） |

### 产品叙事（对外怎么说）

- **今天能用：** 在平台内浏览 HuggingFace 上的机器人相关模型；把本地数据集 **publish 到 HF**。
- **还不能说：** 「机器人界的 App Store」——市场表在，UI 未接；社交与下载未通。
- **对齐纲领：** 阶段三「技能市场」；AI Hub 当前是 **HF 发现层 + 数据集出口**，Marketplace 才是 **BotverseX 自有技能货架**。上架单位必须是 Skill 包，不是裸轨迹。

---

## Reachy Mini

| 优先级 | 功能 | 工作量（估） | 回报 | 状态 |
|--------|------|--------------|------|------|
| **P0** | 轨迹录制-回放（原料层） | 中（2–3 天） | 产品体验补齐、演示亮点 | 待做 |
| **P1** | 轨迹转 Dataset / Episode | 中 | 为训练 Skill 准备原料 | 待做 |
| **P1** | Reachy Skill 打包路径 | 中 | 训练产物 → Skill manifest / version | 待做 |
| **P1** | 虚拟模式（无硬件播放动作） | 小（1–2 天） | 演示不依赖实体机 | 待做 |
| **P2** | MuJoCo 物理仿真 | 大（1–2 周+） | 当前用户场景暂不需要 | 待做 |
| ~~P0~~ | ~~USB 串口 auto~~ | — | 换口自动探测 | **已完成**（M20，`botversex-local-agent` b246080） |

### P0 — 轨迹录制-回放（原料层）

- 在 `reachy_proxy` 增加 `/api/reachy/record/start`、`/api/reachy/record/stop`
- 定时采样关节状态（如 `/api/state/full`），停止后存为 `data/reachy_mini_moves/custom/*.json`
- Web UI：Record Custom Move，录完后出现在动作列表并可播放
- 目标：手动摆 Reachy Mini → 记录轨迹 → 回放（对齐 SO-101 示教体验）
- 边界：这一步产出的是 **Trajectory / Move**，不是 Skill，不进入 Marketplace。

### P1 — 轨迹转 Dataset / Episode

- 将一段或多段 custom move 包装成可训练样本（episode metadata、fps、关节、可选图像）
- 与 LeRobot / BotClaw `DatasetEpisode` 对齐
- 目标：Reachy 的动作录制不只可回放，还能成为训练原料

### P1 — Reachy Skill 打包路径

- 输入：Reachy 数据集 + 训练产物 checkpoint + params schema
- 输出：`skill_id`、`verb`、`version`、`compatible_types`、`params_schema`、artifact 引用
- 目标：上架的是「会挥手 / 会抓杯 v1.x」这种能力包，而不是 `.json` 轨迹

### P1 — 虚拟模式

- daemon 不可用时：内存 Mock 关节 + 现有 JSON 动作播放器驱动状态
- WebSocket 推送虚拟关节值，`UrdfViewer` 随动（无需 MuJoCo）
- 目标：不连硬件也能在网页上演示预设/自定义动作

### P2 — MuJoCo 物理仿真

- URDF → MJCF、后端物理步进、前端渲染对接
- 适用：云端 sim 训练、sim-to-real；**当前新手/真机闭环阶段可延后**

---

## BotverseX Copilot（全站诊断 Agent）

| 优先级 | 项 | 状态 | 说明 |
|--------|-----|------|------|
| **P0** | 确定性诊断面板 | **已完成** | 右下角浮窗，cloud/DB/realtime/robots/camera/serial 一键检测 |
| **P0** | 问答助手（LLM chat） | **已完成** | 后端 `/api/v1/copilot/chat`，支持 Anthropic / OpenAI-compatible / DashScope |
| **P0** | 页面感知建议 | **已完成** | `/setup`、`/robots`、`/training` 各有上下文提示和建议 |
| **P0** | Playbook 知识库 v1 | **已完成** | 21 条结构化故障条目，规则匹配 + 修复步骤 + 验证方式 |
| **P1** | LLM provider 轮换 & 回退 | 待做 | 失败自动切备用；Token 余额预检 |
| **P2** | 侧车 harness 集成 | 待做 | 如果 plain provider 不够，运行 Node sidecar + 窄 JSON 协议 |

**相关代码：** `apps/api/app/api/v1/endpoints/copilot.py`、`apps/api/app/models/copilot_playbook.py`、`apps/api/app/services/copilot_playbook_service.py`、`apps/api/app/data/copilot_playbooks_seed.json`、`apps/web/src/components/copilot/CopilotWidget.tsx`、`apps/web/src/lib/copilotApi.ts`、`apps/web/src/lib/copilotDiagnostics.ts`

---

## 平台体验（横切）

| 优先级 | 项 | 状态 | 说明 |
|--------|-----|------|------|
| **P0** | URDF / runtime 加载性能 | **已做一版** | STL 长缓存、渐进加载、LazyUrdfPreview、`/api/robots` 60s 缓存；ECS 需固化 realtime 镜像 |
| **P1** | M20 改动 commit | 待做 | `f4ea95d` 已含 reachy auto + setup 四步；Compare/DatasetDetail 等大改可另 commit |
| **P1** | `botversex.achao.xin` HTTPS | 待做 | DNS-01 或 standalone；`feispace.me` 已可用 |
| **P2** | Reachy / 真机 smoke 进 acceptance gate | 待做 | 可选 job：本机 ping + hello |

---

## 相关代码索引

| 领域 | 路径 |
|------|------|
| Workflow | `apps/web/src/components/workflow/`、`lib/workflowEngine.ts`、`store/workflowStore.ts` |
| AI Hub | `apps/web/src/pages/AIHub*.tsx`、`apps/api/app/api/v1/endpoints/hub.py` |
| Marketplace | `apps/api/app/api/v1/endpoints/marketplace.py`、`models/skill_listing.py` |
| Copilot | `apps/api/.../copilot.py`、`apps/web/src/components/copilot/CopilotWidget.tsx`、`lib/copilotApi.ts`、`lib/copilotDiagnostics.ts` |
| Reachy | `apps/realtime/api/reachy_proxy.py`、`apps/web/src/pages/RobotReachyMini.tsx` |
| URDF 性能 | `apps/web/src/lib/urdf.ts`、`LazyUrdfPreview.tsx`、`apps/realtime/api/main.py`（cache 中间件） |
| 进度日记 | `progress/M19-*.md`、`progress/M20-*.md` |
| 阶段纲领 | `docs/strategy/roadmap-principles.md`、`docs/strategy/platform-manifesto.md` |
| Runtime manifest | `apps/realtime/config/robots.json`、`apps/realtime/runtimes/` |
| LeRobot Humanoid | 本文「LeRobot Humanoid（观察项）」；[lerobot-humanoid](https://github.com/Virgileboat/lerobot-humanoid) |
| DimOS / dimos | 本文「DimOS / dimos（观察项）」；[dimensionalOS/dimos](https://github.com/dimensionalOS/dimos) |

---

### B601-DM 双臂（预埋）

**Trigger：** 当 `runtimes/b601_dm/` 出现在 manifest 且声明 `bimanual` capability 时，前端自动启用双臂镜像 UI（URDF Viewer 已支持多 URDF）。

---

## Agent 使用说明

1. 开工前先读本文件，选 **P0** 且与当前会话目标一致的项。
2. 完成里程碑后：更新对应行的 **状态**，必要时在 `progress/` 新增 `MXX-*.md`。
3. 勿把本文件中的密钥、token 写入仓库；生产账号见运维文档或环境配置。
