# hbase-env.sh - HBase 2.5.15 on Java 8 环境配置
#
# 注意：HBase 2.5.x 官方只支持 Java 8/11，回退到 Java 8 确保稳定运行
# 通过 docker-compose 挂载到 /opt/hbase/conf/hbase-env.sh

# 使用 Java 8 (HBase 2.5.x 官方支持)
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH

# Java 8 基础选项
export HBASE_OPTS="-Djava.net.preferIPv4Stack=true"

# JMX Exporter Java Agent (Prometheus metrics)
JMX_AGENT="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar"

# HBase Master / RegionServer 额外选项
export HBASE_MASTER_OPTS="$HBASE_OPTS -XX:+UseG1GC -XX:MaxGCPauseMillis=200 ${JMX_AGENT}=10107:/opt/jmx-exporter/config.yml"
export HBASE_REGIONSERVER_OPTS="$HBASE_OPTS -XX:+UseG1GC -XX:MaxGCPauseMillis=200 -Xmx2g ${JMX_AGENT}=10108:/opt/jmx-exporter/config.yml"

# HBase 日志目录
export HBASE_LOG_DIR=/var/log/hbase

# 使用集群的 ZooKeeper
export HBASE_MANAGES_ZK=false
