# 未提交改动评审（工作区 6 文件，+257/-58）

评审基线：`a8dac07`（HEAD）· 评审日期：2026-08-01
验证方式：实跑 `pytest tests/`＋针对性行为探针，不依赖代码阅读推断。

---

## ✅ 修复状态（2026-08-02 更新）

**全部 5 项（3×P0 + 2×P1）已修复并验证，套件回到全绿。**

```
评审时（HEAD a8dac07）:  42 passed /  1 skipped     ← 基线
评审时（工作区）      :  37 passed /  5 failed      ← 5 个失败
修复后              : 113 passed /  1 skipped      ← 现在
scripts/verify_bugfixes.py: exit 0（真实组件集成验证 15 项全过）
```

| 项 | 状态 | 修复位置 | 锁住它的测试 |
|---|---|---|---|
| P0-1 history 取错窗口 | ✅ 已修 | `stores.py` 子查询 | `test_memory_stores.py`（7 个，新建） |
| P0-2 快速通道子串误判 | ✅ 已修 | `orchestrator._GREET_RE` 整句锚定 | 正例 23 + 反例 14 + 6 个行为测试 |
| P0-3 命名脱节致专家失效 | ✅ 已修 | `router.logical_expert_name()` 单一权威 | 3 个命名测试 + 结构性测试 |
| P1-1 forbidden 守卫是死代码 | ✅ 已修 | `router._decide()` 单一收口 | 10 组参数化 + 结构性守卫 |
| P1-2 roomy 归零静默失败 | ✅ 已修 | `activate()` 加 `tid<0` 守卫 | 2 个响亮失败测试 |
| §6 仓库卫生 | ✅ 已做 | `.gitignore` 补运行时产物 | — |
| §4 torch 解耦加固 | ✅ 已加 | — | 子进程守卫测试 |

**测试判别力已验证**（不只是"跑绿"，而是确认能抓住原 bug）：

| 测试组 | 对旧实现的判别力 |
|---|---|
| history 窗口 | 坏 SQL 返回 `turn-01..12`，测试必红 |
| 快速通道反例 | 旧子串实现 **13/14 条误判**，测试必红 |
| forbidden 收口 | 旧守卫位置 **5/7 条分支泄漏**，测试必红 |
| torch 守卫 | 本机未装 torch，改回顶层 import 直接 ImportError |

> §1~§7 的原始分析保留在下方，作为这批 bug 的成因记录。

---

## 0. 一句话结论（评审时）

**这批改动现在不能提交。** 工作区已经把已提交的测试套件从 `42 passed / 1 skipped`
跑成 **`37 passed / 5 failed / 1 skipped`**，其中 1 个失败是真回归（新代码悄悄
关掉了 7/30 刚提交的 BUG-2 修复），另有 2 个未被任何测试覆盖的行为回归。

| 类别 | 数量 | 处理 |
|------|------|------|
| P0 真 bug，必须修 | 3 | 见 §1 |
| P1 设计漏洞，建议同批修 | 2 | 见 §2 |
| 预期内的行为变更，改测试即可 | 3 处失败 | 见 §3 |
| 可直接提交 | 1 | 见 §4 |

---

## 1. P0 —— 真 bug，修完才能提交

### P0-1 `memory/stores.py` `history()` 取错了窗口（新引入的回归）

意图是"修时间戳相同时顺序翻转"，但顺带把**取最近 N 条**改成了**取最早 N 条**。

```
旧: ORDER BY ts DESC LIMIT 12  + reversed()  -> 最近 12 条，正序
新: ORDER BY ts ASC, rowid ASC LIMIT 12      -> 最早 12 条，正序
```

实测（20 轮会话，limit=12）：

```
返回: turn-01 ... turn-12     期望: turn-09 ... turn-20
>>> 最近 8 轮上下文被丢弃 <<<
```

后果：**会话越长，模型看到的上下文越陈旧**。超过 12 轮后模型永远读不到刚说过的话，
表现为"失忆"、反复问同样的问题 —— 而且不报错，只是答得越来越不对题。
这类问题在短会话冒烟测试里 100% 看不出来。

正确写法（子查询保留"取最近 N 条"，同时保住 rowid tiebreak）：

```sql
SELECT role, content FROM (
    SELECT role, content, ts, rowid FROM turns WHERE session=?
    ORDER BY ts DESC, rowid DESC LIMIT ?
) ORDER BY ts ASC, rowid ASC
```

tiebreak 那半边是对的（实测 5 条同 ts 记录顺序稳定），保留。

**必补测试**：①20 轮取 12 条必须是 turn-09..turn-20；②5 条相同 ts 顺序稳定。

---

### P0-2 `orchestrator._is_simple_query()` 子串匹配，误判率 8/8

`any(g in ql for g in self._GREETINGS)` 是**子串**匹配，而问候词里有 `hi` / `hey`
这种会嵌在普通英文单词里的短词：`t-hi-s`、`w-hi-ch`、`hi-story`、`hi-erarchy`、
`somet-hi-ng`、`mac-hi-ne`、`t-hey`。

实测 8 条正常提问，**8 条全部被误判为寒暄**，直接跳过 plan + ReAct：

```
[>>> 误判为寒暄 <<<] What is this repo about?
[>>> 误判为寒暄 <<<] check the history log
[>>> 误判为寒暄 <<<] Which adapter is mounted?
[>>> 误判为寒暄 <<<] summarize this file
[>>> 误判为寒暄 <<<] 分析一下 architecture 有什么问题
[>>> 误判为寒暄 <<<] This crashes, why?
[>>> 误判为寒暄 <<<] hierarchy of the skill map?
[>>> 误判为寒暄 <<<] audit the machine config
```

**这已经造成实际损失**：`tests/test_orchestrator_l3.py::test_plan_fallback_is_logged`
用的查询是 `"do something"` —— `somet(hi)ng` 命中 `hi` → 走快速通道 → 根本不进
planning → 7/30 提交的 BUG-2 日志修复被静默绕过，测试变红。
**新功能悄悄关掉了上周刚修的 bug，唯一发现它的途径就是那条回归测试。**

修法：整句锚定 + 词边界，而不是子串包含。

```python
_GREET_RE = re.compile(
    r"^(?:你好呀|您好呀|你好|您好|在吗|在么|你在吗|谢谢|感谢|你是谁|你是什么|"
    r"早上好|下午好|晚上好|hi|hello|hey|thanks|thank you)"
    r"[\s!！。.?？~、,，]*$", re.I)

def _is_simple_query(self, q: str) -> bool:
    ql = (q or "").strip().lower()
    return bool(ql) and len(ql) <= 40 and bool(_GREET_RE.match(ql))
```

**必补测试**：正例（你好/hi/谢谢/早上好）走快速通道；反例（上面 8 条）必须走完整
流程。反例清单直接搬进测试，这是最值钱的部分。

**附带两个小问题**（同批修掉）：
- 快速通道 `RunResult` 里 `"switches": []` 是硬编码的，但它前面调了
  `_mount_skill("agent", query)` —— 真发生了挂载就会漏报，跟 7/30「每轮独立计数」
  那个修复的口径不一致。应改成读真实 `engine.switch_log`。
- 更关键：为了回一句"你好"去挂 agent 专家，在 tight 模式下会触发**整个 server
  重启换 LoRA**。快速通道本意是省开销，结果最贵的操作没省掉。建议寒暄直接用 base
  （`_mount_skill("base")` 或不挂），这才是"快速"。

---

### P0-3 `router.py` 改名与 `EXPERT_NAME_ALIASES` 脱节 → agent 专家静默失效

改动把 `skill_map["agent"]` 从 `teichai_plan` 改成了 `teichai_fable5_plan`，
但没动 `EXPERT_NAME_ALIASES`，而 `lora_scan.discover_adapters()` 仍在把磁盘目录
反查成**逻辑名**注册。两边对不上了。

实测（造 4 个真实目录跑 `discover_adapters`）：

```
磁盘目录     : ['btl3', 'cybersec', 'rag_n7', 'teichai_fable5_plan']
注册键名     : ['btl3', 'cybersec', 'rag_n7', 'teichai_plan']     <- 反查成逻辑名
skill_map要求: teichai_fable5_plan
agent 能挂载 : False  >>> 静默降级为 base <<<
```

而 `app.py` 里有这段"优雅降级"：

```python
if ad is not None and ad not in engine.adapters:
    router.skill_map[skill] = None   # graceful degrade to base
```

所以**不会崩、不会报错**，只是 agent 专家（默认路由 + 全部 planning）从此永远不挂载，
全程跑裸 base。这正是最难发现的一类故障：能启动、能回答、质量悄悄塌掉。

还要注意 `mol_engine_llamacpp.load_base()` 这次改成用父目录名注册，走的是**磁盘名**
（`teichai_fable5_plan`），没过 `ondisk_to_logical`。于是 llamacpp 后端会同时存在
`teichai_fable5_plan`(真 id) 和 `teichai_plan`(id=-1) 两个键指向同一个 LoRA。

**建议修法（二选一，别折中）**：
- **A（推荐，改动最小）**：`router.py` 的 `skill_map` 改回 `teichai_plan`，只保留
  注释澄清。别名层本来就是为"磁盘名不可改"设计的，已提交的测试也编码了这个契约。
- **B（彻底）**：删掉 `EXPERT_NAME_ALIASES`，逻辑名 == 磁盘名 == `teichai_fable5_plan`，
  同步改 `lora_scan.py`、`app.py` 注释和 2 个测试。

无论选哪个，**`load_base()` 的命名都必须和 `discover_adapters()` 走同一套映射**。

---

## 2. P1 —— 设计漏洞，建议同批修

### P1-1 forbidden 检查加在了永远不会执行的分支上

新增的 `if is_forbidden(adapter): adapter = None` 只在 `route()` **最后一个默认分支**里。
但 `route()` 有 6 个返回点，而 orchestrator 的真实调用是：

```python
decision = self.router.route(step["desc"], task_tag=step["skill"])
```

带 `task_tag` → 命中第 1 个分支 `explicit tag wins` → **直接返回，完全绕过守卫**。
也就是说这道防线在主链路上是死代码。

修法：把守卫收成单一收口，让 6 个返回点都过一遍。比如统一构造：

```python
def _decide(self, skill, reason):
    ad = self.skill_map.get(skill)
    return RouteDecision(skill, None if (ad and is_forbidden(ad)) else ad, reason)
```

顺带：`is_forbidden(None)` 会抛 `TypeError`（`FORBIDDEN_RE.match(None)`），
而 `skill_map["base"]` 本来就是 `None`。收口时一并加空值保护。

**必补测试**：`route("...", task_tag="agent")` 在 skill_map 被污染成 `fable5` 时
必须返回 `None`，而不是 `fable5`。

### P1-2 roomy 模式 `activate()` 把响亮失败变成了静默失败

新的归零逻辑本身是对的（多 LoRA 混合确实要显式置零）。但当目标适配器 `id == -1`
（只注册未预载，见 P0-3 会产生这种条目）时：

```python
body = [{"id": a["id"], "scale": 1.0 if a["id"] == tid else 0.0} ...]
```

`tid = -1` 不匹配任何 `id >= 0` 的项 → **全部置 0.0** → server 正常接受 →
实际跑 base，但 `active_adapter` 记成了目标名。改前是发一个非法 id、server 报错、
日志有记录；改后变成"成功地什么都没挂"。

建议在 `tid < 0` 时显式 `log.error` 并走 disable 分支，别让它假装成功。

---

## 3. 预期内的行为变更 —— 改测试即可（不是 bug）

这 3 个失败是改动的合理结果，但**测试必须同步更新才能提交**，否则套件长期红着就等于没有。

| 失败测试 | 原因 | 处理 |
|---|---|---|
| `test_activate_posts_correct_scale` | 旧断言 `[{"id":0,"scale":1.0}]`，新逻辑发全量带 0.0 | 改断言为"目标 1.0、其余全 0.0"，这正是新契约 |
| `test_skill_map_routing`<br>`test_skill_map_excludes_removed_experts` | 期望 `teichai_plan` | 取决于 P0-3 选 A 还是 B；选 A 则自动恢复绿 |
| `test_gear_machine_disables_thinking_on_empty_rate` | 断言初始 `_thinking_on is True`，默认已翻成 False | **不能只把断言改成 False** —— 那测试就废了。应在测试里显式 `orch._thinking_on = True` 再验证 gear machine 能把它关掉 |

最后一条尤其注意：默认值翻转后，"档位机能关 thinking"这个能力就没有测试覆盖了。
改断言是掩盖，显式置位才是保住覆盖。

---

## 4. 可以直接提交

**`app.py` torch 懒加载** —— 只是把 `from screwshell.core.mol_engine import MoLEngine`
挪进 peft 分支，无行为分叉，风险最低。
可选加固：加一条"llamacpp 后端下 `sys.modules` 里不出现 torch"的守卫测试，
这样以后谁再在顶层 import torch 会立刻被拦住。

**orchestrator 的 phase 事件**（`quick`/`planning`/`step_i_n`/`finalizing`）——
纯事件发射，不改控制流，跟 `ui/app.py` 一起提交即可。UI 侧接线已核对：
`phase` 事件消费、`step_i_n` 解析、`_force_deep` 透传都在。

---

## 5. 建议的提交拆分

```
1. fix(memory): history() 取最近 N 条而非最早 N 条 + 同 ts 顺序稳定   [P0-1 + 测试]
2. fix(router): 统一 forbidden 收口；澄清 agent 专家命名权威          [P0-3 + P1-1 + 测试]
3. fix(llamacpp): roomy 模式显式归零 + id<0 守卫 + 命名走同一映射      [P1-2 + 更新测试]
4. feat(orchestrator): 寒暄快速通道（整句锚定匹配）+ phase 事件        [P0-2 修好 + 正反例测试]
5. feat(ui): 阶段进度展示与深度模式开关                                [随 4 一起]
6. chore(app): torch 懒加载，llamacpp 后端免装 torch                   [可先独立提交]
```

提交前闸口：`pytest tests/ -q` 必须回到 **全绿**（预期 48+ passed / 1 skipped）。

---

## 6. 顺带：仓库卫生

`git status` 里 `.workbuddy/` 和 `demo_workspace/.screwshell/` 是运行时产物，
建议加进 `.gitignore`，避免误提交本地状态。

---

## 7. 拔高一层：为什么这三个 bug 长得一模一样

P0-1、P0-2、P0-3 表面上是三个独立 bug，实际是**同一个模式**：

> 每一处都"看起来只是顺手改个小地方"，实际改掉了一个**没有被任何断言锁住的隐含契约**，
> 而且失败方式全是**静默降级**（丢上下文 / 跳过调查 / 不挂专家），不是崩溃。

三条隐含契约分别是：`history()` 返回的是**最近**窗口、"do something" 是**任务**不是寒暄、
适配器命名的**唯一权威**是逻辑名。三条都没写在测试里，所以改动时无人拦。

对应到流程上，缺的不是"更细心的 code review"（diff 逐行看都挑不出 `ORDER BY` 的问题），
而是三样东西：

1. **提交前跑测试的硬闸**。5 个失败是现成的、免费的信号，只是没人跑。
   这是投入产出比最高的一条 —— 一个 pre-commit hook 就能拦住今天 4 个问题里的 3 个。
2. **命名权威唯一化**。现在 `lora_scan` / `llamacpp load_base` / `router.skill_map`
   三处各自命名适配器，任何一处改名都会静默脱节。应收敛到单一函数，其余只准调用。
3. **"静默降级"必须留痕**。`graceful degrade to base` 和 `activate()` 全零这两处，
   都应该在降级时打 `log.error` 并计入 `RunResult.stats`，让"跑得通但没用上专家"
   在报告里可见 —— 否则性能与质量回退永远查不出来。

第 3 条正好接上 `E2E_OPTIMIZATION_REVIEW.md` 里"能跑但行为没验证"的主题：
**行为验证的前提，是失败得足够响。**
