#!/usr/bin/env bash
# setup-hadoop-direct.sh — Single-node Hadoop direct install (no Docker)
#
# Software stack identical to Docker version:
#   JDK 8 (Hadoop/HBase/ZK) + JDK 21 (Hive 4.2.0)
#   Hadoop 3.3.6 + ZK 3.8.4 + HBase 2.5.15 + Hive 4.2.0 + Tez 0.10.2
#   MySQL 8.0 (Hive Metastore) + MySQL Connector/J 8.0.30
#   supervisord (autorestart=false) + JMX Exporter + Prometheus
#
# Topology: single-node (no HA, no JournalNode/ZKFC)
#   ZK retained: HBase distributed=true mode requires external ZK coordination
#   JN removed: only needed for HDFS HA (QJM), single NN does not need it
#   ZK admin.serverPort=9888: avoid conflict with YARN RM web UI 8080
# SSH on port 22 (single-node direct install, no Docker port mapping)
# Usage: bash scripts/setup-hadoop-direct.sh
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="/data"
LOG_DIR="/logs"
TARBALLS_DIR="/workspace/tarballs"
REMOTE_URL="http://8.148.228.51/repo/tarballs"
JAVA8_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
JAVA21_HOME="/usr/lib/jvm/java-21-openjdk-amd64"
SUPERVISOR_CONF="/etc/supervisor/conf.d"
SUPCTL="supervisorctl -c $SUPERVISOR_CONF/supervisord-hadoop01.conf"

export DEBIAN_FRONTEND=noninteractive

echo "===== Single-node Hadoop direct install (software stack matches Docker) ====="

# ============================================================
# 0. Cleanup residuals (ensure script is re-runnable)
# ============================================================
echo "[0/10] Cleaning up residual processes and locks..."

# Stop old supervisord
supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf shutdown >/dev/null 2>&1 || true
pkill -f supervisord 2>/dev/null || true

# Kill residual Java processes (NN/DN/RM/NM/JHS/HM/RS/ZK/HMS/HS2)
pkill -9 -f 'org.apache.hadoop' 2>/dev/null || true
pkill -9 -f 'org.apache.hbase' 2>/dev/null || true
pkill -9 -f 'org.apache.zookeeper' 2>/dev/null || true
pkill -9 -f 'org.apache.hive' 2>/dev/null || true

# Clean up PID files
rm -f /data/hadoop/pids/*.pid /tmp/hadoop-root-*.pid /opt/hive/conf/*.pid 2>/dev/null || true

# Clean up dpkg locks (prevent lock residual from previous interrupted install)
kill -9 $(lsof /var/lib/dpkg/lock-frontend 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true
kill -9 $(lsof /var/lib/dpkg/lock 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true
rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true
dpkg --configure -a 2>/dev/null || true

sleep 2

# ============================================================
# 1. Install system dependencies (match Dockerfile + MySQL)
# ============================================================
echo "[1/10] Installing system dependencies..."
apt-get update -y
apt-get install -y --no-install-recommends \
  openjdk-8-jdk-headless supervisor netcat-openbsd dnsutils \
  curl wget ca-certificates python3 krb5-user libsnappy-dev \
  openssh-client openssh-server bash mysql-server
echo "  Java 8: $($JAVA8_HOME/bin/java -version 2>&1 | head -1)"

# jps symlink (agent config.py expects /usr/bin/jps)
ln -sf "$JAVA8_HOME/bin/jps" /usr/bin/jps

# ============================================================
# 2. Download + extract tarballs (match Docker image build)
# ============================================================
echo "[2/10] Downloading + installing packages..."
mkdir -p "$TARBALLS_DIR"

# Package list: filename|extracted dir name|target path|official download URL
PACKAGES=(
  "openlogic-openjdk-21.0.11+10-linux-x64.tar.gz|openlogic-openjdk-21.0.11+10-linux-x64|$JAVA21_HOME|https://builds.openlogic.com/downloadJDK/openlogic-openjdk/21.0.11+10/openlogic-openjdk-21.0.11+10-linux-x64.tar.gz"
  "hadoop-3.3.6.tar.gz|hadoop-3.3.6|/opt/hadoop|https://archive.apache.org/dist/hadoop/common/hadoop-3.3.6/hadoop-3.3.6.tar.gz"
  "apache-zookeeper-3.8.4-bin.tar.gz|apache-zookeeper-3.8.4-bin|/opt/zookeeper|https://archive.apache.org/dist/zookeeper/zookeeper-3.8.4/apache-zookeeper-3.8.4-bin.tar.gz"
  "hbase-2.5.15-bin.tar.gz|hbase-2.5.15|/opt/hbase|https://archive.apache.org/dist/hbase/2.5.15/hbase-2.5.15-bin.tar.gz"
  "apache-hive-4.2.0-bin.tar.gz|apache-hive-4.2.0-bin|/opt/hive|https://archive.apache.org/dist/hive/hive-4.2.0/apache-hive-4.2.0-bin.tar.gz"
  "apache-tez-0.10.2-bin.tar.gz|apache-tez-0.10.2-bin|/opt/tez|https://archive.apache.org/dist/tez/0.10.2/apache-tez-0.10.2-bin.tar.gz"
)

for pkg in "${PACKAGES[@]}"; do
  IFS='|' read -r filename src_dir target_path official_url <<< "$pkg"

  # Skip if already installed
  if [ -d "$target_path" ] && [ "$(ls -A "$target_path" 2>/dev/null)" ]; then
    echo "  $filename already installed, skipping"
    continue
  fi

  # Download (prefer remote server, fallback to official source)
  if [ ! -f "$TARBALLS_DIR/$filename" ]; then
    echo "  Downloading $filename ..."
    if curl -sf --connect-timeout 5 "$REMOTE_URL/$filename" -o "$TARBALLS_DIR/$filename" 2>/dev/null; then
      echo "    Downloaded from remote server"
    else
      echo "    Remote unavailable, falling back to official source ..."
      wget -q -O "$TARBALLS_DIR/$filename" "$official_url"
    fi
  else
    echo "  $filename already exists, skipping download"
  fi

  # Extract + rename
  echo "    Extracting to $target_path ..."
  tar -xzf "$TARBALLS_DIR/$filename" -C "$(dirname "$target_path")/"
  mv "$(dirname "$target_path")/$src_dir" "$target_path"
done

# MySQL Connector JAR
MYSQL_JAR="mysql-connector-java-8.0.30.jar"
if [ ! -f "/opt/hive/lib/mysql-connector-java.jar" ]; then
  if [ ! -f "$TARBALLS_DIR/$MYSQL_JAR" ]; then
    echo "  Downloading $MYSQL_JAR ..."
    if curl -sf --connect-timeout 5 "$REMOTE_URL/$MYSQL_JAR" -o "$TARBALLS_DIR/$MYSQL_JAR" 2>/dev/null; then
      echo "    Downloaded from remote server"
    else
      wget -q -O "$TARBALLS_DIR/$MYSQL_JAR" "https://repo1.maven.org/maven2/mysql/mysql-connector-java/8.0.30/mysql-connector-java-8.0.30.jar"
    fi
  fi
  cp "$TARBALLS_DIR/$MYSQL_JAR" /opt/hive/lib/mysql-connector-java.jar
fi

# JMX exporter (symlink from project repo, matches Docker mount)
ln -sf "$PROJ_DIR/deploy/config/jmx-exporter" /opt/jmx-exporter

# hbase-wrapper.sh (force Java 8, matches Docker mount)
cat > /usr/local/bin/hbase << 'WRAPPER'
#!/bin/bash
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH
exec /opt/hbase/bin/hbase "$@"
WRAPPER
chmod +x /usr/local/bin/hbase
# Ensure wrapper uses unix line endings
sed -i 's/\r$//' /usr/local/bin/hbase

# beeline.sh fix (Java 21 compatibility, matches Docker mount)
cp "$PROJ_DIR/deploy/image/beeline.sh" /opt/hive/bin/ext/beeline.sh
sed -i 's/\r$//' /opt/hive/bin/ext/beeline.sh
chmod +x /opt/hive/bin/ext/beeline.sh

# Hive/Hadoop guava conflict fix (matches Dockerfile)
rm -f /opt/hive/lib/guava-*.jar
cp /opt/hadoop/share/hadoop/hdfs/lib/guava-*.jar /opt/hive/lib/

# Tez jar symlink to Hive lib (matches entrypoint.sh)
for j in /opt/tez/*.jar; do
  ln -sf "$j" /opt/hive/lib/$(basename "$j") 2>/dev/null || true
done

echo "  Hadoop:  $(JAVA_HOME=$JAVA8_HOME /opt/hadoop/bin/hadoop version 2>&1 | head -1)"
echo "  Java 21: $($JAVA21_HOME/bin/java -version 2>&1 | head -1)"

# Environment variables (current session)
export JAVA_HOME=$JAVA8_HOME
export HADOOP_HOME=/opt/hadoop
export HADOOP_CONF_DIR=/opt/hadoop/etc/hadoop
export HIVE_HOME=/opt/hive
export HBASE_HOME=/opt/hbase
export ZK_HOME=/opt/zookeeper
export TEZ_HOME=/opt/tez

# /etc/profile.d (available after SSH login)
cat > /etc/profile.d/hadoop.sh << 'EOF'
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export HADOOP_HOME=/opt/hadoop
export HADOOP_CONF_DIR=/opt/hadoop/etc/hadoop
export HIVE_HOME=/opt/hive
export HBASE_HOME=/opt/hbase
export ZK_HOME=/opt/zookeeper
export TEZ_HOME=/opt/tez
export PATH=$PATH:$JAVA_HOME/bin:$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$HIVE_HOME/bin:$HBASE_HOME/bin:$ZK_HOME/bin
EOF

# ============================================================
# 3. Create data directories (match Dockerfile)
# ============================================================
echo "[3/10] Creating data directories..."
mkdir -p $DATA_DIR/hadoop/hdfs/name $DATA_DIR/hadoop/hdfs/data \
         $DATA_DIR/hadoop/pids $DATA_DIR/hadoop/yarn \
         $DATA_DIR/zookeeper $LOG_DIR

echo "1" > $DATA_DIR/zookeeper/myid

# ============================================================
# 4. Generate config files (single-node no HA, params match Docker)
# ============================================================
echo "[4/10] Generating config files..."

HADOOP_CONF=$HADOOP_CONF_DIR

# --- hadoop-env.sh ---
# Note: do not hardcode JAVA_HOME (would override Hive's Java 21)
# supervisord program environment= already sets correct JAVA_HOME
cat > $HADOOP_CONF/hadoop-env.sh << 'ENV'
# JAVA_HOME is set by caller (supervisord environment= or /etc/profile.d/hadoop.sh)
# Do not export JAVA_HOME here, to avoid overriding Hive's Java 21
export HADOOP_HOME=/opt/hadoop
export HADOOP_CONF_DIR=/opt/hadoop/etc/hadoop
export HADOOP_HEAPSIZE_MAX=512
export HADOOP_PID_DIR=/data/hadoop/pids
ENV

# --- core-site.xml ---
cat > $HADOOP_CONF/core-site.xml << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <property><name>fs.defaultFS</name><value>hdfs://localhost:9000</value></property>
  <property><name>hadoop.tmp.dir</name><value>/data/hadoop</value></property>
  <property><name>hadoop.http.staticuser.user</name><value>root</value></property>
</configuration>
XML

# --- hdfs-site.xml (single NN, no HA, no JN) ---
cat > $HADOOP_CONF/hdfs-site.xml << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <property><name>dfs.namenode.name.dir</name><value>file:///data/hadoop/hdfs/name</value></property>
  <property><name>dfs.datanode.data.dir</name><value>file:///data/hadoop/hdfs/data</value></property>
  <property><name>dfs.replication</name><value>1</value></property>
  <property><name>dfs.permissions.enabled</name><value>false</value></property>
  <property><name>dfs.webhdfs.enabled</name><value>true</value></property>
  <property><name>dfs.namenode.http-address</name><value>0.0.0.0:9870</value></property>
</configuration>
XML

# --- yarn-site.xml (single RM, no HA, other params match Docker) ---
cat > $HADOOP_CONF/yarn-site.xml << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <property><name>yarn.resourcemanager.hostname</name><value>localhost</value></property>
  <property><name>yarn.nodemanager.aux-services</name><value>mapreduce_shuffle</value></property>
  <property><name>yarn.nodemanager.vmem-check-enabled</name><value>false</value></property>
  <property><name>yarn.nodemanager.pmem-check-enabled</name><value>false</value></property>
  <property><name>yarn.nodemanager.resource.memory-mb</name><value>4096</value></property>
  <property><name>yarn.nodemanager.delete.debug-delay-sec</name><value>600</value></property>
  <property><name>yarn.log-aggregation-enable</name><value>true</value></property>
  <property><name>yarn.nodemanager.remote-app-log-dir</name><value>/tmp/logs</value></property>
  <property><name>yarn.log-aggregation.retain-seconds</name><value>86400</value></property>
</configuration>
XML

# --- mapred-site.xml (matches Docker: JDK 21 add-opens for Hive on Tez) ---
cat > $HADOOP_CONF/mapred-site.xml << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <property><name>mapreduce.framework.name</name><value>yarn</value></property>
  <property><name>mapreduce.jobhistory.address</name><value>localhost:10020</value></property>
  <property><name>mapreduce.jobhistory.webapp.address</name><value>localhost:19888</value></property>
  <property><name>yarn.app.mapreduce.am.env</name><value>HADOOP_MAPRED_HOME=/opt/hadoop,JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64</value></property>
  <property><name>mapreduce.map.env</name><value>HADOOP_MAPRED_HOME=/opt/hadoop,JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64</value></property>
  <property><name>mapreduce.reduce.env</name><value>HADOOP_MAPRED_HOME=/opt/hadoop,JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64</value></property>
  <property><name>yarn.app.mapreduce.am.command-opts</name><value>-Xmx512m --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/sun.nio.ch=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED</value></property>
  <property><name>mapreduce.map.java.opts</name><value>-Xmx512m --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/sun.nio.ch=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED</value></property>
  <property><name>mapreduce.reduce.java.opts</name><value>-Xmx512m --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/sun.nio.ch=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED</value></property>
  <property><name>yarn.app.mapreduce.am.resource.mb</name><value>512</value></property>
  <property><name>mapreduce.map.memory.mb</name><value>512</value></property>
  <property><name>mapreduce.reduce.memory.mb</name><value>512</value></property>
</configuration>
XML

# --- workers ---
echo "localhost" > $HADOOP_CONF/workers

# --- Copy Docker config files (no modification needed) ---
# Note: project files may be edited on Windows, need CRLF removal
cp "$PROJ_DIR/deploy/config/hadoop/capacity-scheduler.xml" $HADOOP_CONF/
cp "$PROJ_DIR/deploy/config/hadoop/hadoop-metrics2.properties" $HADOOP_CONF/
cp "$PROJ_DIR/deploy/config/hadoop/log4j.properties" $HADOOP_CONF/
sed -i 's/\r$//' $HADOOP_CONF/capacity-scheduler.xml $HADOOP_CONF/hadoop-metrics2.properties $HADOOP_CONF/log4j.properties

# --- zoo.cfg (single-node, admin.serverPort=9888 to avoid conflict with YARN RM 8080) ---
cat > /opt/zookeeper/conf/zoo.cfg << 'CFG'
tickTime=2000
initLimit=10
syncLimit=5
dataDir=/data/zookeeper
clientPort=2181
admin.serverPort=9888
server.1=localhost:2888:3888
CFG

# --- hbase-site.xml (single-node, distributed=true to separate HMaster/RS) ---
cat > /opt/hbase/conf/hbase-site.xml << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <property><name>hbase.rootdir</name><value>hdfs://localhost:9000/hbase</value></property>
  <property><name>hbase.cluster.distributed</name><value>true</value></property>
  <property><name>hbase.zookeeper.quorum</name><value>localhost</value></property>
  <property><name>hbase.zookeeper.property.dataDir</name><value>/data/zookeeper</value></property>
  <property><name>hbase.security.authentication</name><value>simple</value></property>
  <property><name>hbase.security.authorization</name><value>false</value></property>
  <property><name>hbase.unsafe.stream.capability.enforce</name><value>false</value></property>
  <property><name>hbase.wal.provider</name><value>filesystem</value></property>
</configuration>
XML

# --- hbase-env.sh (matches Docker) ---
cp "$PROJ_DIR/deploy/config/hbase/hbase-env.sh" /opt/hbase/conf/hbase-env.sh
sed -i 's/\r$//' /opt/hbase/conf/hbase-env.sh

# --- hive-site.xml (single-node: MySQL localhost, single HMS) ---
cat > /opt/hive/conf/hive-site.xml << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <property><name>hive.metastore.uris</name><value>thrift://localhost:9083</value></property>
  <property><name>hive.metastore.warehouse.dir</name><value>hdfs://localhost:9000/user/hive/warehouse</value></property>
  <property><name>javax.jdo.option.ConnectionURL</name><value>jdbc:mysql://localhost:3306/metastore?createDatabaseIfNotExist=true</value></property>
  <property><name>javax.jdo.option.ConnectionDriverName</name><value>com.mysql.cj.jdbc.Driver</value></property>
  <property><name>javax.jdo.option.ConnectionUserName</name><value>hive</value></property>
  <property><name>javax.jdo.option.ConnectionPassword</name><value>hivepass</value></property>
  <property><name>hive.server2.thrift.port</name><value>10000</value></property>
  <property><name>hive.server2.thrift.bind.host</name><value>0.0.0.0</value></property>
  <property><name>hive.server2.enable.doAs</name><value>false</value></property>
  <property><name>hive.execution.engine</name><value>tez</value></property>
  <property><name>hive.metastore.sasl.enabled</name><value>false</value></property>
  <property><name>hive.metastore.event.db.notification.api.auth</name><value>false</value></property>
</configuration>
XML

# --- hive-env.sh (matches Docker: JDK 21 + --enable-preview) ---
cp "$PROJ_DIR/deploy/config/hive/hive-env.sh" /opt/hive/conf/hive-env.sh
sed -i 's/\r$//' /opt/hive/conf/hive-env.sh

# --- tez-site.xml (single-node: tez.lib.uris changed to localhost) ---
cat > /opt/tez/conf/tez-site.xml << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <property><name>tez.lib.uris</name><value>hdfs://localhost:9000/tez/tez.tar.gz</value></property>
  <property><name>tez.use.cluster.hadoop-libs</name><value>true</value></property>
  <property><name>tez.am.resource.memory.mb</name><value>256</value></property>
  <property><name>tez.am.launch.env</name><value>JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64,LD_LIBRARY_PATH=/opt/hadoop/lib/native</value></property>
  <property><name>tez.task.launch.env</name><value>JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64,LD_LIBRARY_PATH=/opt/hadoop/lib/native</value></property>
  <property><name>tez.am.java.opts</name><value>--add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED --add-opens=java.base/java.net=ALL-UNNAMED --add-opens=java.base/java.io=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.util.concurrent=ALL-UNNAMED -Djava.net.preferIPv4Stack=true</value></property>
  <property><name>tez.task.java.opts</name><value>--add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED --add-opens=java.base/java.net=ALL-UNNAMED --add-opens=java.base/java.io=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.util.concurrent=ALL-UNNAMED -Djava.net.preferIPv4Stack=true</value></property>
</configuration>
XML

echo "  Config files generated"

# ============================================================
# 5. MySQL setup (Hive Metastore backend, matches Docker MySQL container)
# ============================================================
echo "[5/10] MySQL setup..."
service mysql start 2>/dev/null || true
sleep 3

mysql -u root << 'SQL'
CREATE DATABASE IF NOT EXISTS metastore;
CREATE USER IF NOT EXISTS 'hive'@'localhost' IDENTIFIED BY 'hivepass';
GRANT ALL PRIVILEGES ON metastore.* TO 'hive'@'localhost';
FLUSH PRIVILEGES;
SQL
echo "  MySQL: metastore DB + hive user created"

# ============================================================
# 6. SSH setup (single sshd on port 22, no Docker port mapping needed)
# ============================================================
echo "[6/10] SSH setup..."
SSH_DIR="/root/.ssh"
mkdir -p $SSH_DIR /run/sshd
chmod 700 $SSH_DIR

# Copy project SSH keys (matches Docker mount)
if [ -f "$PROJ_DIR/deploy/config/ssh/id_rsa" ]; then
  # Fix source key permissions first (Git checkout leaves 0644, SSH needs 0600)
  chmod 600 "$PROJ_DIR/deploy/config/ssh/id_rsa"
  cp "$PROJ_DIR/deploy/config/ssh/id_rsa" $SSH_DIR/id_rsa
  cp "$PROJ_DIR/deploy/config/ssh/id_rsa.pub" $SSH_DIR/id_rsa.pub
  cp "$PROJ_DIR/deploy/config/ssh/authorized_keys" $SSH_DIR/authorized_keys
  # Fix Windows CRLF line endings
  sed -i 's/\r$//' $SSH_DIR/id_rsa $SSH_DIR/id_rsa.pub $SSH_DIR/authorized_keys
  chmod 600 $SSH_DIR/id_rsa $SSH_DIR/authorized_keys
  chmod 644 $SSH_DIR/id_rsa.pub
else
  # Generate new keys
  if [ ! -f $SSH_DIR/id_rsa ]; then
    ssh-keygen -t rsa -N "" -f $SSH_DIR/id_rsa
  fi
  cat $SSH_DIR/id_rsa.pub >> $SSH_DIR/authorized_keys
  chmod 600 $SSH_DIR/id_rsa $SSH_DIR/authorized_keys
fi

# sshd config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config

# Generate host keys
ssh-keygen -A 2>/dev/null || true

# Single-node: only need 1 sshd on port 22 (no Docker port mapping)
/usr/sbin/sshd 2>/dev/null || true
echo "  sshd: 22"

# ============================================================
# 7. supervisord config (matches Docker hadoop01, autorestart=false)
# ============================================================
echo "[7/10] supervisord config..."
mkdir -p $SUPERVISOR_CONF

# Clean up residual PID files (matches entrypoint.sh)
rm -f /opt/hive/conf/hiveserver2.pid /opt/hive/conf/hivemetastore.pid 2>/dev/null || true
rm -f /tmp/hadoop-root-*.pid 2>/dev/null || true

cat > $SUPERVISOR_CONF/supervisord-hadoop01.conf << 'SUP'
; Single-node supervisord config — all daemons (no HA: no ZKFC/JournalNode)
; JMX Exporter ports match Docker:
;   ZK=10109, NN=10101, DN=10102, RM=10104, NM=10105, JHS=10106
;   HMS=10110, HS2=10111, HM=10107, RS=10108
[supervisord]
nodaemon=false
user=root
logfile=/logs/supervisord.log
pidfile=/tmp/supervisord.pid
; Global environment variables (Docker uses ENV, direct install sets in supervisord)
environment=HADOOP_HOME="/opt/hadoop",HADOOP_CONF_DIR="/opt/hadoop/etc/hadoop",HIVE_HOME="/opt/hive",HBASE_HOME="/opt/hbase",ZK_HOME="/opt/zookeeper",TEZ_HOME="/opt/tez",HBASE_CONF_DIR="/opt/hbase/conf"

[unix_http_server]
file=/tmp/supervisor.sock

[supervisorctl]
serverurl=unix:///tmp/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[program:zookeeper]
command=/opt/zookeeper/bin/zkServer.sh start-foreground
environment=SERVER_JVMFLAGS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10109:/opt/jmx-exporter/config.yml"
autostart=true ; autorestart=false ; startsecs=3  ; priority=10
stdout_logfile=/logs/zk.log
redirect_stderr=true

[program:datanode]
command=/opt/hadoop/bin/hdfs datanode
environment=HADOOP_DATANODE_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10102:/opt/jmx-exporter/config.yml",JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64",HADOOP_HEAPSIZE_MAX="256"
autostart=true ; autorestart=false ; startsecs=3  ; priority=30
stdout_logfile=/logs/dn.log
redirect_stderr=true

[program:nodemanager]
command=/opt/hadoop/bin/yarn nodemanager
environment=YARN_NODEMANAGER_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10105:/opt/jmx-exporter/config.yml",JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
autostart=true ; autorestart=false ; startsecs=3  ; priority=40
stdout_logfile=/logs/nm.log
redirect_stderr=true

[program:namenode]
command=/opt/hadoop/bin/hdfs namenode
environment=HADOOP_NAMENODE_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10101:/opt/jmx-exporter/config.yml",JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64",HADOOP_HEAPSIZE_MAX="512"
autostart=true ; autorestart=false ; startsecs=10 ; priority=50
stdout_logfile=/logs/nn.log
redirect_stderr=true

[program:resourcemanager]
command=/opt/hadoop/bin/yarn resourcemanager
environment=YARN_RESOURCEMANAGER_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10104:/opt/jmx-exporter/config.yml",JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64",HADOOP_HEAPSIZE_MAX="512"
autostart=true ; autorestart=false ; startsecs=10 ; priority=60
stdout_logfile=/logs/rm.log
redirect_stderr=true

[program:historyserver]
command=/opt/hadoop/bin/mapred historyserver
environment=HADOOP_JOB_HISTORYSERVER_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10106:/opt/jmx-exporter/config.yml",JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
autostart=true ; autorestart=false ; startsecs=3  ; priority=70
stdout_logfile=/logs/jhs.log
redirect_stderr=true

; ---- Hive (JDK 21, autostart=false, manually start after HDFS ready) ----
[program:hivemetastore]
command=/opt/hive/bin/hive --service metastore
environment=HADOOP_HEAPSIZE="256",JAVA_HOME="/usr/lib/jvm/java-21-openjdk-amd64",HADOOP_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10110:/opt/jmx-exporter/config.yml"
autostart=false ; autorestart=false ; startsecs=10 ; priority=80
stdout_logfile=/logs/hms.log
redirect_stderr=true

[program:hiveserver2]
command=/opt/hive/bin/hiveserver2
environment=HADOOP_HEAPSIZE="256",JAVA_HOME="/usr/lib/jvm/java-21-openjdk-amd64",HADOOP_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10111:/opt/jmx-exporter/config.yml"
autostart=false ; autorestart=false ; startsecs=10 ; priority=90
stdout_logfile=/logs/hs2.log
redirect_stderr=true

; ---- HBase (JDK 8, matches Docker) ----
[program:hmaster]
command=/opt/hbase/bin/hbase master start
environment=HBASE_MASTER_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10107:/opt/jmx-exporter/config.yml",HBASE_HEAPSIZE="256",JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
autostart=true ; autorestart=false ; startsecs=10 ; priority=100
stdout_logfile=/logs/hm.log
redirect_stderr=true

[program:regionserver]
command=/opt/hbase/bin/hbase regionserver start
environment=HBASE_REGIONSERVER_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10108:/opt/jmx-exporter/config.yml",HBASE_HEAPSIZE="256",JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
autostart=true ; autorestart=false ; startsecs=10 ; priority=110
stdout_logfile=/logs/rs.log
redirect_stderr=true

; ---- Prometheus ----
[program:prometheus]
command=/opt/prometheus/prometheus --config.file=/opt/prometheus/prometheus.yml --storage.tsdb.path=/data/prometheus
autostart=true ; autorestart=true ; startsecs=3 ; priority=120
stdout_logfile=/logs/prometheus.log
redirect_stderr=true

; ---- Grafana (after RPM install, path /usr/share/grafana) ----
[program:grafana]
command=/usr/share/grafana/bin/grafana server --config=/usr/share/grafana/conf/custom.ini --homepath=/usr/share/grafana
autostart=true ; autorestart=true ; startsecs=3 ; priority=130
stdout_logfile=/logs/grafana.log
redirect_stderr=true

; ---- Alertmanager ----
[program:alertmanager]
command=/opt/alertmanager/alertmanager --config.file=/opt/alertmanager/alertmanager.yml --storage.path=/data/alertmanager
autostart=true ; autorestart=true ; startsecs=3 ; priority=140
stdout_logfile=/logs/alertmanager.log
redirect_stderr=true
SUP

# Single-node: no hadoop02/03 symlinks needed (CLUSTER_NODES only has hadoop01)
echo "  supervisord config generated"

# ============================================================
# 8. Install monitoring components (Prometheus + Grafana + Alertmanager)
# ============================================================
echo "[8/10] Installing monitoring (Prometheus + Grafana + Alertmanager)..."

# Generic download function: prefer remote server, fallback to official source
download_file() {
  local filename="$1" official_url="$2"
  if [ -f "$TARBALLS_DIR/$filename" ]; then
    echo "  $filename already exists, skipping"
    return 0
  fi
  echo "  Downloading $filename ..."
  if curl -sf --connect-timeout 10 --retry 3 "$REMOTE_URL/$filename" -o "$TARBALLS_DIR/$filename" 2>/dev/null; then
    echo "    Downloaded from remote server"
  else
    echo "    Remote unavailable, falling back to official source ..."
    curl -fkL --retry 3 -o "$TARBALLS_DIR/$filename" "$official_url"
  fi
}

# --- Prometheus ---
PROM_DIR="/opt/prometheus"
PROM_FILE="prometheus-3.11.2.linux-amd64.tar.gz"
if [ ! -x "$PROM_DIR/prometheus" ]; then
  download_file "$PROM_FILE" \
    "https://github.com/prometheus/prometheus/releases/download/v3.11.2/${PROM_FILE}"
  tar -xzf "$TARBALLS_DIR/$PROM_FILE" -C /opt/
  mv "/opt/prometheus-3.11.2.linux-amd64" "$PROM_DIR"
fi
mkdir -p /data/prometheus

# Prometheus config (single-node: all JMX ports on localhost)
cat > $PROM_DIR/prometheus.yml << 'YML'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'hdfs-namenode'
    static_configs:
      - targets: ['localhost:10101']
        labels: { component: 'namenode' }
  - job_name: 'hdfs-datanode'
    static_configs:
      - targets: ['localhost:10102']
        labels: { component: 'datanode' }
  - job_name: 'yarn-resourcemanager'
    static_configs:
      - targets: ['localhost:10104']
        labels: { component: 'resourcemanager' }
  - job_name: 'yarn-nodemanager'
    static_configs:
      - targets: ['localhost:10105']
        labels: { component: 'nodemanager' }
  - job_name: 'yarn-historyserver'
    static_configs:
      - targets: ['localhost:10106']
        labels: { component: 'historyserver' }
  - job_name: 'hbase-master'
    static_configs:
      - targets: ['localhost:10107']
        labels: { component: 'hmaster' }
  - job_name: 'hbase-regionserver'
    static_configs:
      - targets: ['localhost:10108']
        labels: { component: 'regionserver' }
  - job_name: 'zookeeper'
    static_configs:
      - targets: ['localhost:10109']
        labels: { component: 'zookeeper' }
  - job_name: 'hive-metastore'
    static_configs:
      - targets: ['localhost:10110']
        labels: { component: 'hivemetastore' }
  - job_name: 'hive-server2'
    static_configs:
      - targets: ['localhost:10111']
        labels: { component: 'hiveserver2' }
YML
echo "  Prometheus: OK"

# --- Grafana (deb package, install via dpkg) ---
GRAFANA_FILE="grafana_13.1.1_29761037902_linux_amd64.deb"
if [ ! -x /usr/share/grafana/bin/grafana ] && [ ! -x /opt/grafana/bin/grafana ]; then
  download_file "$GRAFANA_FILE" \
    "https://dl.grafana.com/oss/release/${GRAFANA_FILE}"
  dpkg -i "$TARBALLS_DIR/$GRAFANA_FILE" 2>&1 | tail -5
fi
GRAFANA_DIR="$(ls -d /usr/share/grafana 2>/dev/null || echo /opt/grafana)"
mkdir -p /data/grafana $GRAFANA_DIR/conf/provisioning/datasources $GRAFANA_DIR/conf/provisioning/dashboards

# Grafana datasource (Prometheus)
cat > $GRAFANA_DIR/conf/provisioning/datasources/prometheus.yml << 'YML'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://localhost:9090
    isDefault: true
YML

# Grafana config
cat > $GRAFANA_DIR/conf/custom.ini << 'INI'
[paths]
data = /data/grafana
[server]
http_addr = 0.0.0.0
http_port = 3000
[security]
admin_user = admin
admin_password = admin
INI
echo "  Grafana: OK"

# --- Alertmanager ---
AM_DIR="/opt/alertmanager"
AM_FILE="alertmanager-0.33.1.linux-amd64.tar.gz"
if [ ! -x "$AM_DIR/alertmanager" ]; then
  download_file "$AM_FILE" \
    "https://github.com/prometheus/alertmanager/releases/download/v0.33.1/${AM_FILE}"
  tar -xzf "$TARBALLS_DIR/$AM_FILE" -C /opt/
  mv "/opt/alertmanager-0.33.1.linux-amd64" "$AM_DIR"
fi
mkdir -p /data/alertmanager

# Alertmanager config (empty config, no alerts sent)
cat > $AM_DIR/alertmanager.yml << 'YML'
global:
  resolve_timeout: 5m
route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'default'
receivers:
  - name: 'default'
YML
echo "  Alertmanager: OK"

# ============================================================
# 9. Format HDFS + start + initialize Hive
# ============================================================
echo "[9/10] Format HDFS + start..."

# Stop old supervisord first (if any)
$SUPCTL shutdown >/dev/null 2>&1 || true
pkill -f supervisord 2>/dev/null || true
sleep 2

# Format HDFS (format before starting NN, avoid conflict)
if [ ! -d $DATA_DIR/hadoop/hdfs/name/current ]; then
  echo "  Formatting HDFS..."
  # Clean old data directory (ensure clean format)
  rm -rf $DATA_DIR/hadoop/hdfs/name/* $DATA_DIR/hadoop/hdfs/data/*
  $HADOOP_HOME/bin/hdfs namenode -format -force -nonInteractive 2>&1 | tail -5
fi

# Start supervisord (ZK, DN, NN, RM, NM, JHS, HM, RS, Prometheus)
supervisord -c $SUPERVISOR_CONF/supervisord-hadoop01.conf
sleep 5

# Wait for ZK to be ready
for i in $(seq 1 15); do
  if nc -z localhost 2181 2>/dev/null; then echo "  ZK ready"; break; fi
  sleep 1
done

# Wait for HDFS to be ready
  echo "  Waiting for HDFS..."
for i in $(seq 1 30); do
  if $HADOOP_HOME/bin/hdfs dfsadmin -report >/dev/null 2>&1; then
    echo "  HDFS ready"
    break
  fi
  sleep 2
done

# Upload Tez tarball to HDFS (referenced by tez-site.xml)
echo "  Uploading Tez tarball to HDFS..."
$HADOOP_HOME/bin/hdfs dfs -mkdir -p /tez 2>/dev/null || true
$HADOOP_HOME/bin/hdfs dfs -put -f /opt/tez/share/tez.tar.gz /tez/ 2>/dev/null || true

# Create Hive warehouse directories
$HADOOP_HOME/bin/hdfs dfs -mkdir -p /user/hive/warehouse /tmp 2>/dev/null || true
$HADOOP_HOME/bin/hdfs dfs -chmod g+w /tmp 2>/dev/null || true

# Initialize Hive Metastore schema (schematool uses JDK 21 via hive-env.sh)
echo "  Initializing Hive Metastore schema..."
$HIVE_HOME/bin/schematool -dbType mysql -initSchema 2>&1 | tail -5 || echo "  [INFO] schema may already be initialized"

# Start Hive services
$SUPCTL start hivemetastore 2>/dev/null || true
$SUPCTL start hiveserver2 2>/dev/null || true

echo ""
echo "=== Service status ==="
sleep 5
  $SUPCTL status 2>/dev/null || echo "  supervisord not running"

# ============================================================
# 10. Verify
# ============================================================
echo "[10/10] Verify..."
sleep 10

echo "=== HDFS ==="
$HADOOP_HOME/bin/hdfs dfsadmin -report 2>/dev/null | head -10 || echo "  HDFS not ready yet"

echo ""
echo "=== SSH ports ==="
# Dynamically detect SSH listening ports (single-node: port 22 only)
if command -v ss >/dev/null 2>&1; then
  DETECTED_SSH_PORTS=$(ss -tlnp 2>/dev/null | grep sshd | awk '{print $4}' | awk -F: '{print $NF}' | sort -un)
elif command -v netstat >/dev/null 2>&1; then
  DETECTED_SSH_PORTS=$(netstat -tlnp 2>/dev/null | grep sshd | awk '{print $4}' | awk -F: '{print $NF}' | sort -un)
fi
DETECTED_SSH_PORTS=${DETECTED_SSH_PORTS:-22}
for p in $DETECTED_SSH_PORTS; do
  nc -z localhost $p 2>/dev/null && echo "  port $p: OK" || echo "  port $p: FAIL"
done

echo ""
echo "=== JMX Exporter ports ==="
for pair in "10101:NameNode" "10102:DataNode" "10104:ResourceManager" "10105:NodeManager" "10106:HistoryServer" "10107:HMaster" "10108:RegionServer" "10109:ZooKeeper" "10110:HiveMetaStore" "10111:HiveServer2"; do
  port="${pair%%:*}"
  name="${pair##*:}"
  nc -z localhost $port 2>/dev/null && echo "  $name ($port): OK" || echo "  $name ($port): FAIL"
done

# ============================================================
# Run unified health check script (Docker / direct install dual-mode compatible)
# ============================================================
echo ""
echo "=== Unified health check (healthcheck.sh) ==="
if [ -f "$PROJ_DIR/scripts/healthcheck.sh" ]; then
  sed -i 's/\r$//' "$PROJ_DIR/scripts/healthcheck.sh"
  chmod +x "$PROJ_DIR/scripts/healthcheck.sh"
  bash "$PROJ_DIR/scripts/healthcheck.sh" || true
else
  echo "  [INFO] healthcheck.sh not found, skipping unified health check"
fi

echo ""
echo "===== Complete ====="
echo "  NameNode UI:    http://localhost:9870"
echo "  YARN UI:        http://localhost:8088"
echo "  HBase UI:       http://localhost:16010"
echo "  Prometheus:     http://localhost:9090"
echo "  Grafana:        http://localhost:3000 (admin/admin)"
echo "  Alertmanager:   http://localhost:9093"
echo "  SSH:            localhost:22"
echo "  supervisorctl status  to view service status"
