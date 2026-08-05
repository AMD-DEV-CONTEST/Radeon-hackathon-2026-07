#!/bin/bash
# beeline.sh - 修复 Java 8/21 兼容性
# 替换 /opt/hive/bin/ext/beeline.sh

# Need arguments [host [port [db]]]
THISSERVICE=beeline
export SERVICE_LIST="${SERVICE_LIST}${THISSERVICE} "

beeline () {
  CLASS=org.apache.hive.beeline.BeeLine;

  beelineJarPath=`ls ${HIVE_LIB}/hive-beeline-*.jar`
  superCsvJarPath=`ls ${HIVE_LIB}/super-csv-*.jar`
  jlineJarPath=`ls ${HIVE_LIB}/jline-*.jar`
  hadoopClasspath=""
  if [[ -n "${HADOOP_CLASSPATH}" ]]
  then
    hadoopClasspath="${HADOOP_CLASSPATH}:"
  fi
  export HADOOP_CLASSPATH="${hadoopClasspath}${HIVE_CONF_DIR}:${beelineJarPath}:${superCsvJarPath}:${jlineJarPath}"

  # 强制使用 Java 21（Hive 4.2.0 必须用 Java 21 运行）
  export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
  export PATH=$JAVA_HOME/bin:$PATH
  
  # Java 21 需要的 --enable-preview (JLine FFM terminal) + --add-opens 选项
  # 直接追加到 HADOOP_OPTS (确保 hadoop jar 能拾取)
  export HADOOP_OPTS="$HADOOP_OPTS --enable-preview --enable-native-access=ALL-UNNAMED"
  export HADOOP_CLIENT_OPTS="$HADOOP_CLIENT_OPTS -Dlog4j.configurationFile=beeline-log4j2.properties --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED  --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED "

  if [ "$EXECUTE_WITH_JAVA" != "true" ] ; then
    # if CLIUSER is not empty, then pass it as user id / password during beeline redirect
    if [ -z $CLIUSER ] ; then
      exec $HADOOP jar ${beelineJarPath} $CLASS $HIVE_OPTS "$@"
    else
      exec $HADOOP jar ${beelineJarPath} $CLASS $HIVE_OPTS "$@" -n "${CLIUSER}" -p "${CLIUSER}"
    fi
  else
    # if CLIUSER is not empty, then pass it as user id / password during beeline redirect
    if [ -z $CLIUSER ] ; then
      $JAVAEXE -cp ${HADOOP_CLASSPATH} $CLASS $HIVE_OPTS "$@"
    else
      $JAVAEXE -cp ${HADOOP_CLASSPATH} $CLASS $HIVE_OPTS "$@" -n "${CLIUSER}" -p "${CLIUSER}"
    fi
  fi
}

beeline_help () {
  beeline "--help"
}
