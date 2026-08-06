---
name: git-push
description: Git push troubleshooting and workflow for this repo. Use when git push fails or when syncing with remote.
---

# Git Push 注意事项

本仓库在受限网络环境中，SSH 端口 22 被阻断，需通过 443 端口推送。
同时本仓库为多人协作项目，禁止直接 `git pull`，必须使用 fetch + rebase 工作流。

## 同步工作流（必读）

**禁止使用 `git pull`**。`git pull` 会产生不必要的 merge commit，污染提交历史。

正确流程：

```bash
# 1. 拉取远程最新代码（不合并）
git fetch origin

# 2. 将本地 commit rebase 到远程分支之上
git rebase origin/main

# 3. 如有冲突，解决后继续
# git add <冲突文件>
# git rebase --continue

# 4. 推送
git push origin main
```

如果 push 时被拒绝（non-fast-forward），说明远程有新提交，重复上述流程即可。

## 核心原理

`ssh.github.com` 是 GitHub 的 SSH-over-HTTPS 端点，**默认走 443 端口**，无需额外配置即可穿透防火墙。

只要 remote 指向 `git@ssh.github.com:...` 且 `~/.ssh/id_ed25519.pub` 已添加到 GitHub，git push 就能正常工作。

## 当前配置

- Remote: `git@ssh.github.com:qingxiaozi/ArtisanAI.git`
- SSH key: `~/.ssh/id_ed25519`（公钥 `id_ed25519.pub` 需添加到 GitHub）

## 生成 SSH Key（如无密钥）

```bash
ssh-keygen -t ed25519 -C "artisanai" -f ~/.ssh/id_ed25519 -N ""
```

将 `~/.ssh/id_ed25519.pub` 内容添加到 https://github.com/settings/ssh/new
