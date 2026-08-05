# =============================================================================
# 自建镜像: Apache Hadoop 3.3.6 + Hive 4.2.0 + Tez 0.10.2 + HBase 2.5.15
#           + ZooKeeper 3.8.4 + supervisord + krb5-client
# 一镜像多角色: NODE_ROLE 决定跑哪些 daemon (supervisord 选对应配置)
# 双 JDK: JDK 8 (Hadoop/HBase/ZK) + JDK 21 (Hive 4.2.0)
# Phase 1: 无 Kerberos; Phase 2: 加 Kerberos (krb5-client 已预装)
# =============================================================================
FROM ubuntu:22.04

ARG HADOOP_VERSION=3.3.6
ARG HIVE_VERSION=4.2.0
ARG TEZ_VERSION=0.10.2
ARG HBASE_VERSION=2.5.15
ARG ZK_VERSION=3.8.4
ARG MYSQL_CONN_VERSION=8.0.30

ENV DEBIAN_FRONTEND=noninteractive

# ---- 系统依赖 ----
RUN apt-get update && apt-get install -y --no-install-recommends \
      openjdk-8-jdk-headless supervisor netcat-openbsd dnsutils \
      curl wget ca-certificates python3 krb5-user libsnappy-dev \
      openssh-client openssh-server bash \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd

# ---- JDK 21 (Hive 4.2.0 需要 Java 21, 离线 COPY 免网络) ----
COPY tarballs/openlogic-openjdk-21.0.11+10-linux-x64.tar.gz /tmp/jdk21.tgz
RUN tar -xzf /tmp/jdk21.tgz -C /usr/lib/jvm/ \
    && mv /usr/lib/jvm/openlogic-openjdk-21.0.11+10-linux-x64 /usr/lib/jvm/java-21-openjdk-amd64 \
    && rm /tmp/jdk21.tgz

ENV JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
ENV JAVA_HOME_8=/usr/lib/jvm/java-8-openjdk-amd64
ENV JAVA_HOME_21=/usr/lib/jvm/java-21-openjdk-amd64
ENV HADOOP_HOME=/opt/hadoop
ENV HADOOP_CONF_DIR=/opt/hadoop/etc/hadoop
ENV HIVE_HOME=/opt/hive
ENV TEZ_HOME=/opt/tez
ENV HBASE_HOME=/opt/hbase
ENV ZK_HOME=/opt/zookeeper
ENV PATH=$PATH:$JAVA_HOME/bin:$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$HIVE_HOME/bin:$HBASE_HOME/bin:$ZK_HOME/bin

# ---- 堆内存 (Step 1 保守值; 全集群 ~6GB 堆, 16GB WSL2 够) ----
ENV HADOOP_HEAPSIZE_MAX=512
ENV SERVER_JVMFLAGS="-Xms256m -Xmx256m"

# ---- Hadoop (从本地 tarballs/ 复制, 无需网络下载) ----
COPY tarballs/hadoop-${HADOOP_VERSION}.tar.gz /tmp/hadoop.tgz
RUN tar -xzf /tmp/hadoop.tgz -C /opt/ && mv /opt/hadoop-${HADOOP_VERSION} /opt/hadoop && rm /tmp/hadoop.tgz

COPY tarballs/apache-zookeeper-${ZK_VERSION}-bin.tar.gz /tmp/zk.tgz
RUN tar -xzf /tmp/zk.tgz -C /opt/ && mv /opt/apache-zookeeper-${ZK_VERSION}-bin /opt/zookeeper && rm /tmp/zk.tgz

COPY tarballs/apache-hive-${HIVE_VERSION}-bin.tar.gz /tmp/hive.tgz
RUN tar -xzf /tmp/hive.tgz -C /opt/ && mv /opt/apache-hive-${HIVE_VERSION}-bin /opt/hive && rm /tmp/hive.tgz

COPY tarballs/apache-tez-${TEZ_VERSION}-bin.tar.gz /tmp/tez.tgz
RUN tar -xzf /tmp/tez.tgz -C /opt/ && mv /opt/apache-tez-${TEZ_VERSION}-bin /opt/tez && rm /tmp/tez.tgz

COPY tarballs/hbase-${HBASE_VERSION}-bin.tar.gz /tmp/hbase.tgz
RUN tar -xzf /tmp/hbase.tgz -C /opt/ && mv /opt/hbase-${HBASE_VERSION} /opt/hbase && rm /tmp/hbase.tgz

# ---- MySQL Connector (Hive metastore, Step 2 用) ----
COPY tarballs/mysql-connector-java-${MYSQL_CONN_VERSION}.jar ${HIVE_HOME}/lib/mysql-connector-java.jar

# ---- Hive 与 Hadoop 的 guava 冲突对齐 (通用: 删 Hive 自带 guava, 用 Hadoop 的) ----
RUN rm -f ${HIVE_HOME}/lib/guava-*.jar \
    && cp ${HADOOP_HOME}/share/hadoop/hdfs/lib/guava-*.jar ${HIVE_HOME}/lib/

# ---- 数据/日志目录 ----
RUN mkdir -p /data/hadoop/hdfs/name /data/hadoop/hdfs/data /data/hadoop/hdfs/jn \
             /data/hadoop/yarn /data/zookeeper /logs

# ---- supervisord 配置 + entrypoint ----
COPY supervisord/ /etc/supervisor/conf.d/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
