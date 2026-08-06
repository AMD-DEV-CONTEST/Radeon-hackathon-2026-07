#!/bin/bash
# 启动 sshd（容器无 systemd，需手动启动）
set -e
mkdir -p /run/sshd
if pgrep -x sshd > /dev/null; then
    echo "sshd 已在运行 (pid $(pgrep -x sshd))"
else
    /usr/sbin/sshd
    echo "sshd 已启动"
fi
