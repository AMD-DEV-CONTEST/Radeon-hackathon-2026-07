#!/bin/bash
SSH_KEY=/workspace/Radeon-hackathon-2026-07/deploy/config/ssh/id_rsa
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i $SSH_KEY"

# Create beeline wrapper with -Djline.terminal=dumb passed directly as JVM arg
echo "=== Creating /tmp/beeline_fixed.sh ==="
ssh $SSH_OPTS -p 2222 root@8.148.228.51 'cat > /tmp/beeline_fixed.sh << "EOF"
#!/bin/bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export HADOOP_HOME=/opt/hadoop
export HIVE_HOME=/opt/hive
export HIVE_CONF_DIR=/opt/hive/conf
export HADOOP_CLASSPATH="${HIVE_CONF_DIR}:${HIVE_HOME}/lib/*"
export HADOOP_OPTS="-Djline.terminal=dumb -Djline.terminal.jansi=false --enable-preview --enable-native-access=ALL-UNNAMED --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED"
export TERM=dumb
BEELINE_JAR=$(ls ${HIVE_HOME}/lib/hive-beeline-*.jar)
exec ${HADOOP_HOME}/bin/hadoop jar ${BEELINE_JAR} org.apache.hive.beeline.BeeLine --color=false "$@"
EOF
chmod +x /tmp/beeline_fixed.sh && echo CREATED'

# Test beeline -f
echo "=== Testing beeline -f ==="
ssh $SSH_OPTS -p 2222 root@8.148.228.51 'echo "SHOW DATABASES;" > /tmp/test_beeline.sql && /tmp/beeline_fixed.sh -u jdbc:hive2://localhost:10000 -n root -f /tmp/test_beeline.sql 2>&1 | tail -20'
