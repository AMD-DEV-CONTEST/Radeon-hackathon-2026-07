# Agent Prompt：BotverseX 投资人 Deck 素材搜集（本机 Agent）

> **Agent 在云端沙盒？** 不要用本文件，改用：  
> **`prompt-素材搜集-agent-云端版.md`**（不依赖 `~/下载/` 路径）

---

把下面整段复制给**能访问你本机仓库**的 agent。

---

## 任务

为 **BotverseX Seed 投资人 HTML deck** 搜集、筛选、下载或生成**可用图片/GIF**，放入仓库目录：

```text
/home/amd/下载/dev/botversex/docs/presentations/assets/
```

Deck 文件：`docs/presentations/investor-seed-2026.html`  
已有素材说明：`docs/presentations/投资人-deck-素材清单.md`

**不要改 deck HTML**，只交付素材文件 + 一份 `assets/MANIFEST.md`（每张图：文件名、来源 URL、授权说明、建议用在哪一页）。

---

## 项目背景（给 agent 理解用途）

BotverseX = 具身智能 **数据闭环入口**（网页里：连真机 → 录数据 → 训练 → 部署 → 装 Skill）。  
投资人很多来自 **web3 / 非机器人背景**，deck 策略是：**先产品截图和真机图，再少量生态/场景图衬托市场大**。

**已有（不要重复找）：**

- `so101-hardware.jpeg`, `botversex-so101.png`
- `reachymini实体图.jpg`, `botversex-reachymini.png`
- `botversex-dataset.png`, `botversex-training.png`, `botversex-workflow.png`, `botversex-skill.png`, `botversex-models.png`, `botversex-aihub.png`, `botversex-localagent.png`, `so101-setup.png`
- `botversex-pricing.png`（订阅三档截图）

本地可能还有大 GIF：`~/下载/PPT素材/遥操作演示视频.gif`、`reachymini演示视频.gif`（可裁短复制到 assets）。

---

## 搜集优先级

### P0（必须尝试完成）

| 目标文件名 | 内容 | 规格 |
|------------|------|------|
| `teleop-demo.gif` 或 `.mp4` | SO-101 Leader/Follower 遥操作实拍，手晃臂跟随 | 1280×720 横屏，15–30 秒，&lt;15MB；优先用项目已有 GIF 裁切 |
| `team-ethan.jpg` | CEO 杨智超半身照 | 若仓库没有，在任务报告里写「需创始人提供」 |
| `team-liuqi.jpg` | CTO 刘琦半身照 | 同上 |
| `pipeline-6steps.png` | 一张图：连接→遥操作→录数据→训练→部署→技能，六格+箭头 | 1920×1080；可用已有 assets 小图拼贴合成 |

### P1（尽量完成）

| 目标文件名 | 内容 | 规格 |
|------------|------|------|
| `ecosystem-runtimes.png` | **一页拼贴**：左大右小或横排三格——机械臂 / 人形 / 四足；**必须标注为生态示意，非全部已接入** | 1920×1080，深色底 #0a0e14，橙色 #f59e0b 点缀 |
| `unitree-go2-reference.jpg` | Unitree Go2 **官方 press / 官网图**（机器狗） | 注明来源；仅用于「Runtime 预研 / Building」 |
| `reachy-demo-short.gif` | Reachy Mini 演示（可裁短） | &lt;15MB |
| `aihub-models-collage.png` | AI Hub + Models 两屏拼一张 | 从 `~/下载/PPT素材/` 或线上产品截屏 |
| `before-after-ros-vs-botversex.png` | 左：ROS/脚本碎片示意；右：BotverseX 一个网站（可用截图） | 信息图，勿捏造客户 |

### P2（可选）

| 目标文件名 | 内容 |
|------------|------|
| `scene-factory.jpg` / `scene-lab.jpg` | 工厂、实验室 **氛围图**（无人声称是客户现场） |
| `marketplace-mockup.png` | Skill 商店线框/mockup，角标 **Building** |
| `architecture-export.png` | 从 deck 架构 SVG 导出 2x PNG（若 agent 能跑 headless 截图） |

---

## 网图 / 搜图规则（严格执行）

1. **优先顺序：** 项目自有实拍 &gt; 厂商官方 press kit &gt; 开源硬件文档图（LeRobot/SO-101）&gt; 明确可商用的图库。
2. **禁止：** 随机下载无授权网图；带其他公司 Logo 却声称是 BotverseX 客户；整页高清网图却没有产品 UI。
3. **每张外链图必须在 MANIFEST 写清：** 来源 URL、授权类型（CC0 / 官方 press / 需购买等）、是否可商用。
4. **推荐搜图关键词（英文）：**
   - `Unitree Go2 official press kit`
   - `lerobot SO-101 follower arm`
   - `Reachy mini robot pollens`
   - `robot arm teleoperation leader follower`
   - `quadruped robot warehouse`（仅氛围，标注示例场景）
   - `robotics lab desktop manipulation`
5. **中文关键词：** `四足机器人 官方`、`机械臂 遥操作`、`人形机器人 教育`、`机器人 实验室 场景`
6. **Unitree / 华为 / HF 等：** 只用**官方或新闻稿配图**，不要偷私人博客水印图。

---

## 视觉规范（与 deck 一致）

- 背景深色 `#0a0e14`，强调色橙 `#f59e0b`，文字浅 `#e8edf4`
- 拼贴类：圆角 8px，细边框，不要花哨 3D
- 导出 **PNG**（照片/JPG 也可），GIF 控制体积
- 文件名：**小写英文+连字符**，如上表，不要中文文件名

---

## 交付物

1. 所有文件放入 `docs/presentations/assets/`
2. 新建 `docs/presentations/assets/MANIFEST.md`，表格列：

   | 文件名 | 用途（deck 哪一页） | 来源 | 授权 | 状态 |

3. 简短报告（≤15 条 bullet）：
   - 完成了哪些 P0/P1
   - 哪些找不到、需要创始人拍/截屏
   - 不建议用的图及原因

4. **不要**提交无法验证授权的图；宁可少交也不要侵权风险。

---

## 禁止 agent 做的事

- 不要修改 `investor-seed-2026.html`（除非用户另说「接到 deck」）
- 不要编造「已合作 Unitree / 某大厂」类图片说明
- 不要用 AI 生成「假真机演示」冒充实拍（投资人尽调会穿帮）
- 不要下载需要登录付费且无授权的 Getty/Shutterstock 预览图

---

## 完成后用户会做的事

用户把 MANIFEST 发给另一个 agent，把新图 `src` 接到 `investor-seed-2026.html`。

---

*End of prompt*
