#!/bin/bash
# ============================================================
# NodeFlow — 一键推送 GitHub 脚本
# 用法:
#   bash push_to_github.sh <你的GitHub用户名> <仓库名>
#   例如: bash push_to_github.sh yourname nodeflow
#
# 前置: 仓库已在 GitHub 上创建(空的,不要勾选 README)
# 认证: 任选其一
#   A. 环境变量 GITHUB_TOKEN(推荐, 用带 repo 权限的 PAT)
#   B. 本机已配置 git 凭据(gh auth 或 credential store)
# ============================================================
set -e

if [ $# -lt 2 ]; then
  echo "用法: bash $0 <GitHub用户名> <仓库名>"
  echo "示例: bash $0 yourname nodeflow"
  exit 1
fi

USERNAME="$1"
REPO="$2"
TOKEN="${GITHUB_TOKEN:-}"

echo "=== NodeFlow 推送 GitHub ==="
echo "目标: https://github.com/$USERNAME/$REPO"

# 1. 确保在仓库根目录
cd "$(dirname "$0")"
if [ ! -d .git ]; then
  echo "❌ 未找到 .git,请先 git init"
  exit 1
fi

# 2. 配置 remote(处理 https 含 token 与纯 ssh 两种)
if git remote | grep -q origin; then
  echo "✓ origin 已存在,更新 remote URL"
fi

if [ -n "$TOKEN" ]; then
  REMOTE_URL="https://${USERNAME}:${TOKEN}@github.com/${USERNAME}/${REPO}.git"
  echo "  使用 GITHUB_TOKEN 认证 (https)"
else
  REMOTE_URL="https://github.com/${USERNAME}/${REPO}.git"
  echo "  使用本机凭据认证 (https), 若无缓存会提示输入账号密码"
fi

git remote set-url origin "$REMOTE_URL" 2>/dev/null || git remote add origin "$REMOTE_URL"

# 3. 确认分支
BRANCH=$(git branch --show-current 2>/dev/null || echo main)
if [ -z "$BRANCH" ]; then
  BRANCH="main"
  git branch -M main
fi
echo "  分支: $BRANCH"

# 4. 提交未提交内容(若有)
if [ -n "$(git status --porcelain)" ]; then
  echo "  检测到未提交改动,先提交..."
  git add -A
  git commit -m "chore: sync before push" || echo "  (无新增提交)"
fi

# 5. 推送
echo "=== 推送中... ==="
if git push -u origin "$BRANCH" 2>&1; then
  echo ""
  echo "✅ 推送成功!"
  echo "仓库地址: https://github.com/$USERNAME/$REPO"
  echo "如果首次推送 HTTPS 失败, 可改用 SSH:"
  echo "  git remote set-url origin git@github.com:$USERNAME/$REPO.git && git push -u origin $BRANCH"
else
  echo ""
  echo "❌ 推送失败。常见原因与处理:"
  echo "  1. 仓库未创建 → 去 github.com 新建同名空仓库"
  echo "  2. 认证失败 → export GITHUB_TOKEN=你的PAT 后重试"
  echo "  3. 远程有冲突 → git pull --rebase origin $BRANCH 后重试"
  exit 1
fi