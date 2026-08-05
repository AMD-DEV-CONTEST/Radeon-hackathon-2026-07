p = '/workspace/Radeon-hackathon-2026-07/scripts/inject-fault.sh'
lines = open(p).readlines()
new_lines = []
for line in lines:
    if 'Djline' in line and 'exec /opt/hadoop' in line:
        new_lines.append('export HADOOP_CLIENT_OPTS="-Djline.terminal=dumb -Djline.terminal.jansi=false"\n')
        new_lines.append('exec /opt/hadoop/bin/hadoop jar ${HIVE_HOME}/lib/hive-beeline-*.jar org.apache.hive.beeline.BeeLine --color=false "$@"\n')
    else:
        new_lines.append(line)
open(p, 'w').writelines(new_lines)
print('FIXED')
