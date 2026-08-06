# BotverseX 投资人 FAQ（Seed · $5M）

与 deck 配套：`docs/presentations/investor-seed-2026.html` · 口播 `docs/presentations/口播稿-Investor-Seed-2026.md`  
反对派备忘：`investor-red-team-memo.md`

**Deck 分工：** 首聊 `investor-seed-teaser-2026.html`（15 页）· 尽调 `investor-seed-2026.html`（44 页，正文进攻叙事）· 估值/Cap/「我们不是什么」见本 FAQ 与 `investor-red-team-memo.md`

---

## 一句话（Seed 轮对外）

**BotverseX 是 LeRobot 生态上的真机模仿学习 MLOps 平台**——降低从「连上机器人 → 录数据 → 云/本地训练 → 部署回真机」的端到端摩擦；不是卖铁，不是第三个 Hugging Face，**2026 年主故事也不是跨本体 Skill 商店**。

更长版：

> 具身智能的数据闭环入口 · 先做成开发者愿意付费的生产工具，再谈分发网络。

---

## 我们到底是什么？（剥离宏大叙事）

| 维度 | 结论 |
|------|------|
| 本质 | **易用性 SaaS + 云 Finetune**：Web + Local Agent + Runtime Adapter |
| 用户（近期） | 高校 lab、个人开发者、SO-101/Reachy 早期用户 |
| 用户（远期） | 场景方、企业数据管线（18mo+ 窄试点） |
| 不是什么 | 数据源工厂、基础模型厂、整机 OS、已成熟的产业级 App Store |

**不是 dimos 那种整机 Robot OS。** 我们是 **平台层**：消费 LeRobot 格式，在之上做真机闭环与 Skill 封装（BotClaw 为 **扩展 schema**，不替代 LeRobot Dataset）。

---

## 产业链：零部件、本体、模型、数据、场景 — 你们做哪一段？

| 环节 | 典型玩家 | BotverseX |
|------|----------|-----------|
| 零部件 | 电机、传感器、减速器 | **不做** |
| 本体 | 机械臂、人形、四足 OEM | **不造机** · Runtime 接入 |
| 模型 | HF、基础模型厂、VLA 实验室 | **消费** · 不赌最大模型 |
| 数据 | 场景 episode、失败案例 | **主战场（工具让 USER 生产数据）** |
| 应用场景 | 工厂、lab、教育、桌面 | **入口与回流** |

一句话：**占「数据生产工具 + 闭环」，远期才占「Skill 分发网络」。**

---

## 团队（deck 已写入）

**CEO 杨智超（@ethanyeang）：** 暨南大学商科 · 个人开发者 · 过往企业端 AI 智能化转型业务 **半年营收约 ¥300 万**（非 BotverseX 当前收入）· 生态沟通（HF、DimOS、AWS、AMD 等）。

**CTO 刘琦：** 港中文硕士 · **VLA** · 参与华为、Hugging Face 等相关项目 · Training / Workflow / Runtime / Skill 技术栈。

叙事要点：**CEO 有 B 端 AI 商业化和交付经验，CTO 有 VLA 与大厂/开源生态项目经验；二者互补。**

---

## 和 Hugging Face / LeRobot 什么关系？

| | HF / LeRobot | BotverseX |
|--|--------------|-----------|
| 核心 | 模型、数据集、开源硬件生态 | **真机 Web 闭环 + Workflow** |
| 关系 | **协作大于竞争** | **The best GUI & cloud layer for LeRobot** |
| 风险 | 官方若做录→训→部署 Console | 我们变插件 → 对策：习惯、托管、云训、联合 GTM |

不要说「我们是硬件版 HF」；要说 **「站在 LeRobot 之上，把真机 IL 流水线做到像 W&B + 管道一样省事」**。

---

## 跨本体 / Skill 商店：反对派会问什么？

见 `cross-embodiment-narrative.md` 与 `investor-red-team-memo.md`。

**简短版：**

- **换机税**（真痛点）：换机器人常要重搭格式、脚本、部署环境——我们用 **统一网站 + Runtime** 降 **工程税**。  
- **不承诺**：SO-101 轨迹字节级给 Reachy/宇树直接 90% 成功。  
- **Skill 商店**：12–18 月仅为 **beta/期权**；跨本体「像装 App」在 2026 不成立主收入模型。  
- **同机型**：「会抓杯子 v1.2」+ `compatible_types` + 版本更新——这是近期可验证的 Skill 形态。

---

## 竞争格局（简）

| 玩家 | 威胁类型 | 我们差异 |
|------|----------|----------|
| **LeRobot / HF** | 生态吞掉入口 | 真机产品化、云训、Workflow 习惯 |
| **Foxglove** | 观测/数据平台 | IL 闭环、非 ROS 前置、录→训→部署 |
| **Mecka / Scale** | 卖标准化数据 | 我们卖 **让用户自产数据** 的工具 |
| **OpenMind / UNISTORE** | 本体厂 Skill 店 | 不做硬件联盟 OS；中立 SaaS |
| **NVIDIA Isaac** | 仿真数据 | 真机 episode 回灌；互补 |
| **π / VLA** | 通用大脑 | 长期压制万能小 Skill；不压制数据工具 |

---

## 为什么是现在？

1. 低成本臂（SO-101）让 **wedge 可验证**  
2. LeRobot 成事实标准，但 **非资深工程师仍难跑通真机闭环**  
3. lab 缺 GPU → **云 Finetune** 有即时付费理由  
4. 订阅与训练基础设施已在产品里（`plans.yaml`、registry）

---

## 商业模式怎么赚钱？（优先级）

| 收入线 | 说明 | Seed 阶段权重 |
|--------|------|----------------|
| **云训练用量** | Qualia / GPU 按量；省去买卡与环境 | **P0 · 最真 PMF** |
| **SaaS** | 存储、团队、Workflow 节点、训练额度 | **P1** |
| **教育/团队档** | 个人 Creator；学术策略见下 | **P1** |
| **企业** | 窄：数据合规采集管线；非全国私有部署大包 | **P2 · 18mo+** |
| **Marketplace** | Skill 抽成 15–30% | **期权 · 非主估值** |
| **伙伴** | Runtime 联合 GTM | 随 Runtime 扩展 |

**学术用户：** 倾向 **免费/极低门槛** 换装机与数据集习惯（对标 Foxglove 教育策略），收入从 **云训与团队档** 收，不靠学生订阅 ¥68 为主。

**ARR 保守路径（需随 PMF 调整）：**

| 年份 | ARR | 驱动（修订后） |
|------|-----|----------------|
| Y1 | $0.3–0.8M | 云训练 GMV + Pro/Creator + 试点 |
| Y2 | $2–4M | 云训规模化 + lab 套餐 + **非**商店主驱动 |
| Y3 | $8–15M | 企业管线 + 商店若验证 + 多 Runtime |

---

## 这轮融多少？估值与稀释？

| 项 | 建议对话区间 |
|----|----------------|
| 融资额 | **$5M USD** Seed |
| Pre-money | **$22M – $28M**（真机闭环已验证；**非**商店已验证） |
| 本轮稀释 | **约 15–18%** |
| 期权池 | Post 新设 **10–12%** |
| Runway | **18–24 个月** |

**估值逻辑应绑定：** 云 Finetune 付费、Workflow 复用、双 Runtime 深度——**不是** Marketplace GMV。

### Cap table（当前口径）

- **首轮机构 Seed** · **无 prior SAFE / 无历史机构股**（以律师尽调为准）  
- **融资后示意：** 创始人 ~52–55% · CTO ~20–22% · ESOP 10–12% · Seed 15–18%

---

## $5M 怎么花？（与 deck 一致）

| 用途 | 占比 | 约 |
|------|------|-----|
| 产品与工程 | 42% | $2.1M |
| Runtime / 真机 / SDK | 18% | $0.9M |
| GTM / 社区 / 试点 | 22% | $1.1M |
| 云与基础设施 | 12% | $0.6M |
| 法务 / 安全 / 运营 | 6% | $0.3M |

**18 个月要买到的结果（Seed KPI）：**

1. Dataset → Train → Deploy **稳定可付费**（云训为核心）  
2. SO-101 / Reachy **做深**，Workflow 模板可复用  
3. **10+ lab/企业 POC**（带复购或 LOI）  
4. Marketplace **beta only**，不押注抽成收入  

---

## Venture-scale 机会（诚实版）

- **Category upside：** 真机 MLOps 入口 → 云训练 → 企业数据管线 → **若**跨机型成功率成熟，再加 Marketplace。  
- **Strategic value：** OEM / 云 / 模型厂需要开发者装机与真实 episode，不一定自己做 GUI。  
- **A 轮里程碑：** 可复制 MRR、云训毛利、第二 Runtime 标准、**非**「上架 1000 个跨本体 Skill」。

---

## 护城河（近期可辩护）

1. **Workflow + 数据集账户内沉淀**（切换成本）  
2. **LeRobot 格式 + 真机闭环一体化**（省时间）  
3. **双 Runtime 已验证的接入标准**（`robots.json`）  
4. **分发网络效应**——**远期**，不作 Seed 主护城河论述  

---

## 主要风险（主动披露）

见 `investor-red-team-memo.md`。摘要：

- 跨硬件 Skill 需 Runtime / 微调，**不能过度承诺**  
- **HF/LeRobot 官方产品化** 吞掉入口  
- Foxglove / 云厂商下沉  
- Marketplace **过早** 叙事导致信誉风险  
- 企业私有部署 **项目制泥潭**  
- VLA 长期改变「安装小 Skill」必要性——近端仍要数据工具  

---

## 尽调材料清单

- [ ] 真机 demo 录像（SO-101、Reachy）  
- [ ] Deck · `docs/presentations/assets/`  
- [ ] `docs/strategy/investor-red-team-memo.md`  
- [ ] `docs/roadmap.md` · `docs/architecture.md`  
- [ ] `apps/realtime/config/robots.json`  
- [ ] `packages/botclaw-spec` · `apps/api/app/data/plans.yaml`  
- [ ] 律师：**无 SAFE / 股权结构**  
- [ ] 企业 AI 项目回款摘要（¥300 万口径，脱敏）  
- [ ] 3 个 lab/企业 LOI（若有）
