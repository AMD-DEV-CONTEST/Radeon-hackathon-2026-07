# 投资人 Deck · 建议补充素材清单

给设计/同事拍屏、录屏用。已有素材在 `docs/presentations/assets/`。

**原则：** 投资人（尤其非机器人背景）——**先图后字**；每张图 3 秒内能看懂「这是什么」。

---

## 已接入 deck

| 文件 | 页面 |
|------|------|
| `botversex-pricing.png` | 订阅套餐 |
| `pipeline-6steps.png` | 六步闭环（云端） |
| `before-after-platform.png` | 今天 vs BotverseX（云端） |
| `ecosystem-runtimes.png` + 真机三格 | Runtime 生态（云端+本机） |
| `scene-factory.webp` / `scene-lab.webp` | 真实场景（云端 CC0） |
| `marketplace-mockup.png` | Skill Marketplace Building（云端） |
| `unitree-go2-reference.jpg` | Runtime 页 Unitree 格（云端） |

---

## P0 · 强烈建议补（性价比最高）

| # | 素材 | 用途 | 规格建议 |
|---|------|------|----------|
| 1 | **遥操作 15–30 秒 GIF/MP4** | 封面后：手晃 Leader、Follower 跟动 | 横屏 1280×720，&lt;15MB；源：`~/下载/PPT素材/遥操作演示视频.gif` 裁短 |
| 2 | **六步流水线合成图** | 一页讲完 Connect→Skill | 1920×1080 PNG |
| 3 | **创始人 + CTO 照片** | 团队页 | 半身照统一风格 |
| 4 | **架构图导出 PNG** | 尽调 PDF | 高清导出 |

---

## P1 · 有则加分

| # | 素材 | 用途 |
|---|------|------|
| 6 | Reachy 演示 GIF（可裁短） | 证明第二 Runtime |
| 7 | ~~定价页截图~~ | ✅ 已有 `botversex-pricing.png` |
| 8 | **AI Hub + Models 拼图** | 一页「接 Hugging Face 生态」 |
| 9 | 客户/试点 Logo 条（哪怕 2–3 个） | GTM 可信度；无则写「实验室试点中」 |
| 10 | **Before / After** 对比图 | 左：ROS/脚本碎片；右：BotverseX 一个网站 |

---

## P2 · 尽调包用（不必全进主 deck）

| # | 素材 |
|---|------|
| 11 | 数据室目录页（列：产品、架构、财务、法律） |
| 12 | 里程碑时间轴（Q1–Q6 产品+收入） |
| 13 | 竞品 2×2 矩阵图（HF / dimos / ROS / 我们） |
| 14 | Marketplace 线框/mockup（标明 Building） |

---

## 已有、可直接用

- `so101-hardware.jpeg` / `botversex-so101.png`
- `reachymini实体图.jpg` / `botversex-reachymini.png`
- `botversex-dataset.png` / `training` / `workflow` / `skill` / `models` / `aihub` / `localagent` / `so101-setup.png`

---

## 交给设计同事时的 brief（可复制）

> 风格：深色底 + 橙色强调（与 `investor-seed-2026.html` 一致）。  
> 收尾页极简：标题 + **botversex.feispace.me** + $5M + 邮箱/微信；详细三步口播即可。  
> 资金页：上为 $5M 五条横向比例条，下为四个「结果」卡片（产品、Runtime、市场、基础设施）。

---

## 文件落地路径

新图统一放到：

```text
docs/presentations/assets/
  teleop-demo.gif          # P0
  pipeline-6steps.png      # P0
  team-ethan.jpg           # P0
  team-liuqi.jpg           # P0
  pricing-tiers.png        # P1
  ...
```

放进后说一声，可把 deck HTML 里的对应 `src` 接上。

---

## 网图 / 机器狗 / 人形图 — 要不要加？

**可以加，但要少而准。** 投资人最怕「全是网图、没有自己的产品」。

### 适合用网图 / 官方宣传图的场景（1–2 页足够）

| 场景 | 建议 | 注意 |
|------|------|------|
| **市场很大** | 一页底部：机械臂 + 人形 + 四足 **小图拼贴** | 标注「生态在扩容」，不要暗示全是你们客户 |
| **Runtime 路线图** | Unitree Go2、教育人形 **官方图** | 写「预研 / 伙伴机型」，写清 **Building** |
| **场景应用** | 工厂、实验室、桌面任务 **氛围图** | 用「应用场景示例」，不要写「已部署某厂」 |

### 不建议

- 整页高清网图当主视觉，却没有你们 UI/真机 —— 像 PPT 模板。
- 随机机器狗大图 + 声称「已支持量产 Unitree」。
- 带别人 Logo 的图不注明来源（尽调会问版权）。

### 比网图更值得优先的「真图」

1. 你们 **SO-101 / Reachy 实拍**（已有）  
2. **遥操作 GIF**（一条顶十张网图）  
3. **定价页**（刚补）  
4. **团队正脸照**  
5. 若有：**实验室/客户现场** 1 张（哪怕模糊，也比网图可信）

### 若同事要搜网图

关键词示例（注意版权 / 商用授权）：

- `SO-101 lerobot arm`（开源硬件，可配合 LeRobot 官网图）  
- `Unitree Go2 robot official`（优先官网 press kit）  
- `desktop manipulation robot lab`（场景氛围）  
- `humanoid robot education`（教育场景）

**一页模板「生态扩容」** 可做成：左 60% 你们平台截图，右 40% 三张小网图（臂/狗/人形）+ 字 **「同一平台 · 更多 Runtime」**。
