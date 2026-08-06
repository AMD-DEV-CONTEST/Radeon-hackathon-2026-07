
#!/bin/bash
# scripts/start_milvus.sh
# 启动 Milvus 服务

echo "=============================================="
echo "🚀 Starting Milvus Vector Database"
echo "=============================================="

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found, please install Docker first"
    exit 1
fi

# 检查 Docker Compose 是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not found, please install Docker Compose first"
    exit 1
fi

# 获取项目目录
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 创建 Milvus 配置目录
mkdir -p docker/milvus

# 创建 docker-compose.yml
cat > docker/milvus/docker-compose.yml << 'EOF'
version: '3.5'

services:
  etcd:
    container_name: milvus-etcd
    image: quay.io/coreos/etcd:v3.5.5
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
      - ETCD_SNAPSHOT_COUNT=50000
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/etcd:/etcd
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd

  minio:
    container_name: milvus-minio
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/minio:/minio_data
    command: minio server /minio_data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  standalone:
    container_name: milvus-standalone
    image: milvusdb/milvus:v2.3.3
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/milvus:/var/lib/milvus
    ports:
      - "19530:19530"
      - "9091:9091"
    depends_on:
      - "etcd"
      - "minio"

networks:
  default:
    name: milvus
EOF

echo "✅ docker-compose.yml 已创建"

# 启动 Milvus
echo ""
echo "📦 启动 Milvus 服务..."
cd docker/milvus
docker-compose up -d

# 等待 Milvus 启动
echo ""
echo "⏳ 等待 Milvus 启动 (约 30 秒)..."
sleep 30

# 检查服务状态
echo ""
echo "🔍 检查服务状态..."
docker-compose ps

echo ""
echo "✅ Milvus 已启动"
echo "   📊 端口: 19530"
echo "   📊 管理端口: 9091"
echo "   📊 查看日志: docker-compose logs -f"