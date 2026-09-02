# XAI 安全扫描报告（T2 · 六维验收·维度三 安全验收）

> 生成方式：`scripts/security_scan.py`（只读、零副作用） + 手动合规探针。
> 扫描时间：2026-07-28 | 服务端：127.0.0.1:8000（在线）

## 结论：✅ 运行层无高危项（可交付）

| 检查项 | 结果 | 说明 |
|---|---|---|
| 硬编码密钥/凭证 | ✅ 0 处 | core/ + 根 *.py 全扫，无 sk-/AKIA/ghp_/私钥等 |
| 危险函数调用 | ✅ 0 处真实调用 | 8 处命中均为「检测规则定义」本身（见下） |
| 依赖供应链 | ✅ 低风险 | 仅可选 PyYAML(MIT)，无强制高危依赖 |
| 鉴权闸门 | ✅ 全 PASS | 4 个关键接口均「无 token→401 / 带 token→200」 |
| Guardian 写拦截 | ✅ PASS | grok-write 走审批工单，不直接执行 |

## 1. SAST 静态代码扫描

- 扫描范围：`core/**/*.py` + 根 `*.py`
- **硬编码密钥：0 处** —— 未发现任何 `sk-`/`AKIA`/`ghp_`/`xox*`/私钥/明文 password。
- **危险函数模式：命中 8 处，但全部为误报（实为安全检测规则）**：
  - `core/grok_build_engine.py:101` —— `_DANGER_PATTERNS = ("eval(", "exec(", "os.system(", "pickle.load(")`：这是**用于扫描用户代码的危险模式清单**，并非调用。
  - `core/cognition/verifier.py:63` —— 同上，定义待检测的危险调用列表。
  - `core/adapters/openclaw_adapter.py:441-444` —— 正则规则字符串 `r"os\.system\("` / `r"eval\("` / `r"exec\("`，配套文案「P0: 禁止使用」——这是**适配器自带的安全 lint 规则**，用于拦截危险命令。
  - 结论：**代码库主动定义并使用了危险调用拦截规则，自身并未直接调用 eval/exec/os.system**。这正是 Guardian 安全治理的体现。

## 2. 依赖供应链风险

`requirements.txt` 仅 1 条：`PyYAML>=6.0`（可选、MIT 许可，低风险）。
无 `requests`/`torch`/`transformers` 等强制重依赖 → 供应链攻击面极窄。

## 3. 鉴权闸门（关键接口实测）

| 接口 | 无 token | 带 token | 判定 |
|---|---|---|---|
| `/api/status` | 401 | 200 | PASS |
| `/api/memory` | 401 | 200 | PASS |
| `/api/metrics` | 401 | 200 | PASS |
| `/api/chat/send` | 401 | 200 | PASS |

`_check_auth()` 在 `do_POST`/`do_GET` 集中校验 `X-Auth-Token`，未携带即拒。新增的 `/api/metrics` 自动继承该闸门。

## 4. Guardian 写操作拦截（实测）

- 请求：`POST /api/guardian/grok-write/request` `{"task":"...","reason":"..."}`
- 响应：`{"ok": true, "id": "APR-0001", "status": "pending"}`
- 说明：Grok Build 写操作**不直执行**，而是生成待审批工单，由人工在 `/api/guardian/pending` 批准/拒绝后才落地。治理平面闭环。

## 残余建议（非阻塞，进 v3.1 实证期）

1. **P1 接 CI 安全链**：当前为脚本级扫描，建议接入 `bandit`(SAST) + `pip-audit`(依赖 CVE) 作为提交门禁，自动化复跑本脚本。
2. **P2 限流细化**：`_CHAT_SEM` 为全局并发上限（20），可进阶为按 token 的令牌桶，防单客户端占满。
3. **P2 渗透常态化**：Guardian 拦截、鉴权闸门已实测，建议把本脚本纳入每次发布的回归项。

---
*本报告的 4 项检查均可由 `python3 scripts/security_scan.py` 复跑。*
