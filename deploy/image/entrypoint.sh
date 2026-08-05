#!/bin/bash
# entrypoint.sh — 写 ZK myid → 配置 SSH → 启动 supervisord (PID 1)
# NODE_ROLE 由 docker-compose env 注入: hadoop01 / hadoop02 / hadoop03
set -e
case "${NODE_ROLE}" in
  hadoop01) MYID=1 ;;
  hadoop02) MYID=2 ;;
  hadoop03) MYID=3 ;;
  *) echo "ERROR: NODE_ROLE 未设置或非法 (${NODE_ROLE}), 需要 hadoop01|hadoop02|hadoop03"; exit 1 ;;
esac
mkdir -p /data/zookeeper
echo "${MYID}" > /data/zookeeper/myid

# ---- 配置 SSH (从挂载的 /ssh-config 复制到正确位置, 修正权限) ----
mkdir -p /run/sshd /root/.ssh
if [ -d /ssh-config ]; then
  cp /ssh-config/sshd_config /etc/ssh/sshd_config
  cp /ssh-config/authorized_keys /root/.ssh/authorized_keys
  cp /ssh-config/id_rsa /root/.ssh/id_rsa
  cp /ssh-config/id_rsa.pub /root/.ssh/id_rsa.pub
  cp /ssh-config/ssh_config /root/.ssh/config
  # 修复 Windows CRLF 换行符
  sed -i 's/\r$//' /etc/ssh/sshd_config /root/.ssh/authorized_keys /root/.ssh/id_rsa /root/.ssh/id_rsa.pub /root/.ssh/config
  chmod 600 /root/.ssh/id_rsa /root/.ssh/config /root/.ssh/authorized_keys
  chmod 644 /root/.ssh/id_rsa.pub
  # 生成 host keys
  ssh-keygen -A 2>/dev/null
  /usr/sbin/sshd
fi

# Hive 4.2 编译 Tez 计划需 Tez jar 在 classpath (tez.lib.uris 只供 AM 用, 编译期要本地 jar)
# 启动前把 Tez jar 软链到 hive/lib (幂等, 容器每次启动都做)
for j in /opt/tez/*.jar; do
  ln -sf "$j" /opt/hive/lib/$(basename "$j") 2>/dev/null || true
done

# ---- 清理残留 PID 文件 (容器 stop/start 后旧 PID 可能被其他进程占用, 导致服务拒绝启动) ----
rm -f /opt/hive/conf/hiveserver2.pid /opt/hive/conf/hivemetastore.pid 2>/dev/null || true
rm -f /tmp/hadoop-root-*.pid 2>/dev/null || true

exec supervisord -n -c "/etc/supervisor/conf.d/supervisord-${NODE_ROLE}.conf"
