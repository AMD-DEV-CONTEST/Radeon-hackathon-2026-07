#!/bin/bash
# Test beeline wrapper on remote container
SSH_KEY=/workspace/Radeon-hackathon-2026-07/deploy/config/ssh/id_rsa
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i $SSH_KEY"

# Create beeline wrapper on hadoop01
ssh $SSH_OPTS -p 2222 root@8.148.228.51 'cat > /tmp/beeline_direct.sh << "WRAPPER"
#!/bin/bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export HADOOP_HOME=/opt/hadoop
export HIVE_HOME=/opt/hive
export HADOOP_CLASSPATH="${HIVE_HOME}/conf:${HIVE_HOME}/lib/*"
export HADOOP_OPTS="--enable-preview --enable-native-access=ALL-UNNAMED --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED"
export HADOOP_CLIENT_OPTS="-Djline.terminal=dumb -Djline.terminal.jansi=false"
export TERM=dumb
exec /opt/hadoop/bin/hadoop jar ${HIVE_HOME}/lib/hive-beeline-*.jar org.apache.hive.beeline.BeeLine --color=false "$@"
WRAPPER
chmod +x /tmp/beeline_direct.sh'

# Test: SHOW DATABASES
echo "=== Testing beeline wrapper ==="
ssh $SSH_OPTS -p 2222 root@8.148.228.51 '/tmp/beeline_direct.sh -u jdbc:hive2://localhost:10000 -n root -e "SHOW DATABASES" 2>&1 | tail -20'
