#!/bin/bash
# hbase-wrapper.sh - 使用 Java 8 的 HBase 启动脚本
# 挂载到 /usr/local/bin/hbase，覆盖默认的 hbase 命令
# HBase 2.5.x 官方只支持 Java 8/11

# 使用 Java 8
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH

# 调用原始的 hbase 脚本
exec /opt/hbase/bin/hbase "$@"
