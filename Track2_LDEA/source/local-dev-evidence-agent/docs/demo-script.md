# LDEA 演示视频脚本（3–5 分钟）

> 配套：`docs/项目规格说明书.md`  
> 用法：先完整预演 2 遍，再按「镜头」分段录，最后剪辑。  
> 口播可中英，但关键字保留：**verified / abandoned / 本地 / ROCm / 门禁**。

---

## 0. 录制前 15 分钟清单

### 环境

- [ ] GPU 机 vLLM 已加载，日志无报错  
- [ ] `ssh -L 8000:127.0.0.1:8000` 已连  
- [ ] `LDEA_LLM_BASE_URL` / `LDEA_LLM_MODEL` 已设且与 served name 一致  
- [ ] 开发机：`npm run build` 成功  
- [ ] `node dist/cli.js doctor` → `LLM: OK`  

### 画面

- [ ] 终端字号加大（建议 16–20pt），对比度高  
- [ ] 工作目录路径不要暴露无关隐私  
- [ ] 可选：准备干净展示用 root，例如临时 `$env:LDEA_ROOT=".ldea-demo-show"`，避免 ls 太脏  
- [ ] 分屏方案（推荐）：左 CLI · 右 vLLM 日志或 `rocm-smi` 静态窗  

### 备用

- [ ] 离线 `demo` 一定可录（无 GPU 也能保底）  
- [ ] 若 live 不稳定：主片用 A/B 对照，live 只留 20–40s 成功片段  

### 建议文件名

`LDEA-Demo-AMD-ROCm-4min.mp4`

---

## 1. 总时长与节奏（默认 ~4:00）

| 段 | 时间 | 标题 | 是否依赖 GPU |
|----|------|------|----------------|
| 1 | 0:00–0:25 | 开场立场 | 否 |
| 2 | 0:25–0:55 | Radeon + vLLM | **是** |
| 3 | 0:55–1:15 | doctor | **是** |
| 4 | 1:15–2:40 | **四故事 suite 矩阵（高潮）** | 否 |
| 5 | 2:40–3:30 | live 含糊目标 | **是** |
| 6 | 3:30–3:50 | ls / show 多会话 | 否 |
| 7 | 3:50–4:10 | 架构 + ROCm 收束 | 否 |

可压到 3:00：删减段 5 至 20s 或改为静态 tool-trace 截图；段 4 可改 `demo` 双故事。  
可拉到 5:00：段 4 四份报告各停 5s + 段 5 完整工具链。

---

## 2. 分镜与口播

### 段 1 · 开场（0:00–0:25）

**画面**

- 黑场或标题卡：  
  `Local Dev Evidence Agent`  
  `拒绝未验证的完成叙事`  
- 可叠一行：AMD DevMaster · 赛道二 · 本地私有智能体  

**口播**

> 在 AI 辅助开发里，「做完了」变得很廉价。  
> Local Dev Evidence Agent——LDEA——是一个跑在本地的开发证据智能体。  
> 它不复述聊天，只回答一件事：到底做成了什么。  
> 硬规则是：只有状态 verified 才能写已完成；大模型不能自己给自己验真。

**剪辑**

- 字幕高亮：`verified` · `不能自证`

---

### 段 2 · GPU / ROCm / vLLM（0:25–0:55）

**画面**

- GPU 机终端：  
  - `rocm-smi`（或等价）滚动/定格 GPU 名  
  - vLLM 启动命令与加载完成日志  
- 明确出现：`127.0.0.1:8000`、模型名、ROCm/vLLM 版本（可事先 `echo` 版本）

**命令（示例，按实机改）**

```bash
rocm-smi
# 已在跑可只展示日志尾部
vllm serve ...   # 或 tail 启动日志
```

**口播**

> 推理全部在本机 AMD Radeon 上，通过 ROCm 版 vLLM 提供 OpenAI 兼容接口，只监听本地端口。  
> 代码和证据账本留在开发机，不经过公有云大模型 API。

**剪辑**

- 用箭头/圈出：GPU 型号、`TRITON_ATTN`、tool-call-parser  
- 若有 tok/s，右下角贴字条：`~XX tok/s`【预演后填】

---

### 段 3 · doctor（0:55–1:15）

**画面**

- 开发机：

```bash
node dist/cli.js doctor
```

- 输出 `LLM: OK` 和 models 列表特写  

**口播**

> 开发机通过 SSH 隧道连到 GPU 上的 vLLM。  
> doctor 确认本地私有链路可用，这是 Agent 跑工具循环的前提。

**失败预案**

- 若现场 doctor 挂了：切预先录好的 doctor 成功片段，口播改为「预录的连通性检查」。

---

### 段 4 · 四故事门禁矩阵（1:15–2:40）★ 必保段

**画面（推荐主命令）**

```bash
# 可选干净账本，ls 更清爽
# $env:LDEA_ROOT=".ldea-demo-show"
node dist/cli.js demo --suite
```

四故事同一 fixture 叙事、不同证据组合（全程离线、无需 GPU）：

| ID | 声称 | 证据 | 期望 |
|----|------|------|------|
| A | 「今天全部做完了」 | 无 git / 无测试 | `abandoned` |
| B | 「重构完可上线」 | 仅 git diff | `evidenced`（未 verified） |
| C | 「已修复，测试该绿了」 | git + **仍失败** 测试 | `evidenced`（不得 verified） |
| D | 「已修复 + 补 pytest」 | git + fail→pass + 隐私扫描 | `verified` |

- 每故事停在：报告顶部**门禁**条 + `状态计数` + 成果/未闭合  
- **结尾矩阵表必须完整保留**（`多故事门禁矩阵`）——评委 5 秒看懂差异  
- D 的隐私命中可停 2 秒：完成 ≠ 可公开  

**口播**

> 先看离线多场景——不消耗 GPU，规则引擎保证可复现。  
> 同一句「做完了」，四种证据，四种账本状态。  
> A 空口 → abandoned；B 只有代码 → evidenced，还不能写已完成；  
> C 测试仍红 → 同样进不了 verified；只有 D：代码加上测试从失败到通过，才是 verified。  
> 差别不在文笔，在证据。LLM 不能把 E 或 A 说成 V。

**剪辑要点**

- 每故事切点字幕：`A abandoned` / `B evidenced` / `C 仍红·未 verified` / `D verified`  
- 矩阵表定格 ≥ 4 秒，可叠读法：「完成叙事必须过门禁」  
- 中间长报告 2× 加速；**不要**快进矩阵 footer  

**备选（时间紧）**

```bash
node dist/cli.js demo          # 仅 A vs verified 双故事
# 或单故事补录：
node dist/cli.js demo --empty
node dist/cli.js demo --code
node dist/cli.js demo --failing
node dist/cli.js demo --verified
```

---

### 段 5 · live 含糊目标（2:25–3:25）

**画面**

```bash
node dist/cli.js demo --live
```

- 关注：多轮 tool 名称序列（git_diff / claim / ingest_test_output / scan_privacy / render_report…）  
- 可切到 `agent-trace.json` 或终端 tools 行  
- 最终报告仍出现门禁与状态计数  

**口播**

> 接下来是真正的本地智能体路径。  
> 目标故意说得很含糊：有人说修好了，有人说收工了——请模型自己规划，调用工具侦查。  
> 它可以使用 git、测试日志、隐私扫描和账本查询，但仍然不能直接把结果写成 verified。  
> 最终以工具写回的 L1 账本为准。

**剪辑**

- 中间思考/等待 8× 加速；工具返回与最终报告实时  
- 字幕列出 tool trace：`git_diff → … → render_report`  

**失败预案（重要）**

| 情况 | 处理 |
|------|------|
| 现场 live 翻车 | 使用预演成功的录像段 + 口播「完整工具轨迹如下」 |
| 只调了 1 次工具就结束 | 补 `ldea run "…"` 预录，或展示 trace 文件 |
| 模型嘴上说完成但账本未 verified | **保留**，口播强调「以账本为准，这正是门禁」 |

---

### 段 6 · 多会话 ledger（3:25–3:45）

**画面**

```bash
node dist/cli.js ls
node dist/cli.js show
# 或 show <demo-empty-id> / show <demo-id>
```

**口播**

> 每次核验都是一条 session，可以列表、筛选、回看。  
> 这不是一次性脚本输出，而是本地开发证据 ledger 的雏形。

---

### 段 7 · 收束（3:45–4:05）

**画面**

- 一张架构图（规格书 §3，可做成全屏 PNG/PPT 页）  
- 三行字：  
  1. 私有：Radeon + ROCm + vLLM  
  2. 智能体：规划 + 工具 + 记忆  
  3. 门禁：verified 才算完成  

**口播**

> LDEA：在 AMD 本地 GPU 上运行的私有开发证据智能体。  
> 它用工具收集 git 与测试，用规则账本判定真伪，用报告拒绝空口完成。  
> 谢谢。

---

## 3. 屏幕字卡（可直接做字幕）

1. `完成 ≠ 声称 · 完成 = verified`  
2. `LLM 不得自证 verified`  
3. `故事 A abandoned · 故事 B verified`  
4. `本地 127.0.0.1 · 数据不出云`  
5. `Agent 编排 · 规则判定`  

---

## 4. 预演记录表（录前填）

| 项 | 记录 |
|----|------|
| 日期 | |
| GPU / ROCm / vLLM | |
| doctor 是否一次成功 | |
| 离线 demo A/B 是否稳定 | |
| live 成功次数 / 尝试次数 | |
| live 大致耗时 | |
| tok/s | |
| 本次采用：完整 live / 预录 live | |

---

## 5. 剪辑检查单

- [ ] 时长 3:00–5:00  
- [ ] 有真实 ROCm/vLLM 画面（非纯 PPT）  
- [ ] 有 abandoned vs verified 对照  
- [ ] 有报告门禁条特写  
- [ ] 有 Agent 或明确双路径说明  
- [ ] 无真实密钥、无陌生隐私文件内容特写（demo 里的假 sk- 可保留并口播「演示用假数据」）  
- [ ] 片尾或说明里可找到源码 / 规格书位置  

---

## 6. 口播精简版（一镜备用，~90 秒）

若只能录极短版，用此稿 + 段 2/4 画面：

> LDEA 是本地开发证据智能体，跑在 AMD ROCm 的 vLLM 上。  
> 问题是：AI 和人都爱说「做完了」。  
> 我们的门禁是：没有代码和测试证据，就是 abandoned；有 diff 和测试闭环，才是 verified。  
> 模型可以规划、调工具，但不能自己给自己验真。  
> 这就是私有、可核验的开发证据 Agent。

---

## 7. 与规格书同步

剪辑完成后，把各段时间码填回：

`docs/项目规格说明书.md` → §8 演示说明表。
