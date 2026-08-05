# hive-env.sh - Hive 4.2.0 on Java 21 的 JVM flags + Tez 集成
#
# Hive 4.2.0 必须用 Java 21 运行（class file version 65.0）
# JLine 3.25.0 FfmTerminalProvider 用 Java 21 preview FFM API, 需开 preview + native-access
# TEZ_CONF_DIR 指向 tez-site.xml (否则 tez.lib.uris 读不到, 报 Invalid configuration of tez jars)
#
# 注意: --enable-preview 通过 HADOOP_OPTS 传递 (仅 hadoop/hive 启动脚本使用)
# 不能用 JAVA_TOOL_OPTIONS, 因为该变量会被所有 Java 进程拾取 (包括 Java 8 的进程检查)
# 同时跳过 hive 脚本内部的 hadoop version 检查 (该检查可能用 Java 8, 不支持 --enable-preview)

# 强制使用 Java 21
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH

# 跳过 hive 脚本的 hadoop version 检查 (避免 Java 8 进程拾取 --enable-preview)
export SKIP_HADOOPVERSION=true
export HADOOP_VERSION=3.3.6

# Java 21 需要的选项 — 追加到 HADOOP_OPTS (不影响 Java 8 进程检查)
if [[ "$HADOOP_OPTS" != *"--enable-preview"* ]]; then
  export HADOOP_OPTS="$HADOOP_OPTS --enable-preview --enable-native-access=ALL-UNNAMED"
fi
export TEZ_CONF_DIR=/opt/tez/conf
