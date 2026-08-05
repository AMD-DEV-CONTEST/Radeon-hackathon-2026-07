#!/usr/bin/env bash
# export-cluster.sh — Export Hadoop image + pre-initialized data volumes
# Usage: bash scripts/export-cluster.sh
# Output: C:/Users/feng/Desktop/aiops-cluster-backup.tar.gz (~5GB)
set -euo pipefail

COMPOSE_PROJECT="aiops-ha"
IMAGE_NAME="aiops-hadoop:step1"
BACKUP_DIR="C:/Users/feng/Desktop/aiops-cluster-backup"
OUTPUT_FILE="C:/Users/feng/Desktop/aiops-cluster-backup.tar.gz"

VOLUMES=(
  "hadoop01-data"
  "hadoop02-data"
  "hadoop03-data"
  "mysql-data"
)

echo "===== Exporting Hadoop cluster (image + data volumes) ====="
echo ""

# Pre-check
if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${IMAGE_NAME}$"; then
  echo "[ERROR] Image $IMAGE_NAME does not exist"
  exit 1
fi

mkdir -p "$BACKUP_DIR/volumes"
rm -f "$BACKUP_DIR/image.tar" "$BACKUP_DIR"/volumes/*.tar.gz 2>/dev/null || true

TOTAL=$((${#VOLUMES[@]} + 1))

# 1. Export image
echo "[1/${TOTAL}] Exporting image (~4GB)..."
docker save "$IMAGE_NAME" -o "$BACKUP_DIR/image.tar"
echo "  Done: $(du -sh "$BACKUP_DIR/image.tar" | cut -f1)"

# 2. Export data volumes
i=2
for vol in "${VOLUMES[@]}"; do
  FULL_NAME="${COMPOSE_PROJECT}_${vol}"
  echo "[${i}/${TOTAL}] Exporting volume $FULL_NAME ..."
  # Use stdout redirect, no backup dir mount, bypass Git Bash path issues
  MSYS_NO_PATHCONV=1 docker run --rm --entrypoint tar \
    -v "${FULL_NAME}:/data:ro" \
    "$IMAGE_NAME" \
    czf - -C /data . > "$BACKUP_DIR/volumes/${vol}.tar.gz"
  echo "  Done: $(du -sh "$BACKUP_DIR/volumes/${vol}.tar.gz" | cut -f1)"
  i=$((i + 1))
done

# 3. Pack
echo ""
echo "[3] Packing into aiops-cluster-backup.tar.gz ..."
tar czf "$OUTPUT_FILE" -C "$BACKUP_DIR" .
rm -rf "$BACKUP_DIR"

echo ""
echo "===== Complete ====="
echo "  Output: $OUTPUT_FILE ($(du -sh "$OUTPUT_FILE" | cut -f1))"
echo ""
echo "  Transfer to AMD Cloud: scp $OUTPUT_FILE root@<cloud>:/workspace/"
