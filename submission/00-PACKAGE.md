# omima 参赛提交包（完全体索引）

> **赛事**：2026 AMD AI DevMaster 黑客松 · 赛道 **Track 2**（Development & Local Deployment of Private AI Agents）
> ⚠️ 官方规则：全部提交材料英文；PR 标题 `Track 2, kon, omima`
> **作品**：omima — Astral Metro Domain  
> **参赛者**：kon（Luma 注册名；未填 Team name）  
> **提交**：PR → `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`  
> **截止**：2026-08-06 23:59（北京时间）  
> **本包角色**：评委与提交用的**定稿目录**；planning/ 为施工与历史，不以 planning 替代本包。

---

## 一、提交物清单（齐套）

| # | 文件 | 用途 | 状态 |
|---|------|------|------|
| 0 | [`core-thesis.md`](./core-thesis.md) | **核心思想收敛**：六大类需求 → 三要素 → 效率工程 | 定稿 |
| 1 | [`README.en.md`](./README.en.md) | GitHub PR 主 README（全英文，赛制要求） | 定稿 |
| 2 | [`main-paper.en.md`](./main-paper.en.md) | 主论文英文版（**官方要求全英文，PR 主文档**） | 定稿 |
| 2b | [`main-paper.md`](./main-paper.md) | 主论文中文原版（对照） | 定稿 |
| 3 | [`amd-rocm-technical.md`](./amd-rocm-technical.md) | **AMD GPU / ROCm 40 分技术专章**（模式 + 主链证据） | 定稿 |
| 4 | [`pitch-deck.md`](./pitch-deck.md) | 答辩 PPT 大纲（10 页 / 5–8 分钟） | 定稿 |
| 5 | [`demo-script.md`](./demo-script.md) | VOX 叙事脚本（配合） | 定稿 |
| 5b | [`demo-storyboard-vox.md`](./demo-storyboard-vox.md) | **VOX 分镜主表（制作依据）** | 定稿 |
| 5c | [`storyboard-board.html`](./storyboard-board.html) | 分镜板可视化（浏览器打开/打印） | 定稿 |
| 6 | [`PR-DESCRIPTION.md`](./PR-DESCRIPTION.md) | PR 标题与正文模板 | 定稿 |
| 7 | [`evidence/INDEX.md`](./evidence/INDEX.md) | 证据索引（日志 / 魔搭 / 指标口径） | 定稿 |
| 8 | 客户端安装包（**DEMO 版**） | `omima客户端/`（Xagent.exe、omima-phone.apk）——演示构建，非成熟可发布工程版 | 见仓库根目录点检 |
| 9 | Demo Video | **VOX 动画**（按 `demo-storyboard-vox.md`，3–5 min/90s） | **已交付 · 2026-08-05** |

---

## 二、评分映射（评委扫读）

| 赛制关注 | 读哪里 |
|----------|--------|
| 作品是什么 / 应用价值 | `README.en.md` + `main-paper.md` §1–3、§4 |
| **本地推理 ~20** | `amd-rocm-technical.md`（编制 + MI300X 主链）+ evidence |
| **推理速度优化 ~10** | `amd-rocm-technical.md` 试验记录（FP8 +65% 等） |
| **AMD 生态工具链 ~10** | 同上 · ROCm / vLLM / peft / llama.cpp / ModelScope |
| 演示怎么讲 | `demo-script.md` + `pitch-deck.md` |
| 可复核资产 | `evidence/INDEX.md` |

**叙事主轴（全包统一 · 见 `core-thesis.md`）**：

> 六大类应用需求推演实现算法。  
> 收敛为三大要素：系统化协议与算法 · 内化大模型设置 · 内化工作方法（创意→论证→规划→执行→审查，多 Agent 串流并行）。  
> 效率工程含 Harness · Loop · 硬件全面考量。终点：用户高满意度交付。  
> AMD/ROCm 数字是模型内化与硬件切面的可复核切片。演示主形态为 **VOX 动画**（按 `demo-storyboard-vox.md`）。

---

## 三、数字口径（全包唯一真源）

| 指标 | 值 | 条件 |
|------|-----|------|
| 35B-A3B BF16 | ~118 TPS | vLLM ROCm，C=3 聚合 |
| 35B-A3B FP8 | ~195 TPS | 同上；相对 BF16 **+65%**；tool-call 8/9 |
| omima-35B LoRA 服务 | ~59–65 TPS（短） | Ornith-1.0-35B + adapter @ MI300X |
| omima-35B 训练 | Loss ~1.88→0.96；~1h11m | MI300X |
| omima-9B 训练 | Loss ~1.82→0.79；~57min | MI300X |
| omima-9B CPU | ~13 t/s | GGUF Q8，tool-call 通过 |
| 置信度阈值 | ~0.72 | 协议样本标定 |
| 成本账 | 56.3 亿 tokens / ¥444.55 | 缓存命中真实账（应用层，非 GPU 分） |

**产品落位（模式预期，本赛未逐台消费级实测）**：9B → Ryzen AI 笔记本；35B → MAX 395+/400 类统一内存主机；训练与主链验证 → MI300X。

**数据**：首轮岗位 LoRA 为数百条级高质量样本已训通；万级分片在魔搭数据集侧就绪，不作「已全量训进 35B」表述。

---

## 四、与仓库其它目录的关系

| 路径 | 角色 |
|------|------|
| `DOCS/submission/` | **提交定稿（本包）** |
| `DOCS/planning/` | 施工、决策、历史应答；`amd-40pts-response.md` 与 submission 专章同步，以 submission 为准 |
| `DOCS/references/` | 试验日志、技术方案原文、训练数据副本 |
| `DOCS/brand/` | 品牌与信息图素材 |
| Gitea `omima-hackathon` / `AMD-hackthon` | 远端镜像；提交前 push 对齐 |

---

## 五、提交动作（执行清单）

1. 英文 README 使用 `README.en.md` 内容放入 PR 仓库根或赛制指定路径  
2. PR 标题与正文使用 `PR-DESCRIPTION.md`  
3. 附上或链接：main-paper、amd-rocm-technical、evidence、客户端说明  
4. **Demo Video**：VOX 动画已交付（`evidence/media/omima-vox-90s.mp4`，2026-08-05）  
5. 数字若有新实测，**先改本文件第三节**，再同步 main-paper / pitch / README.en / evidence  

---

*包索引维护：omima 项目组 · 与 amd-rocm-technical 同叙事*
