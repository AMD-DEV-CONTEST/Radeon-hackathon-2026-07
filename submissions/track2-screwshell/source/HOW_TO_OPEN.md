# 如何打开 ScrewShell 界面（真机 W7900 @ 36.150.116.206）

> 部署/排错的完整流程见 **`deploy/w7900/RUNBOOK.md`**。本文只回答"我怎么把界面点开"。

## 为什么直接打 `localhost:7860` 打不开？

界面跑在**远程比赛机**上，不在你自己的电脑。`localhost` 指向你本机，所以当然是空的。

**真机当前状态（2026-08-02 实测）**

| 服务 | 状态 |
|---|---|
| `llama-server` :8080 | ✅ 在跑，Qwen3.6-27B-Q4_K_M 已载入 W7900 |
| Gradio UI :7860 | ✅ 在跑 |
| LoRA 专家 | **3 个**预载：`btl3` / `cybersec` / `rag_n7` |
| `teichai_fable5_plan` | ❌ **无权重来源**，agent 专家降级为 base |

## 方式一：SSH 隧道（最稳，推荐）

在你**自己电脑**上开一个终端（cmd / PowerShell / Git Bash 都行），粘贴运行：

```
ssh -p 31010 -L 7860:127.0.0.1:7860 root@36.150.116.206
```

- **端口是 31010**（不是 31033，旧文档写错过）
- 认证只认公钥；若提示 `Permission denied (publickey)`，说明你这台机器的
  `~/.ssh/id_ed25519.pub` 还没进服务器白名单
- **这个黑窗口保持开着，不要关**
- 然后浏览器打开：**http://localhost:7860**

> 原理：借用已通的 SSH 连接，把远程机的 7860 端口"搬"到你本机的 7860。
> 不依赖云防火墙放行，确定可用。

## 方式二：公网直连（碰运气）

浏览器直接开：**http://36.150.116.206:7860**

> UI 绑的是 `127.0.0.1`，且云平台大概率没放行 7860 —— 基本不通，用方式一。

## 进去后你会看到什么

- 左侧聊天框：打字提问 → 多步调查（规划 → 调工具 → 换专家 → 出带引用的答案）
- 右侧面板：当前激活的 LoRA 专家 + 切换历史、工具调用、证据卡片、权限审计、GPU 状态
- 问代码类 → 切 `btl3`、问安全 → 切 `cybersec`、问文档 → 切 `rag_n7`，秒切不重启
- 问规划类 → 本应切 `teichai_plan`，**但该权重缺失，会跑 base**（不是 bug，是数据缺口）

## 服务掉了怎么重启（在远程机上）

```bash
# UI —— 分两条执行，别合并（合并会 pkill 掉自己）
pkill -f "screwshell.ui.app"; sleep 2
nohup bash /workspace/persistent/screwshell_run/run_ui.sh > /tmp/ui.log 2>&1 &

# 模型服务
pkill -f llama-server; sleep 3
nohup bash /workspace/persistent/screwshell_run/run_roomy_server.sh > /tmp/llama.log 2>&1 &
```

两个脚本的权威版本在 `deploy/w7900/`，同步过去即可：

```bash
scp -P 31010 deploy/w7900/run_*.sh root@36.150.116.206:/workspace/persistent/screwshell_run/
```

> ⚠️ 真机根目录是 `/workspace/persistent/screwshell_run`，**不是 `/persistent`**。
> 旧文档和根目录的 `_run_*.sh` 写的是后者，照着做必然失败，现已改成报错存根。
