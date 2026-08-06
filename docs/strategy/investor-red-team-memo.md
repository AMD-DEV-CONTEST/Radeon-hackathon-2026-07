# BotverseX · 反对派备忘录（Red Team）

> 供 **Data Room / 二轮 DD 口头问答** — **不进 Deck 正文**（勿在路演末尾替投资人念风险清单）。  
> 配套：`investor-faq.md` · `investor-seed-2026.html`（结尾仅一句「见 Data Room」）· `cross-embodiment-narrative.md`

---

## 一句话（给投资人先读）

**Seed 轮买的是：LeRobot 真机模仿学习 MLOps + 云 Finetune 的付费验证。**  
**不是买：跨本体 Skill 商店、通用机器人大脑、或已产业化的工厂平台。**

---

## 内部对齐 · Seed 轮买什么（不进 Deck 正文）

> 原 Deck「真实定位」三栏（是什么 / 不是什么 / 远期上行）仅用于团队与 data room，首聊与 Deep Dive 正文用进攻叙事即可。

| 栏 | 要点 |
|----|------|
| **是什么** | 真机 MLOps · Web + Local Agent + Runtime · 云 Finetune · Workflow · LeRobot |
| **不是什么** | 数据工厂 · 基础模型厂 · 2026 主叙事≠跨本体 App Store |
| **远期上行** | Skill 版本化 · Marketplace Building · 多 Runtime · 伙伴 GTM |

跨本体诚实边界见 `cross-embodiment-narrative.md`。

---

## 剥离外衣：我们到底是什么？

| | |
|--|--|
| **是** | 面向开源臂 / 教育 lab 的 **真机 IL MLOps SaaS**（Web + Local Agent + Runtime） |
| **是** | **LeRobot 生态的最佳 GUI/云副驾驶**（格式兼容，不替代 lerobot 训练库） |
| **不是** | 数据源工厂（≠ Mecka / Scale 的 DaaS） |
| **不是** | 基础模型公司（≠ Physical Intelligence / 自训 VLA） |
| **不是** | 整机 Robot OS（≠ dimos / OpenMind OM1） |
| **不是（2026–2028 主收入）** | 已规模化的 **跨本体 App Store**（≠ Unitree UNISTORE 赛道） |

---

## 反对派最常问的 6 个问题 · 标准答法

### Q1：SO-101 的数据能直接给 Reachy / 宇树用吗？

**答：** 不能承诺「字节级混训、安装即用」。我们解决的是 **换机税里的工程部分**：同一网站、同一 Workflow、LeRobot 格式、换 Runtime 不重搭 pipeline。跨机型策略迁移靠 `compatible_types`、微调或未来 VLA，**不吹万能**。

### Q2：和 Hugging Face LeRobot 什么关系？会不会被 Hub 吞掉？

**答：** **协作大于竞争**。LeRobot 是格式与工具链标准；我们是 **真机闭环产品层**。最大风险是 HF 官方做录→训→部署 Console——对策：深度兼容、联合 GTM、贡献上游、占住开发者 Workflow 习惯。**不另立与 LeRobot 冲突的数据标准。**

### Q3：Foxglove 已经 $40M，你们还有什么空间？

**答：** Foxglove 强在 **ROS/工业观测与 telemetry**；我们强在 **非 ROS、模仿学习、录→训→部署闭环**。用户可并存。我们不对标 Anduril 级私有部署，先吃 **教育 / lab / 创作者**。

### Q4：Skill Marketplace 12–18 个月能赚钱吗？

**答：** **不能作为主估值假设。** 2026 年跨本体「装 App」成功率不足以支撑抽成规模化。Marketplace 是 **产品期权**（API/DB 已有，前端 Building）。近端收入：**云训练用量 > 存储/团队 SaaS > 企业试点**。

### Q5：$5M 够做「跨本体 + 商店 + 企业」吗？

**答：** **不够同时做全叙事。** $5M 买 18–24 个月：**SO-101/Reachy 做深、Workflow 可执行、云 Finetune PMF、第二 Runtime 标准、10 个 lab/企业 POC**。商店与多 Runtime 规模化是 **A 轮故事**，前提是 Seed KPI 达成。

### Q6：Pre-money $22–28M 凭什么？

**答：** 凭 **真机已跑通 + 双 Runtime + 订阅与云训练已进产品 + 团队 B 端交付记录**，不是凭「已是机器人 App Store」。若投资人主定价在商店叙事，**不应按本平台估值**。

---

## 竞争阵营（简表）

| 阵营 | 代表 | 与我们的关系 |
|------|------|----------------|
| 开源生态 | HF LeRobot | 共生；最怕官方闭环产品化 |
| 数据工厂 | Mecka, Scale | 不同赛道（他们卖数据，我们卖工具） |
| 本体商店 | Unitree UNISTORE, OpenMind | 硬件/OS 联盟游戏；我们不做主叙事 |
| 观测平台 | Foxglove | 部分重叠；阶段与 buyer 不同 |
| 仿真 | NVIDIA Isaac | 补数据方式不同；真机 episode 仍要入口 |
| 基础模型 | π 等 VLA | 长期压制「小 Skill 万能」；不压制「数据生产工具」 |

---

## Seed 轮北极星 KPI（建议写进 term sheet 对话）

| 优先级 | 指标 | 说明 |
|--------|------|------|
| P0 | 月活 **云 Finetune 付费任务数** | 最直接 PMF |
| P0 | **Workflow 模板复用率**（第 2 台 Runtime 用户） | 验证「换机不重搭」 |
| P1 | Pro/Creator **付费账户数**、MRR | SaaS 验证 |
| P1 | 标杆 **实验室/企业 POC** 数量（带 LOI 更好） | B 端路径探测 |
| P2 | Marketplace 上架 Skill 数 | **不作为 Seed 主 KPI** |

---

## 收入叙事顺序（对外统一）

1. **Now → 12mo：** 云 GPU 训练 + 存储/团队档 + 教育 lab 渗透（学术版策略见 FAQ）  
2. **12–18mo：** 企业 **窄** 试点（数据合规采集管线），非全国私有部署  
3. **18mo+：** Marketplace **beta**；是否规模化看跨机型成功率与第三方供给  

---

## 主动披露的 5 条风险

1. **跨硬件**：Skill 需 Runtime / 微调；不能过度承诺「写一次跑遍所有机器人」。  
2. **生态依赖**：LeRobot/HF 路线变化；策略为对齐与副驾驶定位。  
3. **大厂下沉**：云厂商一键训练、HF 官方 Console。  
4. **付费敏感**：纯脚本用户不付费；需云训与 workflow 粘性。  
5. **企业定制泥潭**：私有部署易变项目制；Seed 阶段控制交付范围。

---

## 修订后的投资结论（可自行放进 memo 末尾）

- **若按「具身智能时代的真机 MLOps + LeRobot 副驾驶」定价** → 产品稀缺、落地快，Seed 区间可讨论。  
- **若按「跨本体 Skill 商店 / 机器人 App Store」定价** → 应保持高度警惕，要求证据而非叙事。  
- **建议**：本轮 term sheet 对话绑定 **P0 KPI**，Marketplace 仅作 **optionality** 披露。
