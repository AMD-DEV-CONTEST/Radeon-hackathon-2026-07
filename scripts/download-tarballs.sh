#!/usr/bin/env bash
# download-tarballs.sh — Download tarballs needed for Hadoop cluster image build
#
# Usage: bash scripts/download-tarballs.sh
# Output: deploy/image/tarballs/ directory with 7 files (~2GB)
# Source: Prioritize 8.148.228.51 server (fast in China), fallback to Apache official
set -euo pipefail

TARBALLS_DIR="$(cd "$(dirname "$0")/.." && pwd)/deploy/image/tarballs"
mkdir -p "$TARBALLS_DIR"
cd "$TARBALLS_DIR"

# Remote server (preferred, fast in China)
REMOTE_URL="http://8.148.228.51/repo/tarballs"

# Apache official (fallback)
declare -A OFFICIAL=(
  ["hadoop-3.3.6.tar.gz"]="https://archive.apache.org/dist/hadoop/common/hadoop-3.3.6/hadoop-3.3.6.tar.gz"
  ["apache-hive-4.2.0-bin.tar.gz"]="https://archive.apache.org/dist/hive/hive-4.2.0/apache-hive-4.2.0-bin.tar.gz"
  ["apache-tez-0.10.2-bin.tar.gz"]="https://archive.apache.org/dist/tez/0.10.2/apache-tez-0.10.2-bin.tar.gz"
  ["hbase-2.5.15-bin.tar.gz"]="https://archive.apache.org/dist/hbase/2.5.15/hbase-2.5.15-bin.tar.gz"
  ["apache-zookeeper-3.8.4-bin.tar.gz"]="https://archive.apache.org/dist/zookeeper/zookeeper-3.8.4/apache-zookeeper-3.8.4-bin.tar.gz"
  ["openlogic-openjdk-21.0.11+10-linux-x64.tar.gz"]="https://builds.openlogic.com/downloadJDK/openlogic-openjdk/21.0.11+10/openlogic-openjdk-21.0.11+10-linux-x64.tar.gz"
  ["mysql-connector-java-8.0.30.jar"]="https://repo1.maven.org/maven2/mysql/mysql-connector-java/8.0.30/mysql-connector-java-8.0.30.jar"
)

echo "===== Downloading tarballs to $TARBALLS_DIR ====="

TOTAL=${#OFFICIAL[@]}
i=0
for filename in "${!OFFICIAL[@]}"; do
  i=$((i + 1))
  if [ -f "$filename" ]; then
    echo "  [$i/$TOTAL] $filename already exists, skipping"
    continue
  fi
  echo "  [$i/$TOTAL] Downloading $filename ..."
  # Try remote server first
  if curl -sf --connect-timeout 5 "$REMOTE_URL/$filename" -o "$filename" 2>/dev/null; then
    echo "    Downloaded from remote server"
  else
    echo "    Remote unavailable, falling back to official source ..."
    wget -q -O "$filename" "${OFFICIAL[$filename]}"
  fi
done

echo ""
echo "===== Verification ====="
for filename in "${!OFFICIAL[@]}"; do
  if [ -f "$filename" ]; then
    SIZE=$(ls -lh "$filename" | awk '{print $5}')
    echo "  [OK] $filename ($SIZE)"
  else
    echo "  [FAIL] $filename missing!"
  fi
done
echo "===== done ====="
